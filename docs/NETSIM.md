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
| M2 channel | todo: correlated shadowing, orientation loss, trace-driven mode |
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

## Not modelled yet
Correlated shadowing, phone orientation, packet-level collisions and capture, the Wi-Fi/4G uplink, relay/wormhole attacks,
baselines other than the existing studies. `sim.room`, `sim.orientation`, `sim.platforms` are thin wrappers over netsim and
their acceptance criteria are unchanged.
