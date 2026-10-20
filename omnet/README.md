# NetPresence on OMNeT++

The roll call as a discrete-event simulation in **OMNeT++ 6.x** (the standard network simulator): phones, the shared BLE
advertising channel and the server are OMNeT++ modules; their messages are animated by OMNeT++'s own **Qtenv** viewer. The
server's decision is made by the REAL engine (`backend/app/services/graph.py`), called at the report deadline.

| Module | What it simulates |
|---|---|
| `Phone` | tap delay, radio on, advertising events on channels 37/38/39 (100 ms Android / 150 ms iOS + advDelay), scanner duty cycle, `NeighbourCollector` (median, min samples), signed-report upload with the app's retry ladder (0.5 s doubling to 4 s, 5 s timeout) |
| `BleMedium` | PDU airtime, collisions and optional capture, half duplex, background (Wi-Fi) loss, Rician fading, OS drop, sensitivity |
| `Server` | shared Wi-Fi/4G uplink (FIFO, loss, congestion), report verification queue, refuses reports after the deadline, runs the real engine and shows the verdict |

The channel's MEAN received power per pair (path loss, bodies, wall, door, shadowing) comes from the same Python code as the
Python simulator, so both simulators see identical classrooms; everything that happens in time is OMNeT++.
Protocol constants (window, tail, grace, min samples, retry ladder, timeout) are read from the repo sources by
`backend/sim/protocol.py` and exported to the model - never typed in twice.

## Windows setup (one time)
1. Download **OMNeT++ 6.1 for Windows** from omnetpp.org (the `omnetpp-6.1-windows-x86_64` package, ~600 MB) and unzip it, e.g. to `C:\omnetpp-6.1`.
2. Run `C:\omnetpp-6.1\mingwenv.cmd` (a shell with the compiler and OMNeT++ on the path; first start builds nothing, it is prebuilt).
3. In that shell:
   ```
   cd <repo>\omnet
   opp_makemake -f --deep -o netpresence -O out
   make MODE=release
   ```
4. In the same shell (Python 3.11+ must be on the PATH, with `pip install -r backend\requirements.txt`):
   ```
   cd <repo>\backend
   python -m netsim.omnet_run --preset class93 --seed 1 --gui
   ```
   Qtenv opens. Press **Run** (or **Fast**): phones turn yellow when they tap, blue while advertising/scanning, purple when
   they upload; arrows are the BLE adverts; at the report deadline the engine runs and phones turn **green = present**, **red = absent**,
   **orange = flagged**, grey = never checked in; green lines are the proximity graph the engine built; the black wall has the door gap.

Linux/macOS: same, with `source setenv` instead of `mingwenv.cmd`.

## Commands
```
python -m netsim.omnet_run --preset class93 --seed 1                 # headless, prints the verdict
python -m netsim.omnet_run --preset class93 --relays 2 --gui         # relay attack: watch two radios get flagged
python -m netsim.omnet_run --preset class60 --set door_open=false --set ios_share=0.5 --gui
python -m netsim.omnet_run --compare --preset class60 --seeds 12     # OMNeT++ vs the Python simulator on identical rooms
```
The exported scene and results land in `omnet/generated/last/` (git-ignored); `results/*.sca` are standard OMNeT++ scalar files you can
open in the OMNeT++ IDE's analysis tool.

## Honest status
* The OMNeT++ link layer was written independently of `netsim/ble_des.py`; `--compare` and `tests/netsim/test_m10_omnet.py` check that
  the two agree. Random streams differ, so results agree statistically, not bit for bit.
* A relay's friend is modelled as a second id on the accomplice's radio (same position and channel); the shared-radio collisions between the
  two ids are not modelled.
* Qtenv (the animated window) has been run only on your machine; the build here is headless (Cmdenv).
