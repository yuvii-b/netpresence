# Live roll call (protocol v3): latency and accuracy

**Status: SIMULATED with assumed radio / phone / network values. Nothing here is measured on a real phone.** The native Android/iOS code
has only been compiled by CI, not run on a device. Read this together with `docs/PIVOT_PLAN.md` (the design) and `docs/NETSIM.md`.

## What the student experiences
Teacher taps a subject -> every registered phone of that subject is woken by its long-poll (server wake < 100 ms), checks in, turns
its radio on (already warmed), hears neighbours, reports its neighbour list every 1 s, and the server re-evaluates at most every
300 ms with the real engine. The student's screen goes **Present** the moment the server's verdict arrives.

## Pre-declared acceptance study (`python -m sim.live`, 40 classrooms per row, 93 students, 30 % iPhones, good Wi-Fi)
| criterion (written before the first run) | limit | result |
|---|---|---|
| false-absent at finish, door closed / open | <= 2 % | 0.05 % / 0.05 % |
| corridor phones Present at finish, door open | <= 15 % | 0.94 % |
| time to Present, p50 | <= 2.5 s | 2.03 s |
| time to Present, p95 | <= 5 s | 2.60 s |
| absent friend relayed through an accomplice: flagged / admitted | >= 90 % / <= 10 % | 100 % / 0 % |

Information only: congested Wi-Fi gives p50 2.9 s, p95 4.2 s, false-absent 0.11 %. Teacher finish rule: no change for 5 s and not before 15 s.
Per-size, per-uplink tables: experiment E15; seed modes: E16 (`python -m paper.make --only E15,E16`).

## What the first run found (kept on purpose)
Run 1 of `sim.live` FAILED the relay criterion (80 % flagged, 20 % admitted) while latency and accuracy passed. Cause: the phone kept the median of only the last
20 samples per peer (`LIVE_WINDOW = 20`), too noisy for the co-location detector (spread < 2.5 dB), and the result was read at ~8 s. Fix, not a looser
criterion: `LIVE_WINDOW = 100` and the app's Finish button says "most accurate in N s" until `LIVE_BEST_AFTER_S = 15`. A sweep (40 classrooms each): window 20 -> 8 admitted,
window 100 + finish at 15 s -> 0 admitted, 40 flagged. Students are not slowed down: they are Present after ~2 s; only the teacher's Finish waits for the sharper relay check.

## What the first field test found (kept on purpose)
On real phones a student already shown Present bounced back to "Checking" and again to Present. The simulator showed no flicker (0 students in 40 classrooms), so
it could not predict this: real RSSI near the edge-admission threshold is noisier than the simulator's. Fix (server, `Hub._latch`): once a student is shown
Present they stay Present for the rest of the roll call and their phone just keeps relaying; the final result keeps them too. Only a co-location flag (relay
defence) or the teacher's own decision releases the latch. Trade-off: a corridor phone admitted early by a lucky reading would also stay Present; the simulator's corridor
number (0.94 %) already includes this rule, but it is still simulated, not measured.

## Fingerprint at every roll call (simulated, assumed unlock times)
Each roll call now asks the student for the phone's fingerprint / face / screen lock BEFORE the phone checks in (`live.ts`
phase `confirming`; `need_biometric` if cancelled or none is set up - it never joins without it). The app counts
time-to-Present from after the unlock, so the person's own touch is not system latency, but it spreads when phones join.
`LiveConfig.bio_s_lo/hi` (assumed, default 0 = the pre-declared study is unchanged) models it; 93 students, good Wi-Fi, 12 classrooms:

| unlock time per student | false-absent | time-to-Present p50 | p95 |
|---|---|---|---|
| none (pre-declared study) | 0.0 % | 1.79 s | 2.10 s |
| uniform 1-4 s | 0.0 % | 2.15 s | 3.36 s |
| uniform 1-8 s | 0.0 % | 2.20 s | 5.01 s (just over the 5 s criterion) |

The unlock times are ASSUMED, not measured on phones. The server cannot see the fingerprint: registration stores a
client-attested `bio_registered` flag, and the roll-call prompt is enforced by the app. A modified app could skip it; the
strong version (a signing key that the OS only releases after a fresh fingerprint) is not built.

## Known weak spots (honest)
* Sparse classes (about 20 students): the co-location detector can flag an honest pair and the k-witness pruning then removes students who depended on them; classroom seed 1
  of the default 20-student config collapsed to the teacher only. Over 24 random classrooms of 20 students the live flow had 4.2 % false-absent (the old window flow: 7.8 %) and none collapsed,
  but the weakness is in the engine and is not fixed here.
* Per-model offsets (`rx + tx`) are assumed known to the server; a fresh server without that table is worse at small sizes (E04).
* Uplink: reports are assumed to pay full connection set-up each time (conservative); lost requests cost `REQUEST_TIMEOUT_MS` + first retry. A network that stays dead is not
  modelled in the simulator; the phone shows "No connection" and keeps retrying (`mobile/core/test/live_unit.test.ts`).
* The OMNeT++ model does not have the live flow yet.
* Real numbers needed: time from teacher tap to a real phone saying Present, on a real classroom Wi-Fi with 6-30 phones (`netsim.loadtest` covers the server and network side now).
