# netsim: how to run it

Plan and rationale: `docs/SIM_PLAN.md`. Plain Python 3.11+ and numpy; works the same on Windows and Linux.

    cd backend
    python -m netsim.run --preset class93 --trials 60
    python -m netsim.run --preset class60 --set door_open=false --set ios_share=0.5 --set models.iphone.tx=12

`--set` takes any `RoomConfig` field (`netsim/config.py`) and `models.<name>.<attr>`. Presets: `class93 class60 class35
class20 lab6 exam`, or a TOML file in `netsim/presets/` or passed with `--toml`.

## Status (milestones from SIM_PLAN section 8)
| | |
|---|---|
| M1 skeleton | done: config + presets + provenance tags, scenario, channel, fast link layer, phone (tap), server wrapper |
| M2 channel | done: `shadow_model=gudmundson`, `orient_mix/orient_db`, `channel=trace` + `netsim/traces.py`, BLE-lab CSV v2 in the app |
| M3 link layer | done: `--set ble_mode=des` packet-level advertising channel (`ble_des.py`) |
| M4 phone + uplink | done: exact `NeighbourCollector` port + retry schedule + report size pinned to the real TypeScript by generated vectors; `uplink=wifi_good\|wifi_congested\|cell_4g` (mixes allowed) |
| M5 attacks + co-location defence | todo |
| M6 baselines | todo |
| M7 paper pipeline | todo |
| M8 Windows CI hash parity | todo (the Windows job already runs `tools.check`) |
| M9 loadtest | todo |

## Provenance of every default
`netsim/config.py` tags each field `measured`, `spec` or `assumed` (`config.TAGS`; a test fails if one is missing). Protocol
constants (window, tail, min samples, airtime, Android advertise mode) are read from the real code by `sim/protocol.py`.
Everything tagged `assumed` is a guess until the BLE-lab campaign (SIM_PLAN section 5) replaces it.

## BLE-lab CSV v2 and trace-driven channel
The app's BLE lab writes `t_ms,model,platform,peer_eph,distance_m,orientation,bodies,wall,rssi` (pickers for how the phones are
held, people between them, wall). `python -m netsim.traces lab.csv` shows coverage and fitted A, n, sigma;
`python -m netsim.traces --synthesize out.csv` writes a template from the parametric model. Use it with
`--set channel=trace --set trace_file=lab.csv`; pairs without a nearby measurement fall back to the parametric model and are
counted in `trace_fallbacks`.

## Link layers
`ble_mode=fast` (default, analytical Poisson counts) and `ble_mode=des` (every advertising PDU on channels 37/38/39, scanner
window/channel hopping from the Kotlin code, half duplex, collisions with optional capture, 2.4 GHz background, Rician
fading, OS callback loss). A 93-phone DES run takes ~1 s. Without background traffic DES delivers ~7-10% fewer samples per
pair than the fast model (fading drops weak links; checked in `tests/netsim/test_m3_ble_des.py`, tolerance 15%); end to end
both give 0.28% false-absent and 0% corridor admission at 93 students over 20 classrooms.

## Phone and uplink
`netsim/phone.py` ports `aggregate.ts` exactly (round-half-up samples, median of integers, sort, cap). Vectors are produced by
the real TypeScript (`mobile/core/test/fixtures/{collector,retry}-vectors.json`, regenerate with `UPDATE_VECTORS=1 npx vitest
run test/netsim-vectors.test.ts`) and checked on both sides, so editing `aggregate.ts` or `submitReport` without the simulator
fails a test. `--set uplink=wifi_congested` sends every report through a shared-medium Wi-Fi queue with loss, the per-request
timeout (`REQUEST_TIMEOUT_MS`, now in `api.ts`: before, a lost packet could hang the report past the deadline) and the real
retry ladder (0.5 s doubling to 4 s until the report deadline). Reports that miss the deadline make the student absent.

## Findings so far
* **Uplink is not the bottleneck** (93 phones, 40 neighbours each, assumed profiles): 100% delivered on good Wi-Fi (p95 0.35 s),
  99.95-100% on congested Wi-Fi (p95 2.9 s, 1.05 attempts each), 4G p95 1.5 s. Upload jitter 1-4 s does not raise delivery, it
  only adds latency, so it is NOT added to the app. Re-check with `loadtest.py` on the real classroom network (M9).
* **How phones are held matters.** A uniform extra loss (phone on a desk: ~2 dB per end) looks like a larger distance to the
  fixed edge threshold: at 60 students false-absent is 0.5% (hand), 12% (desk), 41% (mixed with pockets/bags), 98% (all in
  pockets). Simulated with assumed losses; E08 sweeps it, and a session-level offset estimate is the candidate fix.

## Not modelled yet
Server overload errors (429/5xx), relay/wormhole attacks,
baselines other than the existing studies. `sim.room`, `sim.orientation`, `sim.platforms` are thin wrappers over netsim and
their acceptance criteria are unchanged.
