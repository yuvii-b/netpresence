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
| M3 link layer | todo: packet-level BLE (`ble_des.py`) |
| M4 phone + uplink | todo |
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

## Findings so far
* **How phones are held matters.** A uniform extra loss (phone on a desk: ~2 dB per end) looks like a larger distance to the
  fixed edge threshold: at 60 students false-absent is 0.5% (hand), 12% (desk), 41% (mixed with pockets/bags), 98% (all in
  pockets). Simulated with assumed losses; E08 sweeps it, and a session-level offset estimate is the candidate fix.

## Not modelled yet
Packet-level collisions and capture, the Wi-Fi/4G uplink, relay/wormhole attacks,
baselines other than the existing studies. `sim.room`, `sim.orientation`, `sim.platforms` are thin wrappers over netsim and
their acceptance criteria are unchanged.
