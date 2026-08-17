# Math Explainer (short version)

A quick, presentation-ready summary of the actual math used in this project
— meant for walking a mentor through *what* algorithm is used *where* and
*why*, without the full derivations. For the in-depth version (proofs,
derivations, edge cases), see `docs/ALGORITHMS.md`.

There are really only three pieces of math worth knowing:

1. **Encoding** — mapping a character to a frequency
2. **Decoding** — the Goertzel algorithm, checking "is this frequency present?"
3. **Trust** — deciding a decoded token is genuine and not a replay

---

## 1. Encoding: each character is a distinct pitch

`frontend/src/audio/toneEncoder.js` assigns every character in the token
alphabet its own frequency, evenly spaced:

```js
freq(c) = BASE_FREQ + index(c) × FREQ_STEP
        = 1000 Hz    + index(c) × 60 Hz
```

`'0'` → 1000 Hz, `'1'` → 1060 Hz, ... `'Z'` → 3100 Hz. Two extra frequencies
(800 Hz and 900 Hz) mark "start of message" and "end of message," like
punctuation. This is **Frequency-Shift Keying (FSK)** — the same idea used
by dial-up modems and DTMF touch-tone phones: instead of a `0`/`1` voltage,
each symbol gets its own pitch. Pitch survives distance, echo, and cheap
speakers/mics much better than volume does, which is why frequency (not
loudness) carries the data.

Each tone is played for 400ms with a smooth fade in/out (not an instant
on/off) — an abrupt jump in volume splatters energy across many
frequencies and would make neighboring tones harder to tell apart, so
volume is ramped up and down instead.

---

## 2. Decoding: the Goertzel algorithm

This is the core algorithm of the whole project. The decoder's job, every
100ms, is: **"of these ~38 known frequencies (36 characters + start + end),
which one, if any, is currently playing?"**

The brute-force way to answer "how much of frequency `f` is in this audio"
is a Discrete Fourier Transform (DFT) — computing every frequency bin from
scratch. That's overkill here: we only ever care about 38 *specific*
frequencies, not the whole spectrum. The **Goertzel algorithm** answers the
same question for one target frequency without computing the others, using
a simple recurrence (each step only needs the current sample and the
previous two results):

```js
// frontend/src/audio/toneDecoder.js
goertzel(samples, sampleRate, freq) {
  const N = samples.length;
  const omega = (2 * Math.PI * freq) / sampleRate;
  const coeff = 2 * Math.cos(omega);
  let s1 = 0, s2 = 0;
  for (let i = 0; i < N; i++) {
    const s = samples[i] + coeff * s1 - s2;
    s2 = s1; s1 = s;
  }
  return s2 * s2 + s1 * s1 - coeff * s1 * s2;   // "power" at this frequency
}
```

Run this once per candidate frequency over a 100ms chunk of microphone
audio, and whichever one returns the highest `power` is the frequency
that's actually playing right now:

```js
for (const f of CANDIDATES) {
  const p = this.goertzel(window, sampleRate, f);
  if (p > bestPower) { bestPower = p; bestFreq = f; }
}
```

**Why Goertzel instead of a full FFT:** an FFT computes *every* frequency
bin in `O(N log N)` time — useful if you need the whole spectrum. Goertzel
computes *one* frequency in `O(N)` time with almost no memory. Since we
only ever check ~38 known frequencies (never "the whole spectrum"),
checking 38 of them with Goertzel is cheaper and simpler than running one
FFT and discarding everything except those 38 bins.

**Why the tones are spaced 60Hz apart:** a 100ms analysis window can only
distinguish frequencies that are roughly `1/0.1s = 10Hz` or further apart
— any closer and they blur together. 60Hz spacing gives 6x that margin,
so small timing jitter or a slightly-off speaker/mic doesn't cause one
character to be misread as its neighbor.

---

## 3. Confidence: is that a real tone, or just noise?

Picking the "loudest" frequency isn't enough by itself — silence has a
loudest candidate too, it's just quiet noise. Two checks together decide
whether to trust a detection:

```js
const avgPower = totalPower / CANDIDATES.length;
const snr = bestPower / (avgPower || 1);                 // relative check
const normPower = bestPower / (window.length * window.length); // absolute check

if (snr < this.powerThreshold || normPower < this.absPowerThreshold) {
  // not a real tone — treat as silence
}
```

- **SNR (Signal-to-Noise Ratio)** — how many times louder is the winning
  frequency than the *average* of all 38 candidates right now? A real tone
  stands out clearly; noise doesn't. Using a *ratio* rather than a fixed
  volume cutoff means it self-adjusts to how loud/quiet the room is.
- **Absolute floor** — a backstop for the case where, by pure chance, one
  noise frequency happens to be a bit louder than the others (a "confident"
  false positive). The winning power must also clear a minimum floor, not
  just beat its neighbors.

A detection only counts if it passes **both** checks. iOS phones use looser
thresholds than everything else, because iOS's microphone pipeline runs its
own automatic gain control that the browser can't fully disable — it
compresses tones toward the ambient noise level, so the same physical sound
produces a lower SNR on iOS than on Android/desktop. (Note: the switch is
literally just "iOS or not" — Android, Windows, macOS, and Linux all share
one set of thresholds; there's no separate per-OS tuning beyond that.)

---

## 4. Trust: is a decoded token valid, and not reused?

Once a token is decoded (e.g. `"A7X"`), the backend (`token_service.py`)
runs two simple checks before accepting it:

```python
if now > session["expires_at"]:            # time-window (TTL) check
    raise HTTPException(..., "Audio token expired.")

nonce_key = f"{session_id}:{student_id}:{decoded_token}"
if nonce_key in self.used_tokens:          # replay check
    raise HTTPException(..., "Token already submitted.")
self.used_tokens.add(nonce_key)
```

- **Expiry** — a submission only counts inside a fixed time window
  (default 60s) after the session started. A token overheard later is
  useless.
- **Replay prevention** — `used_tokens` is a set; checking membership is
  effectively instant regardless of size. Keying it by
  `session_id:student_id:token` means the same student can't submit the
  same token twice, but different students can each submit the same
  overheard token once.

---

For the full derivations (why Goertzel's formula works, the Nyquist
sampling limit, the time/frequency resolution tradeoff, information-theory
data rate, etc.), see `docs/ALGORITHMS.md`.
