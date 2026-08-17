# The Math Behind NetPresence

NetPresence marks attendance by playing a short "song" of tones from the
teacher's speaker and having every student's phone *listen* to that song
through its microphone and decode it back into text. That single sentence
hides five distinct pieces of mathematics:

1. **Turning a letter into a sound** (Frequency-Shift Keying)
2. **Turning continuous sound into numbers a computer can use** (Sampling / Nyquist)
3. **Turning numbers back into "was frequency X present?"** (the Goertzel algorithm)
4. **Deciding "was that a real tone or just noise?"** (Signal-to-Noise Ratio & thresholds)
5. **Deciding "who gets credit, and only once"** (token expiry & replay prevention)

This document walks through the math of each piece from first principles,
using the actual constants from the codebase (`frontend/src/audio/toneEncoder.js`,
`frontend/src/audio/toneDecoder.js`, `backend/app/services/token_service.py`)
so you can trace every formula straight back to a line of code.

No prior signal-processing background is assumed. If you already know what
a sine wave is, feel free to skip to [§3 The Goertzel Algorithm](#3-the-goertzel-algorithm-listening-for-one-note-in-a-crowd),
which is the heart of the system.

---

## 0. The 30-second mental model

Think of the whole system as **musical Morse code**:

- Every character (`0`–`9`, `A`–`Z`) is assigned its own musical note (a
  specific frequency).
- The teacher's browser plays those notes back-to-back, bracketed by a
  "start" note and an "end" note — like a bugle call announcing "message
  incoming" and "message over."
- The student's phone doesn't try to understand the whole sound at once.
  Instead, for every tiny 100-millisecond sliver of audio, it asks 38 very
  specific yes/no questions — *"is note #1 playing right now? Is note #2?
  ... Is the start note? Is the end note?"* — and picks whichever answer
  is loudest.
- Whichever note wins that slice becomes one decoded character, and the
  characters are stitched back into the original token.

Everything below is the math that makes each of those steps precise and
robust to noise, cheap phone microphones, and iOS's aggressive audio
processing.

---

## 1. Sound, in one paragraph

Sound is air pressure wiggling up and down over time. A microphone turns
that wiggle into a voltage, and the browser turns that voltage into a
stream of numbers — a **waveform**. The simplest possible wiggle is a
**sine wave**:

```
x(t) = A · sin(2π f t + φ)
```

- `A` — **amplitude**, how big the wiggle is (loudness)
- `f` — **frequency**, how many full wiggles happen per second, measured
  in Hertz (Hz)
- `t` — time, in seconds
- `φ` — **phase**, where in the wiggle cycle it starts (a left/right shift)

A sine wave is special because it contains **exactly one frequency** — it's
the "atom" of sound. Any other sound (a voice, a chord, traffic noise) is a
sum of many sine waves at different frequencies and amplitudes (this is the
**Fourier** idea: complex sound = many pure tones added together). NetPresence
deliberately uses pure sine-wave tones (`osc.type = 'sine'` in
`toneEncoder.js`) so that decoding reduces to the much simpler question
*"how much energy is at this one frequency?"* rather than having to untangle
a rich, multi-frequency signal like a voice.

---

## 2. Frequency-Shift Keying (FSK): turning letters into notes

### 2.1 The frequency map

Every character in the token alphabet gets its own frequency, spaced evenly
apart:

```
ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"   (36 symbols)

freq(c) = BASE_FREQ + index(c) × FREQ_STEP
        = 1000 Hz    + index(c) × 60 Hz
```

So `'0'` → 1000 Hz, `'1'` → 1060 Hz, `'2'` → 1120 Hz, ... all the way up to
`'Z'` (index 35) → 1000 + 35×60 = **3100 Hz**.

Two extra frequencies act as punctuation, sitting *below* the data range so
they can never be confused with a real character:

```
START_FREQ = 800 Hz   ("here comes a token")
END_FREQ   = 900 Hz   ("token is complete")
```

This is a textbook example of **Frequency-Shift Keying (FSK)** — the same
family of modulation used by old dial-up modems and DTMF touch-tone phones.
Instead of changing a wire's voltage to represent a `0` or `1` (like Morse
code changes a light on/off), we change *which pitch* is playing.

Why 36 evenly-spaced tones and not, say, amplitude levels (loud = 1, quiet =
0)? Because frequency is far more robust to real-world distortion:
distance, room echo, and phone speaker/mic quality all change *volume*
drastically but barely touch *pitch*. Encoding information in frequency
rather than amplitude is precisely why FM radio resists static better than
AM radio — same underlying principle.

### 2.2 Why the tones are spaced 60 Hz apart, not 1 Hz or 500 Hz

This isn't an arbitrary choice — it's tied directly to the math in
[§5](#5-the-resolution-tradeoff-why-60-hz-spacing-and-a-100-ms-window). Spaced
too closely, the decoder can't tell two adjacent notes apart (they blur
into each other). Spaced too far apart, you waste usable frequency range
and risk drifting into frequencies phone speakers/mics reproduce poorly.
60 Hz turns out to be comfortably above the minimum separation the decoder
needs (about 10 Hz — derived later), giving a healthy safety margin against
real-world imperfection.

### 2.3 The envelope: why each tone fades in and out

Look at `_playTone` in `toneEncoder.js`:

```js
gain.gain.setValueAtTime(0, startTime);
gain.gain.linearRampToValueAtTime(0.7, startTime + 0.02);            // fade IN over 20ms
gain.gain.linearRampToValueAtTime(0.7, startTime + durationMs/1000 - 0.02);
gain.gain.linearRampToValueAtTime(0, startTime + durationMs/1000);   // fade OUT over 20ms
```

If a tone just switched instantly from silent to full volume, that instant
jump is mathematically a **discontinuity** — and a Fourier analysis of a
sudden jump shows it isn't just "one frequency," it's smeared across *every*
frequency (this is related to the **Gibbs phenomenon**: sharp edges in time
always leak energy across the whole spectrum). In audio terms this sounds
like an audible "click" or "pop," and in decoding terms it means junk energy
leaks into neighboring frequency bins, confusing the Goertzel detector
described next. Ramping the volume smoothly up and down (a **trapezoidal
envelope**) keeps almost all of the tone's energy concentrated at its
intended single frequency — a cleaner signal in, a more reliable decode out.

---

## 3. Digitizing sound: sampling and the Nyquist limit

Before any of this math can run on a computer, the continuous sound wave
has to become a list of numbers. The microphone hardware measures the air
pressure (via the browser's `AudioContext`) at a fixed rate — the **sample
rate**, typically 44,100 or 48,000 samples per second — and stores each
measurement as a number between -1 and 1.

There's a hard mathematical limit on what frequencies can be captured this
way, the **Nyquist–Shannon sampling theorem**:

```
To faithfully capture a frequency f, you must sample at a rate:
        sample_rate ≥ 2 × f
```

Sample any slower and higher frequencies fold back and masquerade as lower
ones (**aliasing**) — like a spinning wheel that appears to spin backward
under a slow-motion strobe light. NetPresence's highest tone is 3100 Hz, so
it needs a sample rate of at least 6200 Hz. Real devices sample at 44,100+
Hz — over 14× the required minimum — so this system has enormous headroom
and aliasing is never a practical concern here. (This generous margin is
also *why* choosing frequencies up around 800–3100 Hz was safe: it's well
inside both the Nyquist limit and the frequency range phone speakers/mics
reproduce well.)

---

## 4. Detecting a frequency: the Discrete Fourier Transform, the slow way

Before getting to the algorithm this project actually uses, it helps to see
the "obvious but slow" approach it's avoiding.

To test "how much of frequency `f` is present in this chunk of `N`
samples," the direct mathematical tool is the **Discrete Fourier Transform
(DFT)**:

```
X(f) = Σ (n=0 to N-1)  x[n] · e^(-j·2π·f·n / sample_rate)
```

This formula essentially "spins" each sample around a circle at a rate
matching frequency `f` and adds up the results as arrows (vectors). If the
signal really does contain frequency `f`, the spins line up and the arrows
mostly point the same direction, so they add up to something big. If it
doesn't, the spins point every which way, and the arrows cancel out to
something close to zero. The final arrow's *length* tells you how strongly
frequency `f` is present.

The **FFT (Fast Fourier Transform)** is a well-known trick to compute
*every* frequency bin's `X(f)` at once, cleverly, in `O(N log N)` time
instead of the `O(N²)` a naive computation would take. But NetPresence
doesn't need *every* frequency — it only ever needs to check 38 specific
candidate frequencies (36 letters/digits + start + end). Running a full FFT
to then throw away all but 38 of its outputs is wasteful. This is exactly
the situation the Goertzel algorithm was invented for.

---

## 3. The Goertzel Algorithm: listening for one note in a crowd

*(numbered "3" to match its role as the centerpiece — see `goertzel()` in
`toneDecoder.js`)*

### 3.1 The core idea

The Goertzel algorithm computes the exact same "how much energy is at
frequency `f`" answer as one bin of the DFT, but without computing all the
other bins, and without ever explicitly multiplying by a spinning complex
exponential at every step. It rearranges the DFT sum into a **recurrence
relation** — each new output depends only on the current input sample and
the previous two outputs — so a single frequency check costs `O(N)` time
and needs almost no memory, regardless of how many candidate frequencies
you're checking in total. Checking 38 frequencies costs `38 × O(N)`, still
far cheaper than one `O(N log N)` FFT for realistic window sizes, and much
simpler to implement.

### 3.2 Where the recurrence comes from

Start from the DFT formula for one target frequency `f`, and define the
angular frequency:

```
ω = 2π f / sample_rate
```

The DFT sum can be viewed as evaluating a polynomial in `e^(jω)` — and just
like Horner's method lets you evaluate a polynomial with repeated
multiply-and-add instead of computing every power separately, the DFT sum
can be evaluated with a repeated multiply-and-add too. Doing that algebra
(the full derivation is standard and available in any DSP textbook) collapses
into this **second-order IIR (Infinite Impulse Response) filter**:

```
s[n] = x[n] + 2·cos(ω)·s[n-1] - s[n-2]
```

- `x[n]` is the n-th input audio sample
- `s[n]` is a running internal state (initialized `s[-1] = s[-2] = 0`)
- `2·cos(ω)` is a constant computed once per target frequency

Run this for all `N` samples in the window, then compute the final power
(squared magnitude) from just the last two state values:

```
power = s[N-1]² + s[N-2]² − 2·cos(ω)·s[N-1]·s[N-2]
```

Compare this to the actual implementation in `toneDecoder.js`:

```js
goertzel(samples, sampleRate, freq) {
  const N = samples.length;
  const omega = (2 * Math.PI * freq) / sampleRate;
  const coeff = 2 * Math.cos(omega);
  let s1 = 0, s2 = 0;
  for (let i = 0; i < N; i++) {
    const s = samples[i] + coeff * s1 - s2;
    s2 = s1; s1 = s;
  }
  return s2 * s2 + s1 * s1 - coeff * s1 * s2;
}
```

`s1` plays the role of `s[n-1]`, `s2` the role of `s[n-2]` — it's exactly
the recurrence above, one loop iteration per audio sample. No trigonometry
is computed *inside* the loop (only once, for `coeff`, before it starts) —
which is exactly why this is cheap enough to run continuously, in real
time, in a browser's audio callback, 38 times over, many times per second.

### 3.3 Why the output is a good "how loud is this note" measurement

For a real sine wave sitting exactly at frequency `f`, every sample's
contribution rotates in phase with the recurrence and the internal state
`s[n]` grows *linearly* with the number of samples `N` — the terms
reinforce each other (this is called **coherent accumulation**, the same
principle behind how a radio telescope or a matched filter builds up a
faint signal). Since `power` is the square of that state, power from a real
tone grows like `N²`.

Random noise, on the other hand, doesn't rotate in phase with anything — it
accumulates like a **random walk**: its amplitude grows only like `√N`, so
its power grows only like `N`.

That means the ratio of signal power to noise power — the SNR — improves
proportionally to `N` as the analysis window gets longer:

```
SNR(N) ∝ N² / N = N
```

This is called **processing gain**, and it's the mathematical reason a
longer listening window makes a real tone easier to distinguish from
background noise. It's also *why* there's a real cost to making the window
too short (noisier detection) or too long (see the tradeoff in §5 — a
longer window also means slower, less responsive detection, and the window
can't be longer than the tone itself).

### 3.4 Picking the winner among 38 candidates

Each 100 ms audio window is run through `goertzel()` once per candidate
frequency (36 letters + start + end). Whichever frequency produces the
highest `power` is declared `bestFreq` — literally "which of these 38
very specific questions got the loudest 'yes'":

```js
for (const f of CANDIDATES) {
  const p = this.goertzel(window, sampleRate, f);
  totalPower += p;
  if (p > bestPower) { bestPower = p; bestFreq = f; }
}
```

---

## 5. The resolution tradeoff: why 60 Hz spacing and a 100 ms window

There's a fundamental tradeoff in all time-based frequency analysis, sometimes
loosely compared to the Heisenberg uncertainty principle: **you cannot
simultaneously know exactly when something happened and exactly what
frequency it was** — the more precisely you pin down one, the blurrier the
other gets. Concretely, for a window of length `T` seconds, the smallest
frequency difference you can reliably tell apart is approximately:

```
Δf ≈ 1 / T
```

`toneDecoder.js` analyzes a `WINDOW_MS = 100` ms window, so:

```
Δf ≈ 1 / 0.1 s = 10 Hz
```

That means two tones need to be at least roughly 10 Hz apart before the
decoder can reliably tell them apart without their energy "smearing"
into each other's bins. The encoder spaces tones `FREQ_STEP = 60 Hz` apart —
**six times** that minimum — which is a comfortable safety margin that
absorbs real-world imperfections (Doppler-ish pitch drift from cheap
speakers, mic frequency response ripple, small timing jitter) without risking
one letter being misread as its neighbor.

This also explains the relationship between `TONE_MS = 400` (how long each
tone is *played*) and `WINDOW_MS = 100` (how long a *chunk* the decoder
analyzes at once): the decoder doesn't need to see an entire tone to
recognize it, just one 100 ms slice out of the 400 ms the tone is actually
playing. This gives generous timing slack — the decoder's 100 ms analysis
window can land anywhere within a 400 ms tone (even accounting for
network/processing jitter) and still catch it.

---

## 6. Is that a real tone or just noise? Signal-to-Noise Ratio

Finding the *loudest* candidate frequency isn't enough on its own — silence
has a "loudest" candidate too, it's just quiet, random noise. The decoder
needs to distinguish "one candidate is clearly, meaningfully louder than
the others" (a real tone) from "all candidates are roughly equally quiet"
(silence/noise). This is done with two complementary checks.

Framed formally, this is an instance of **binary hypothesis testing** (the
same statistical framework behind medical screening tests and radar
detection): every 100 ms window is either "silence" (H₀) or "tone" (H₁), and
the decoder must pick one using an imperfect, noisy measurement. Any
threshold you pick trades off two kinds of mistakes — a **false alarm**
(calling noise a tone) versus a **miss** (calling a real tone silence). There
is no threshold that eliminates both simultaneously; you can only choose
where on that trade-off curve to sit (this trade-off curve is formally
called an ROC curve — Receiver Operating Characteristic — a concept from the
same theory that gave us the Goertzel/DFT detector in the first place, both
having originated in radar and communications engineering). The two
thresholds below are exactly that choice, made concrete:

### 6.1 Relative check: Signal-to-Noise Ratio (SNR)

```js
const avgPower = totalPower / CANDIDATES.length;
const snr = bestPower / (avgPower || 1);
```

This computes the average power across *all* 38 candidate frequencies (a
proxy for the general noise floor at that moment) and asks: *how many times
louder is the winner than the average competitor?* A value of `snr = 4`
means the winning frequency is carrying 4× as much power as a "typical"
frequency bin right now — a strong sign that this isn't a coincidence.

Using a *ratio* rather than a fixed loudness cutoff is what makes this
robust across wildly different environments: a phone held close to a loud
speaker and a phone across a noisy classroom have totally different
absolute volume levels, but the ratio of "real tone vs. background" stays
comparable in both cases. This mirrors §3.3's processing-gain idea directly
— SNR is quite literally the ratio this section is named after.

### 6.2 Absolute check: a noise floor

```js
const normPower = bestPower / (window.length * window.length);
if (snr < this.powerThreshold || normPower < this.absPowerThreshold) { ... }
```

The SNR check alone has a flaw: in pure silence, all 38 powers are tiny
random noise values, but *by chance* one of them can still end up several
times larger than the average of the others — a high SNR built entirely out
of noise. To guard against that, a **second, absolute** threshold is
required: the winning power, normalized, must also clear a minimum floor.

The normalization `bestPower / N²` cancels out the `N²` growth from §3.3
(recall real-tone Goertzel power grows like `amplitude² × N² / 4`), turning
"power" into something closer to a pure loudness measurement that doesn't
depend on how large the analysis window happens to be. Only when **both**
the relative check (SNR high enough) **and** the absolute check (loudness
above the noise floor) pass does the decoder accept it as a genuine tone —
a tone must be both *clearly the winner* and *actually loud*, which rejects
both "confident-sounding noise" and "genuinely loud but ambiguous" signals.

### 6.3 Why iOS gets different numbers

```js
const THRESHOLDS = {
  ios:     { power: 1.05,    abs: 0.000001 },
  default: { power: 4.0,     abs: 0.0001   },
};
```

Even with `echoCancellation`, `noiseSuppression`, and `autoGainControl` all
requested off in `getUserMedia`, iOS Safari doesn't fully honor that
request — it still runs its own **Automatic Gain Control (AGC)** and noise
suppression in hardware/OS layers the browser can't override. AGC works by
continuously *adaptively* amplifying quiet input and damping loud input to
target a roughly constant output loudness — mathematically, it's a
time-varying, signal-dependent gain multiplier applied *before* the app
ever sees the samples. This actively works against the two checks above: it
compresses genuine tones toward the same loudness as the noise floor
(crushing the SNR ratio down toward 1) and can suppress quiet trailing parts
of a tone as if they were noise (lowering absolute power). The fix isn't
algorithmic — the constants are simply loosened empirically (`power: 1.05`
means "just barely louder than average" instead of `4.0`, and `abs` is
lowered by 100×) to compensate for AGC's distortion, at the acknowledged
cost of being more permissive about false positives on iOS specifically.

### 6.4 The switching is binary, not per-OS — despite what's computed

It's tempting to assume from `platform.js` exporting `getOS()` (which
distinguishes iOS / Android / Windows / macOS / Linux) and `getDeviceType()`
(Mobile / Tablet / Desktop) that thresholds are tuned per-platform. They
aren't. `ToneDecoder`'s constructor computes and stores all of that detail:

```js
this.os = getOS();
this.deviceType = getDeviceType();
const profile = isIOS() ? THRESHOLDS.ios : THRESHOLDS.default;
```

but the actual threshold **lookup is a single boolean branch**: `isIOS()`
true or false. `this.os` and `this.deviceType` are never read again anywhere
in the decoder, and `THRESHOLDS` only ever defines two profiles (`ios` and
`default`) — there's no `THRESHOLDS.android`, no `THRESHOLDS.windows`. In
`StudentScanner.jsx`, `getOS()`/`getDeviceType()` are called a *second*,
independent time purely to render a human-readable label in the UI (e.g.
"Android · Mobile") — that copy never feeds back into detection thresholds
either. So today: **Android, Windows, macOS, and Linux microphones are all
treated identically** (the `default` profile), and only "iOS or not" changes
the math. The richer OS/device data is captured but currently unused for
anything except display — worth knowing if you're ever asked "does this
system tune itself for Android specifically?" (No — Android just happens to
behave close enough to desktop that the shared `default` profile works for
both, in practice.)

---

## 7. Reading a whole token: the arm/disarm state machine

A single physical tone, played for 400 ms, gets analyzed by many
overlapping 100 ms windows as audio streams in — so the *same* tone would
naively get "detected" many times in a row. Concretely: the browser's
`ScriptProcessorNode` delivers audio in fixed-size chunks of 2048 samples
(`createScriptProcessor(2048, 1, 1)`), which at a 44,100 Hz sample rate is
about `2048 / 44100 ≈ 46 ms` of audio per callback. But the Goertzel check
runs on the **last** `windowSize ≈ 4410` samples (100 ms) every single time
a callback arrives — not just once every 100 ms. That means each new
analysis window shares roughly `(4410 − 2048) / 4410 ≈ 54%` of its samples
with the previous one: this is a **sliding (overlapping) window**, advancing
in ~46 ms hops rather than jumping in non-overlapping 100 ms blocks. A tone
lasting 400 ms is therefore going to be seen — and pass the SNR/power
checks — across roughly `400 / 46 ≈ 8-9` consecutive overlapping windows in
a row, all for the *same* physical tone. The decoder needs to count each
physically-played tone exactly once despite that. It does this with a
simple two-state machine, closely related to a **Schmitt trigger** or
hysteresis circuit in electronics (a comparator that requires crossing back below a low
threshold before it will re-trigger on a rise above the high threshold —
this is exactly what prevents "chattering" from a noisy signal near a
single fixed threshold):

```js
if (snr < threshold || normPower < absThreshold) {
  this.armed = true;   // silence → ready to catch the NEXT tone
  return;
}
if (!this.armed) return;   // already inside a tone we've counted — ignore
this.armed = false;        // consume this tone, don't recount it
```

- **Armed** = "I have seen silence since the last tone; I'm ready to
  register a new one."
- **Disarmed** = "I already registered the tone currently playing; ignore
  it until it stops."

This is exactly why the encoder inserts `GAP_MS = 150` ms of silence
between every tone (`toneEncoder.js`): that gap is what lets the decoder
observe "silence" and flip back to armed before the next character's tone
begins. Without that gap, one long 400 ms tone and two adjacent 200 ms
tones would look identical to a decoder with no memory of state — the gap
is the punctuation that makes counting well-defined.

---

## 8. Packet framing: start/end tones as a mini protocol

`START_FREQ` and `END_FREQ` function like the header and footer of a
network packet, or the "AT" and end-of-line in a modem handshake:

```js
if (bestFreq === START_FREQ) { this.started = true; this.tokenChars = []; return; }
if (!this.started) return;                 // ignore noise before a start tone
if (bestFreq === END_FREQ) { /* emit token */ }
```

Mathematically this isn't signal processing so much as a small **finite
state machine** layered on top of the frequency detector: `NOT_LISTENING →
(hear START) → COLLECTING → (hear END) → emit token → NOT_LISTENING`. It
guards against a phone that starts listening mid-transmission, or ambient
noise being mistaken for a stray character, by refusing to collect any
characters until an explicit start-of-message marker is heard.

---

## 9. Trust and replay prevention: the math on the backend

Once a token like `"A7X"` is decoded, `backend/app/services/token_service.py`
has to decide whether to trust it. Two independent time/set-theory checks
guard this, both simple but both load-bearing.

### 9.1 Expiry — a time window

```python
expires_at = now + settings.TOKEN_VALIDITY_SECONDS   # default 60s
...
if now > session["expires_at"]:
    raise HTTPException(..., "Audio token expired.")
```

This is a **TTL (time-to-live)** check: a submission is only valid inside
the half-open time interval `[created_at, created_at + 60s]`. It bounds how
long a token, if overheard or guessed, remains useful — turning a
one-time-use secret into something closer to a rolling secret that
naturally expires, without needing any additional cryptography.

### 9.2 Replay prevention — set membership

```python
nonce_key = f"{session_id}:{student_id}:{decoded_token}"
if nonce_key in self.used_tokens:
    raise HTTPException(..., "Token already submitted.")
self.used_tokens.add(nonce_key)
```

`used_tokens` is a **hash set** — mathematically, a set data structure
backed by a hash function that gives expected `O(1)` (constant-time)
membership checks regardless of how many prior submissions exist. Combining
`session_id`, `student_id`, and `decoded_token` into a single composite key
means the *same* student submitting the *same* token twice for the *same*
session is rejected (blocking naive replay / accidental double-submits),
while still correctly allowing different students to submit that same
overheard token once each, and allowing the same student to participate
again in a different session.

### 9.3 How hard is a token to guess?

The alphabet has 36 symbols. A token of length `L` has:

```
36^L possible values
```

A 3-character token (like the app's default `"A7X"`) has `36³ = 46,656`
possibilities. Within a 60-second validity window, an attacker blindly
guessing tokens over the network — with no rate limiting currently in
place — has a non-trivial chance of a lucky hit; this is explicitly called
out as a known limitation in `docs/STATUS.md`/`README.md` (no auth, fixed
expiry). The real-world deterrent isn't the guess-space size so much as the
fact that the token is only broadcast over audio to students physically
present in the room in the first place — the security model leans on
physical proximity more than on cryptographic hardness. Worth knowing if
this project's threat model ever needs to be tightened (e.g. longer/random
tokens, or a proper HMAC-signed token, would each directly enlarge or
strengthen the guess-space math above).

---

## 10. How much data does a tone-song actually carry?

This is a question that comes up naturally once you've seen the encoding —
and it's answered by **information theory**, specifically the idea (due to
Claude Shannon) that a symbol chosen from `M` equally likely options carries:

```
bits per symbol = log₂(M)
```

Each character here is chosen from `M = 36` symbols, so every tone carries:

```
log₂(36) ≈ 5.17 bits
```

Each character costs `TONE_MS + GAP_MS = 400 + 150 = 550 ms` of airtime
(tone, then its silence gap), plus one extra 550 ms slot each for the
`START` and `END` framing tones. So a 3-character token like `"A7X"` takes:

```
(3 + 2) tones × 550 ms = 2,750 ms ≈ 2.75 seconds
```

to transmit `3 × log₂(36) ≈ 15.5 bits` of actual payload (the start/end
tones carry framing information, not payload). That works out to an
effective **data rate of roughly 5.6 bits/second** — glacially slow by
network standards (a dial-up modem, doing the same job over a wire instead
of open air with a phone mic, ran tens of thousands of times faster), but
that's the deliberate trade-off: every one of those 550 ms is spent buying
robustness — safety margins in frequency spacing (§2.2/§5), the fade
envelope (§2.3), and gaps for state-machine re-arming (§7) — against a
noisy, uncontrolled classroom acoustic channel. This is the same fundamental
tension Shannon's channel capacity theorem describes: a noisier channel
forces a lower achievable data rate for reliable (low-error) communication,
and this system sits deliberately far below what the audio channel could
theoretically carry, in exchange for reliability on cheap hardware.

---

## 11. End-to-end summary

| Stage | Question it answers | Math tool | Where |
|---|---|---|---|
| Encoding | Which pitch means this character? | Frequency-Shift Keying, linear frequency map | `toneEncoder.js` |
| Playback | How to avoid clicks/spectral leakage? | Amplitude envelope (avoids Gibbs phenomenon) | `toneEncoder.js` `_playTone` |
| Capture | How to turn air pressure into numbers without losing information? | Nyquist–Shannon sampling theorem | Browser `AudioContext` |
| Detection | Is frequency *f* present in this chunk? | Goertzel algorithm (DFT recurrence, `O(N)`) | `toneDecoder.js` `goertzel()` |
| Sizing the window | How short can the window be before frequencies blur together? | Time–frequency resolution tradeoff (`Δf ≈ 1/T`) | `WINDOW_MS`, `FREQ_STEP` |
| Confidence | Real tone or noise? | Signal-to-Noise Ratio (relative) + normalized power floor (absolute) | `toneDecoder.js` `onaudioprocess` |
| Counting tones | How to count one long tone once? | Hysteresis / Schmitt-trigger-style state machine | `armed` / `disarmed` logic |
| Framing | Where does a message start/end? | Finite state machine | `START_FREQ` / `END_FREQ` handling |
| Trust | Is this submission valid, fresh, and not a repeat? | Time-window (TTL) + hash-set membership | `token_service.py` |
| Payload size | How much data does the whole token-song actually carry? | Information theory (bits/symbol = log₂(M)) | §10 |

Every threshold, spacing, and window size in this codebase traces back to
one of the formulas above — they aren't arbitrary constants, they're the
smallest values that satisfy the underlying math with a safety margin
(6× the minimum frequency spacing, 14×+ the minimum sample rate, a
100 ms window comfortably inside a 400 ms tone). If you're ever asked *"why
this number and not another,"* the answer is almost always traceable to one
of the derivations in this document.
