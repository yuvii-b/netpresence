# Measurements from real phones

Everything in this folder is read by the paper pipeline (`python -m paper.make`). Until files exist here, E12 prints
"NO REAL DATA" and E13 labels its trace SYNTHETIC. Nothing here is ever invented by the simulator.

## sessions.csv  (E12: simulator vs real phones)

One row per real roll call, counted by a human who knows who was really in the room:

| column | meaning |
|---|---|
| `session` | any label, e.g. `2026-11-03-lab6-a` |
| `preset` | the simulator preset that matches the room: `lab6`, `class20`, `class35`, `class60`, `class93`, `exam` |
| `students_inside` | students really inside the room, teacher's seed phones excluded |
| `marked_absent_inside` | how many of them NetPresence did not mark PRESENT (false-absent) |
| `outside` | phones deliberately kept outside (corridor / next room) |
| `marked_present_outside` | how many of those NetPresence marked PRESENT |
| `ios_share` | fraction of the phones that were iPhones (0..1) |

    session,preset,students_inside,marked_absent_inside,outside,marked_present_outside,ios_share
    2026-11-03-lab6-a,lab6,6,0,2,0,0.5

## traces/*.csv  (E13 and `channel = "trace"`)

BLE-lab CSV v2 exported from the app's Lab screen (columns `t_ms,model,platform,peer_eph,distance_m,orientation,bodies,wall,rssi`).
`python -m netsim.traces --help` lists coverage, fit and synthetic-template commands; `python -m tools.fit_pathloss` fits A, n, sigma.

## loadtest-*.json

Written by `python -m netsim.loadtest` (virtual phones against a real server). It measures the server and the network only; the
radio is simulated, so it must NOT be copied into sessions.csv.

## Honest labelling

A number is "measured" only if it came from a file in this folder. Everything else in the paper is "simulated with assumed values"
(see the provenance tags in `netsim/config.py`).
