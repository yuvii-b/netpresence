# Paper material (not the paper)

Everything you need to WRITE the paper, in one place. Numbers come from `results/` (generated, never typed by hand);
regenerate with `python -m paper.make` then `python -m paper.key_numbers`.

## 1. One-paragraph pitch
Instant classroom roll call on phones. Every phone broadcasts a random per-session id in a BLE advertisement and reports the
signal strength (RSSI) of the ids it hears. The server builds a proximity graph and floods trust outward from the teacher's
verified front-bench students; a student is present only with k = 2 vertex-disjoint trust paths. Result: ~25 s for a class of
93 (vs ~4.5 min calling names), no proxy attendance by a single friend, works on Android and iOS, and a relay attack is detected.

## 2. Research questions and the experiment that answers each
| RQ | Question | Experiment | Figure / table |
|---|---|---|---|
| RQ1 | Is it accurate at classroom scale (20-93 students, door open/closed)? | E01 | `e01_accuracy` |
| RQ2 | What does each mechanism (disjoint paths, self-calibration, adaptive edge, tail, k, co-location) buy? | E02 | `e02_mechanisms` |
| RQ3 | Which attacks work, which are stopped? (collusion, relay, RSSI inflation) | E03 | `e03_attacks` (ROC of the co-location threshold) |
| RQ4 | Does it work for any Android/iPhone mix despite TX-power differences? | E04 | `e04_platforms` |
| RQ5 | How fast, and how long does a student wait vs calling names? | E05 | `e05_speed` |
| RQ6 | Is the network a bottleneck? | E06 | `e06_uplink` |
| RQ7 | Do BLE advertising collisions matter at 93 phones? Does the fast model agree with packet-level? | E07 (+ OMNeT++ cross-check) | `e07_ble` |
| RQ8 | Which assumption would hurt most if wrong? | E08 | `e08_robustness` (tornado) |
| RQ9 | How does it compare with manual / BLE beacon / acoustic / QR? | E09 | `e09_baselines` |
| RQ10 | Do the back benches get missed? | E10 | `e10_backbench` |
| RQ11 | Does it scale to large halls? | E11 | `e11_scalability` |
| RQ12 | Does the simulator predict real phones? | E12 | needs real data |
| RQ13 | Do measured RSSI tables change the conclusions? | E13 | needs real data |
| RQ14 | Battery cost per roll call | E14 | arithmetic on assumed currents |

## 3. Contributions you can claim (and the evidence)
1. **Server-side proximity-graph attendance that runs identically on Android and iOS** (iOS cannot advertise custom payloads or set TX power): identity in the 128-bit service UUID. Evidence: design (`docs/V2.md`), E04.
2. **Teacher-rooted, TTL/metre-bounded trust flood with k vertex-disjoint paths (Menger)**: evidence E01, E02 ("no disjoint paths" ablation), E03 collusion table (succeeds exactly when accomplices >= k).
3. **Platform self-calibration from mutual pairs** (no lab calibration for the Android/iOS gap): E04 (12 dB gap: ~27-36% lost -> <1%).
4. **Co-location (relay) detection** from the robust spread of reading differences over common observers: E03 (relay admitted vs flagged, honest false-flag rate, ROC).
5. **A reusable network-simulator methodology**: channel (path loss, bodies, wall, correlated shadowing, orientation), packet-level BLE advertising channel, phone code port pinned to the real TypeScript by generated vectors, uplink with the app's real retry policy, the real server engine in the loop, two independent implementations (Python and OMNeT++) cross-validated on identical rooms. Evidence: `docs/NETSIM.md`, E07, OMNeT++ `--compare`.
6. **Honest provenance:** every parameter tagged spec / assumed / measured; E08 sweeps the assumed ones.

## 4. Method facts you will need (all in the repo)
* **Protocol:** window 20 s + discovery tail 5 s + report grace 10 s; min 3 samples per peer; median RSSI; report <= 200 neighbours; retry 0.5 s doubling to 4 s; request timeout 5 s (constants read from the code by `sim/protocol.py`).
* **Edge admission:** both directions heard, |r_ab - r_ba| <= 8 dB, implied distance <= adaptive threshold (2.0 m for >= 70 check-ins, 2.5 m for 50-69, 3.0 m for 30-49, 3.5 m below); path loss r = A - 10 n log10 d with A = -59 dBm, n = 3 (assumed).
* **Flood:** TTL 8 hops, path <= 15 m, k = 2 vertex-disjoint paths (max-flow); seeds = verified front bench.
* **Crypto:** ECDSA P-256 in Secure Enclave / Android Keystore; signed register / check-in / report messages; per-session nonce; replay refused.
* **Simulator layers:** config with provenance tags -> scenario (bench layout 3 x 8 x 4, wall + door, corridor phones) -> channel -> link layer (fast Poisson | packet-level DES | OMNeT++) -> phone (exact NeighbourCollector port) -> uplink -> **the real `evaluate()`** -> metrics (bootstrap CIs over classrooms, paired differences).
* **Statistics:** the classroom is the unit; pooled rates with 95% bootstrap CI (2000 resamples); comparisons paired on identical seeds; results hashed and identical on Linux and Windows.
* **Cross-validation:** OMNeT++ vs Python on identical rooms, false-absent class35 0.6/0.3%, class60 0.5/0.5%, class93 0.3/0.5% (`python -m netsim.omnet_run --compare`).
* **Reproduce:** `python -m paper.make` (full), `--quick` (smoke), `python -m netsim.loadtest` (server under 93 phones), `tools.check` (all acceptance criteria).

## 5. Threat model table (for the security section)
| Attack | Attacker | Result in simulation | Residual |
|---|---|---|---|
| Corridor / next-room phone | honest but outside | not admitted (E01) | door open: bounded by TTL/edge |
| Remote forger | uploads fabricated links | one-sided edges rejected | - |
| Collusion | c in-room accomplices vouch | works iff c >= k (E03) | raise k, headcount, teacher review |
| Relay / wormhole | accomplice radio also carries friend's id | admitted ~100% without defence, flagged with co-location (E03) | < 10 common observers abstains; per-observer power-varying hardware not modelled |
| RSSI inflation | phone adds +X dB | pooled per platform; lopsided links rejected (E03) | - |
| Replay | resubmit old report | refused: signature binds session | - |
| Id spoof of a present classmate | second radio sends a classmate's id | NOT modelled | future work |

## 6. Honest limitations (put these in the paper)
1. All radio, phone and human parameters are **assumed**, not measured; no BLE-lab data yet (E12/E13 are empty/synthetic until `paper/real/` is filled).
2. The Android and iOS apps were only compiled by CI; never run on a device.
3. Phones in pockets/bags/on desks look farther: a uniform extra loss breaks the fixed edge threshold (E08 / `docs/NETSIM.md` finding); a session-level offset estimate is a candidate fix, not built.
4. A **fresh server without a per-model offset table** loses small classes (E04, 20 students).
5. Large halls (200 seats) need a larger TTL than the default (E11).
6. Very small rooms (< ~20 phones) are weak and the co-location check abstains below 10 observers.
7. iOS works in the foreground only; collusion is mitigated, not eliminated.
8. Baseline parameters (beacon threshold, acoustic SNR, QR sharing) are assumptions (`netsim/baselines.py`).

## 7. Related work: where to look (add real citations yourselves)
No citations are invented here. Search for prior work in these groups and cite what you can read:
* RFID/NFC/QR/biometric/GPS/Wi-Fi attendance systems and their proxy-attendance weaknesses.
* BLE proximity attendance (beacon- or RSSI-based), and BLE contact tracing (RSSI-to-distance error, phone-model offsets).
* Acoustic / near-ultrasound proximity proof (your own v1 trials are the baseline).
* RSSI path-loss and shadowing models (log-distance; Gudmundson spatial correlation), BLE advertising channel specification (Core Spec, Vol 6).
* Relay/wormhole attacks and distance-bounding; Sybil defences; vertex-disjoint paths / Menger's theorem; OMNeT++ (the simulator you used).
* ECDSA P-256 (FIPS 186) and platform key storage.

## 8. Figure and table plan (suggested paper order)
Fig. 1 architecture / flow (draw yourselves; see `docs/V2.md` section 1). Fig. 2 `e01_accuracy`. Fig. 3 `e09_baselines`. Fig. 4 `e03_attacks`.
Fig. 5 `e04_platforms`. Fig. 6 `e02_mechanisms`. Fig. 7 `e10_backbench`. Fig. 8 `e08_robustness`. Fig. 9 `e05_speed`. Optional: `e06`, `e07`, `e11`.
Tables: `tables/E01.tex`, `E09.tex`, `E03.tex`, `E14.tex`. Colour-blind safe palette; PDF vector figures.
Take a screenshot of the OMNeT++ window (`--gui`) and the teacher console for the system section.

## 9. Before you submit (checklist)
- [ ] Run the FULL `python -m paper.make` and re-run `python -m paper.key_numbers`; never quote QUICK numbers.
- [ ] Collect BLE-lab traces (two phones, 0.5-4 m, hand/desk/pocket) -> `paper/real/traces/`; fit with `tools.fit_pathloss`; re-run -> E13 becomes real.
- [ ] Run 3+ real roll calls (even 6 phones, `lab6`) -> `paper/real/sessions.csv` -> E12 becomes the validation section.
- [ ] Measure battery with a USB power meter for E14 (replace assumed currents).
- [ ] Install the APK/IPA, run a real class; report bugs honestly.
- [ ] Add related-work citations; get your professor's view on the threat model.
- [ ] State "simulated with assumed values" next to every simulated number until measured data replaces it.
