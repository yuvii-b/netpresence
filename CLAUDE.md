# Project rules (read before changing anything)

* **Commits**: author `chinchoooo <aravinth3007k@gmail.com>`; never add a Co-Authored-By or any AI attribution line.
* **The simulator and the repo are always at the same level.** The simulator (`backend/sim`, and `backend/netsim` once
  built) must model exactly what the code at that commit does:
  * protocol constants come from the real sources via `backend/sim/protocol.py` - never hand-copied numbers;
  * `backend/tests/test_parity.py` must pass; extend it when the simulator starts depending on something new;
  * a change to the server, phone core, Android/iOS radio code or protocol lands in the SAME commit as the matching
    simulator change (or an explicit "not modelled yet" note in `docs/NETSIM.md`).
* **Runs on the author's Windows laptop**: plain Python 3.11+ and numpy, no Linux-only tools, `pathlib` paths, ASCII
  console output, `multiprocessing`-safe entry points. CI runs on Windows and Linux.
* **Before every commit**: `cd backend && python -m tools.check` must pass (tests, both acceptance studies, phone code vs
  live server). Never loosen a pre-declared acceptance criterion silently.
* **Honesty**: every result says whether it is simulated with assumed values, measured, or from real phones. The native
  Android/iOS code is only compiled by GitHub Actions; say so until it has run on a device.
* **Plan for the paper's simulator**: `docs/SIM_PLAN.md`. Design and current results: `docs/V2.md`.
