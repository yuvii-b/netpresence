# NetPresence network simulator (netsim) - build plan

Audience: the engineer (or model) who builds it. Everything needed is here; when something is not specified, choose the
simplest option that keeps the acceptance checks green and write the choice down in `docs/NETSIM.md`.

## 0. Why this exists

The paper's evaluation must not depend on getting 90 phones into one room. Undergraduates can realistically get
**4-6 phones they control** (their own, friends') and, with consent, **one or two sessions with a real class** where
only Android students can install the app easily (iPhones need sideloading). So the evaluation is built as:

1. a **layered network simulator** that models every network the system crosses - the BLE advertising channel, the
   phone OS, the Wi-Fi/4G uplink, the server - and runs the **real server engine** unchanged;
2. **calibrated and validated** with what 4-6 phones can measure (trace-driven channel, sample rates, timing);
3. **hardware/network-in-the-loop**: a few real phones plus ~90 virtual phones driving the real server over the real
   classroom Wi-Fi from laptops (a genuine 90-client network load test with no extra phones);
4. optional: one real-class session as the final sim-to-real check.

This is a networks project: the simulator is the main artifact. It must show link-layer, transport/uplink and
protocol (flood/trust) behaviour, not just a geometric toy.

## 1. Hard requirements

| ID | Requirement | Check |
|---|---|---|
| R1 | Runs on the author's **Windows** laptop: Python 3.11+, `numpy`, optional `matplotlib`. No Linux-only deps, no shell scripts, no ns-3 needed. | GitHub Actions job on `windows-latest` runs the quick suite |
| R2 | `multiprocessing` safe on Windows (spawn): workers are top-level functions, every entry point under `if __name__ == "__main__":`, paths via `pathlib`. | same job |
| R3 | Deterministic: same config + seed -> identical JSON results on Windows and Linux. Use `numpy.random.SeedSequence` + `PCG64`, iterate ids in sorted order, never iterate a `set` to make decisions. | CI compares result hashes of the quick suite across OSes |
| R4 | Speed on a 4-core laptop: one 93-phone packet-level run (25 s of air time) < 5 s; quick suite < 2 min; full paper suite < 20 min. | `python -m paper.make --quick` timed in CI |
| R5 | The server logic is the **real** `app.services.graph.evaluate` (and, in API mode, the real FastAPI app). Never re-implement it. | import check + existing API-parity test |
| R6 | Every number in the paper is produced by `python -m paper.make` from code + configs; nothing hand-typed. | `paper/out/summary.md` regenerated in CI |
| R7 | Commits authored `chinchoooo <aravinth3007k@gmail.com>`, no co-author lines. `python -m tools.check` stays green after every milestone. | git log, CI |

## 2. Layout

```
backend/netsim/
  __init__.py
  config.py        dataclasses for every layer + TOML loading (stdlib tomllib) + named presets
  scenario.py      room geometry, people, phones (platform profiles), corridor, attackers  (moved from sim/room.py)
  channel.py       PHY: parametric path loss, CORRELATED shadowing, bodies, wall/door, fast fading; trace-driven mode
  ble_fast.py      analytical link layer (today's Poisson sample model, moved from sim/room.py)
  ble_des.py       packet-level discrete-event link layer (advertising events, scanning, collisions, capture)
  phone.py         app/OS layer: tap time, start-up, OS report filtering, NeighbourCollector (exact port of the TS one)
  uplink.py        Wi-Fi / 4G uplink with shared-medium contention, loss, timeouts, exact client retry policy
  server.py        wraps the real engine; optional API mode through the real FastAPI app (in-process ASGI)
  attacks.py       corridor phones, remote fabricators, colluders, relay/wormhole, RSSI inflation, report replay
  baselines.py     manual roll call, single teacher beacon, acoustic broadcast (v1), rotating QR, ablations
  metrics.py       per-trial metrics, classroom-level bootstrap CIs, paired differences
  runner.py        parallel execution, result cache keyed by config hash (results/<hash>.json)
  plots.py         one matplotlib style, PDF + PNG, colour-blind safe palette
  loadtest.py      virtual phones over a REAL network against a real server (hardware/network in the loop)
  traces.py        load BLE-lab CSV v2 -> empirical channel tables
  experiments/     e01_accuracy.py ... e14_energy.py (section 6)
backend/paper/make.py   runs experiments -> paper/out/{figures/*.pdf, tables/*.tex, results/*.json, summary.md}
docs/NETSIM.md          how to run, add an experiment, plug in traces, every default and where it came from
```

`sim/room.py`, `sim/orientation.py`, `sim/platforms.py` stay as thin wrappers over `netsim` (their tests and the two
acceptance studies must keep passing with identical criteria).

## 3. Layers - exact models and defaults

Units: metres, milliseconds (link layer) / seconds (app), dBm/dB. Every default carries a tag in `config.py`:
`[measured]`, `[spec]` (from a standard / AOSP), or `[assumed]`. The paper's sensitivity study (E8) sweeps every
`[assumed]` value.

### 3.1 Scenario (`scenario.py`)
Reuse the bench room: 3 bench columns x 8 benches x 4 seats, seat pitch 0.5 m, aisle 0.8 m, bench pitch 1.1 m,
capacity 93; side wall with a 1 m door at the back; corridor phones 0.8-3 m past the wall. Add:
* `orientation` per phone: `hand` | `desk` | `pocket` | `bag` with extra loss 0 / 2 / 6 / 10 dB `[assumed]`.
* `seat_of(phone)` so per-seat metrics (E10) are possible.
* Presets: `class93`, `class60`, `class35`, `class20`, `lab6` (6 phones on one bench, for sim-to-real), `exam`
  (every second seat).

### 3.2 Channel / PHY (`channel.py`)
Mean RSSI of i hearing j:
`P_tx(j) + G_rx(i) - PL(d) - L_body - L_wall - L_orient(i) - L_orient(j) + S_ij`
* `PL(d) = PL0 + 10 n log10(d / 1 m)`, `PL0` chosen so a reference pair reads `A = -59 dBm` at 1 m; `n = 3.0` `[assumed]`.
* **Correlated shadowing** (new; needed for honest co-location tests): Gudmundson model. Give every phone a latent
  2-D position field: `S_ij = sigma * (z_i + z_j + w_ij) / sqrt(3 + 2 rho_ij)` where `z` is a spatial Gaussian field
  sampled at the phone positions with correlation `rho = exp(-dist / d_corr)`, `d_corr = 1.0 m` `[assumed]`, and `w_ij`
  i.i.d. N(0,1); the divisor keeps `Var(S_ij) = sigma^2` for every pair. `S_ij = S_ji` (reciprocal). `sigma = 5 dB`
  `[assumed]`. Sample `z` with a Cholesky of the n x n correlation
  matrix (n <= ~110, cheap).
* Bodies: occupied seats within 0.35 m of the segment, 3 dB each, capped at 3 `[assumed]`. Wall 12 dB unless through the
  door `[assumed]`. Keep the vectorised implementation from `sim/room.py` (only pairs < 8 m).
* Per-packet fast fading: Rician with K = 3 dB in amplitude, applied per received PDU (DES) or as the per-sample sigma
  (fast mode) `[assumed]`.
* Receiver sensitivity -95 dBm `[spec-ish]`; a PDU below it is not received.
* **Trace-driven mode**: instead of the parametric mean+shadowing, draw `RSSI | (distance bin, bodies, wall, model pair,
  orientation)` from empirical CDFs built by `traces.py` from BLE-lab CSV v2 (section 5). Distance bins 0.25 m up to 8 m.
  Fall back to parametric for empty bins and count the fall-backs in the result JSON.

### 3.3 BLE link layer - packet-level DES (`ble_des.py`)
This is the core networking model. Simulate the advertising channel for the whole room for the discovery period.
* **Advertiser** (per phone, from its platform profile): advertising events every `advInterval + advDelay`,
  `advDelay ~ U(0, 10) ms` `[spec: BLE Core Vol 6 B 4.4.2.2]`. Each event sends the same PDU on channels 37, 38, 39 in
  order, inter-PDU gap `t_ifs_adv = 0.4 ms` `[assumed, typical]`. PDU airtime at LE 1M:
  `(1 preamble + 4 access address + 2 header + payload + 3 CRC) * 8 us`; our payload = 6 (AdvA) + 21 = 27 bytes ->
  `(1+4+2+27+3)*8 = 296 us`. Android `ADVERTISE_MODE_LOW_LATENCY` = 100 ms `[spec: AOSP]`; iOS foreground interval
  `[assumed]` 150 ms (sweep 20-300 ms).
* **Scanner**: scan window / interval per platform. Android `SCAN_MODE_LOW_LATENCY` = 4096 / 4096 ms (continuous),
  `BALANCED` 1024/4096, `LOW_POWER` 512/5120 `[spec: AOSP]`. Channel advances 37 -> 38 -> 39 every scan interval,
  random phase per phone. iOS `[assumed]`: continuous, 30 ms channel dwell (sweep).
* **Half-duplex**: a phone cannot receive while it is transmitting one of its own PDUs.
* **Collisions and capture**: on the same channel, two PDUs overlapping in time at a receiver collide. With capture
  enabled, the stronger survives iff its power exceeds the sum of the interferers by `capture_db = 6 dB` `[assumed]`;
  without capture both are lost. Interferer powers come from the same channel model (each receiver sees its own SINR).
* **2.4 GHz background**: per channel a busy probability `p_bg` (37: 0.05, 38: 0.10, 39: 0.05 `[assumed]`, Wi-Fi channel
  6 overlaps 38 most); a PDU arriving during background busy is lost.
* **OS reporting filter** (platform profile): Android `CALLBACK_TYPE_ALL_MATCHES` reports every received PDU; iOS with
  `AllowDuplicates` may coalesce: report a peer at most every `ios_min_report_ms` (default 0 = every PDU, sweep up to
  1000 ms) `[assumed]`.
* **Implementation for speed** (R4): generate all PDUs as numpy arrays (t_start, t_end, channel, sender). Per channel,
  sort by start, find overlaps with a sweep (`searchsorted` on ends). For each PDU, compute the receiver set as a boolean
  vector: listening (scanner on that channel at t, vectorised from phase/window), not transmitting, above sensitivity,
  survives collision/capture, survives background. Accumulate per (receiver, sender) RSSI samples into preallocated
  arrays (cap 200 per pair, like the app). Target: < 5 s for 93 phones x 25 s.
* Output identical in shape to `ble_fast`: per ordered pair the list (or count + median) of RSSI samples.

### 3.4 BLE link layer - fast analytical mode (`ble_fast.py`)
Today's model: `m_ij ~ Poisson(overlap * 1000/adv_j * scan_eff_i * p_ok)`, `p_ok = exp(-2 * airtime * sum(1/adv))`,
median noise `1.2533 * sigma_fast / sqrt(m)`. Keep it as the default for big sweeps. **E7 must show fast vs DES agreement**
(samples per pair within 15%, false-absent within the CIs) to justify using it.

### 3.5 Phone / app / OS (`phone.py`)
* Human tap delay: lognormal, median 4 s, log-sd 0.6 `[assumed]` (E5 sweeps median 2-10 s).
* Start-up: tap -> radio on = check-in RTT (from `uplink`) + `radio_start_ms` (Android 150 ms, iOS 300 ms `[assumed]`).
* Check-in closes at `WINDOW_SECONDS`; discovery runs to `window + DISCOVERY_TAIL_SECONDS`; late tappers cannot join.
* App killed / screen locked mid-roll-call with probability `p_abort` (default 0.01 `[assumed]`): radio stops at a uniform
  random time.
* **NeighbourCollector**: exact Python port of `mobile/core/src/aggregate.ts` (median per peer, ignore self, ignore
  rssi >= 0 and 127, `minSamples = 3`, cap 200). Parity test against vectors generated by the TS code (section 7).
* Report size: `bytes = 120 + 38 * neighbours` (JSON + signature) `[measured from a real request in API mode]`.

### 3.6 Uplink network (`uplink.py`)
Models the classroom network the reports cross. All phones in a class upload at nearly the same moment (discovery end),
which is a classic synchronised-burst problem.
* Profiles (each per-phone or mixed by fraction):
  * `wifi_good`: RTT lognormal median 15 ms, loss 0.5%, shared capacity 30 Mbit/s.
  * `wifi_congested`: RTT median 80 ms with heavy tail (log-sd 1.0), loss 3%, shared capacity 5 Mbit/s, plus a
    contention penalty: effective capacity `C / (1 + alpha * active_stations)`, `alpha = 0.02` `[assumed]` (802.11 DCF
    efficiency drops with stations).
  * `cell_4g`: RTT median 60 ms, loss 1%, independent per phone, 1% chance of a 1-3 s stall.
* The shared medium is a single FIFO server with the profile's capacity: each request's transfer time = queueing +
  size / capacity; then the RTT; then the server service time (`verify_ms = 1.5`, `close_ms` measured, `[measured]`).
  Requests time out after 8 s.
* **Client retry policy = exactly `submitReport` in `mobile/core/src/session.ts`**: delay 500 ms doubling to 4 s while
  `now + delay <= report_deadline`; only transient errors (timeout, 5xx, 429) retried. Parity test (section 7).
* Optional mitigation to evaluate (E6): **upload jitter** - each phone waits `U(0, J)` before its first attempt
  (J = 0, 1, 2, 4 s). If it clearly helps, implement it in the TS core afterwards (small change, own commit + tests).
* Outputs: per phone delivered/not by deadline, attempts, delivery time; per class p50/p95 time to "all reports in".

### 3.7 Server (`server.py`)
* Default: build `reports` exactly as `_compute` does (eph id -> student, per-model offset, platform groups) and call the
  real `evaluate`.
* `--api` mode: drive the real FastAPI app in-process (existing `sim/e2e.py` approach) for end-to-end runs; must give
  identical verdicts (existing parity test extended to DES mode).
* Record engine wall time per close (E11).

### 3.8 Attacks (`attacks.py`) - each returns modified reports and/or extra on-air transmitters
| Attack | Model | Expected outcome today |
|---|---|---|
| A1 corridor | honest phones outside, behind wall/door | admitted only via door/leaks (C1) |
| A2 remote fabricator | absent student uploads a signed report claiming strong links to random in-room ids | never admitted (no reverse direction) |
| A3 collusion | `c` in-room accomplices add fabricated mutual links with the absent friend | succeeds iff `c >= k` |
| A4 **relay / wormhole** | one in-room accomplice's phone ALSO advertises the absent friend's UUID (Android can run several advertising sets; iOS can list two service UUIDs); the friend uploads a report that mirrors what honest neighbours of the accomplice measured | **likely succeeds with c = 1 - the gap to close** |
| A5 RSSI inflation | a phone adds +X dB to all its readings (vs self-calibration) | pooled self-cal resists (C4) |
| A6 replay | resubmit a previous session's signed report | rejected by session binding (API mode only) |
| A7 eph-id spoof | advertise a classmate's current UUID to steal their links | classmate still also advertises -> co-location / duplicate detection |

### 3.9 Defence to add: co-location (Sybil/relay) detection - server side
Put it in `app/services/graph.py` (it is a server defence, so it must ship, not just be simulated), behind a param
`colocation_db` (default to be chosen by E3/E8; start at 2.5), with API exposure like other params.
* For every pair of ids (u, v) with at least `m = 5` common observers o (o heard both u and v), compute
  `D(u,v) = median_o |r_ou - r_ov|` (after self-calibration).
* One radio emitting two ids gives the same channel to every observer: D ~ measurement noise (~1-2 dB). Two people
  even 0.5 m apart differ by the independent part of shadowing (~sigma * sqrt(2/3) ~ 4 dB with correlation) - E3
  measures the real separation including correlated shadowing; pick `colocation_db` at the best Youden point.
* If `D(u,v) < colocation_db`: mark both FLAGGED with reason `co-located`, never PRESENT automatically; surface to the
  teacher (the console already lists FLAGGED rows). Also: a single received PDU containing two NetPresence UUIDs is
  direct evidence - the native scanners should report all prefix matches, not just the first (small native change).
* Cost: O(ids^2 * observers) worst case ~ 1e6 ops at 100 phones; vectorise with numpy on the RSSI matrix (NaN for
  missing) - must stay < 50 ms.
* Tests: relay (A4) is flagged in >= 95% of trials; honest bench-mates flagged in <= 1% (FPR) in the class93 preset.

### 3.10 Baselines (`baselines.py`) - same rooms, same seeds
| Baseline | Model | Metrics it competes on |
|---|---|---|
| B0 manual roll call | per student `U(1.5, 3) s` + 20% need a repeat call; proxy answering for absentees succeeds with p = 0.5 `[assumed]` | time, proxy attendance |
| B1 teacher beacon | one BLE beacon at the teacher's desk; present iff median RSSI > threshold (best threshold per head-count, chosen on held-out seeds) | false-absent at back benches, corridor leak |
| B2 acoustic broadcast (v1) | teacher phone speaker 75 dB SPL at 1 m `[assumed]`, -6 dB per doubling + 1 dB per body in path; ambient noise lognormal around 58 dB (fans) `[assumed]`; detection iff SNR > per-device threshold (iPhone mic offset from the email thread: ~20x threshold ~ 13 dB) | false-absent per seat (back bench), sensitivity to fans |
| B3 k-witness without disjoint paths | engine with `independent=False` | corridor leak (C2) |
| B4 no self-calibration | `autocal=False` | mixed-fleet false-absent (C4) |
| B5 rotating QR on the projector | anyone who sees the screen is present; photo forwarded to absent friends with p_share `[assumed]` | proxy attendance |

### 3.11 Metrics (`metrics.py`)
Per trial (one classroom = one trial): false-absent rate (FAR), corridor false-present rate (FPR), attack success,
time to "teacher has result" (last report or deadline), per-student wait, reports delivered, bytes on air
(PDUs x airtime x channels), uplink bytes, energy (section 3.12), engine ms.
**Statistics**: the classroom is the unit. 95% CIs by bootstrap over classrooms (2000 resamples). Comparisons between
variants use **paired** bootstrap on per-classroom differences (common random numbers are already used: one
`SeedSequence` per noise source). Report mean +- CI everywhere; never a bare percentage.

### 3.12 Energy
`mAh = (I_scan * t_scan + I_adv * duty_adv * t_adv + I_cpu * t) / 3600`; defaults Android scan 10 mA, adv 4 mA,
iOS similar `[assumed]`; screen-on 120 mA dominates - report both with and without the screen.

## 4. Configuration and running
* TOML presets in `backend/netsim/presets/*.toml`; every field overridable from the CLI:
  `python -m netsim.run --preset class93 --set ble.mode=des --set uplink.profile=wifi_congested --trials 60`
* `python -m paper.make [--quick] [--only E03,E06] [--workers N]` -> `paper/out/`. `--quick` = fewer trials, every
  experiment still runs (CI). Results cached by config hash so re-running only recomputes what changed.
* Every experiment file exposes `EXPERIMENT = {id, title, sweep, trials_quick, trials_full, run(), plot(), table()}`.

## 5. Real data with 4-6 phones (no 90-phone requirement)

### 5.1 BLE lab CSV v2 (app change, small)
Extend the lab export to: `t_ms,model,platform,peer_eph,distance_m,orientation,bodies,wall,rssi` (one row per sample).
The lab screen gets three pickers: distance, orientation, bodies-between (0/1/2/3), wall yes/no.

### 5.2 Measurement campaign (one afternoon, 4-6 phones, the real classroom)
1. **Path loss**: two phones of the same model, 30 s each at 0.5, 1, 1.5, 2, 3, 4, 6, 8 m, orientations hand/desk.
   Repeat for every model you have (gives per-model link budget + n + sigma).
2. **Bodies**: same pair at 2 m with 0, 1, 2, 3 friends standing in between.
3. **Wall/door**: one phone in the corridor at 1 and 3 m from the wall, door closed and open.
4. **Cross-platform asymmetry**: an Android and an iPhone, both logging each other, 1-4 m (measures the real gap that
   self-calibration removes - replaces the `[assumed]` iOS TX value).
5. **Sample rate**: 2, 4, 6 phones advertising together, how many samples/s each sees per peer (validates the link layer).
6. **Tap timing**: in any lecture, time how long the class takes to react to "everyone tap now" (phone stopwatch,
   no app needed).
`traces.py` turns these files into the empirical channel tables (3.2) and fitted defaults; `paper.make` reports which
defaults are now `[measured]`.

### 5.3 Network-in-the-loop load test (`loadtest.py`)
Run the real server on one laptop, `python -m netsim.loadtest --server http://<ip>:8000 --phones 93` on one or two
other laptops in the same classroom Wi-Fi. Virtual phones (real P-256 keys, real signed requests, the scenario's
synthetic BLE readings) check in at simulated tap times and upload at discovery end, with and without upload jitter.
This measures the **real** network's delivery and latency under a 93-client burst - the uplink model (3.6) is then
validated against it. No extra phones needed.

### 5.4 Small real sessions
* `lab6` preset: 6 real phones on one bench + 2 in the corridor; run 10 roll calls; compare observed vs predicted.
* Optional real class (consent first): Android students install the APK; iPhone students simply don't participate ->
  a natural partial-coverage experiment (the simulator can model "only fraction f of the class runs the app").

## 6. Experiments (each = one file in `netsim/experiments/`, one figure and/or table)

| ID | Question | Sweep | Output |
|---|---|---|---|
| E01 | Accuracy at classroom scale | head-count 20-93 x door open/closed | Fig: FAR and FPR vs head-count with CIs |
| E02 | What each mechanism buys | full / no disjoint / no self-cal / no adaptive edge / no tail / k=1,2,3 | Table: FAR, FPR, attack success |
| E03 | Attacks and the co-location defence | A3 accomplices 0-4 x k; A4 relay with/without defence; A5 X=0-20 dB | Fig: success rates; ROC for `colocation_db` |
| E04 | Android/iOS mix | iOS share 0-100% x TX asymmetry 0-18 dB | Heatmap: FAR, self-cal on vs off |
| E05 | How fast can it be | check-in window 10-45 s x tap median 2-10 s | Fig: FAR; CDF of total roll-call time vs manual roll call |
| E06 | Uplink under a synchronised burst | profile x jitter J x head-count | Fig: delivery % and p95 completion time |
| E07 | BLE link layer | phones 10-120 x adv interval x scan mode x capture; DES vs fast | Fig: samples/peer, discovery latency; agreement plot |
| E08 | Robustness to assumptions | every `[assumed]` parameter low/high | Tornado chart: delta FAR, delta FPR |
| E09 | Versus alternatives | B0-B5 | Table/bar chart: FAR, FPR, proxy success, time |
| E10 | Back-bench problem | per seat | Heatmap of per-seat FAR: acoustic (B2) vs teacher beacon (B1) vs NetPresence |
| E11 | Scalability | students 50-500 (bigger rooms), engine time, sim time | Fig: ms vs N |
| E12 | Sim-to-real | lab6 sessions + load test | Fig: predicted vs observed |
| E13 | Trace-driven channel | E01 with measured traces vs parametric | Fig: overlay |
| E14 | Energy per roll call | platform x window | Table: mAh |

## 7. Tests the builder must add (pytest, in `backend/tests/netsim/`)
* airtime formula; advertising event timing (`advDelay` bounds); scanner channel schedule.
* collisions: two overlapping PDUs on one channel lost without capture; with capture the 6 dB-stronger one survives;
  different channels never collide; half-duplex blocks own reception.
* DES vs fast: samples per pair within 15% for N = 10, 30, 93 (capture off), seeds fixed.
* correlated shadowing: reciprocity `S_ij == S_ji`; empirical correlation of `z` at 1 m ~ exp(-1) +- 0.1.
* NeighbourCollector parity: `mobile/core/test/collector-vectors.json` generated by a new TS test, consumed by Python.
* retry parity: Python uplink retry times equal `submitReport`'s schedule (vector file generated from the TS code).
* co-location: relay flagged >= 95%, honest FPR <= 1% (class93, 60 trials).
* determinism: two runs, same seed -> identical JSON; Windows/Linux hash comparison in CI.
* parity: fast mode with the old defaults reproduces today's `sim.platforms` / `sim.orientation` results (same
  criteria pass).
* API mode == engine mode on 3 seeds, fast and DES.

## 8. Milestones (each its own commit; `python -m tools.check` green after each)
1. **M1 skeleton**: `netsim` package, config + presets, scenario + fast channel moved from `sim/room.py`; old studies
   become wrappers; parity test.
2. **M2 channel**: correlated shadowing, orientation loss, trace-driven mode + `traces.py` + BLE-lab CSV v2 (app change).
3. **M3 link layer**: `ble_des.py` + tests + E07.
4. **M4 phone + uplink**: `phone.py` (collector port + vectors), `uplink.py` (retry parity), E05, E06.
5. **M5 attacks + co-location defence** in the server engine (+ API tests, console shows the reason) + E03; native
   scanners report every prefix match per PDU.
6. **M6 baselines**: B0-B5 + E09, E10.
7. **M7 paper pipeline**: metrics/bootstrap, runner cache, plots, `paper/make.py`, remaining experiments, `summary.md`.
8. **M8 Windows + docs**: `windows-latest` CI job (quick suite + hash parity), `docs/NETSIM.md`.
9. **M9 loadtest** + E12 harness (ready for the measurement afternoon).

## 9. Things that must not change silently
* The on-air format, signed message formats and API fields (TS core, native code and `docs/test-vectors.json` depend
  on them). Any change: update all three + tests in the same commit.
* The 13 + 6 acceptance criteria in `sim.orientation` / `sim.platforms`. If new realism (e.g. correlated shadowing)
  makes one fail, do not loosen it silently: report it, then fix the system or justify the criterion change in the
  commit message.
* Honesty in `docs/V2.md`: every result says whether it is simulated with assumed, measured, or real data.
