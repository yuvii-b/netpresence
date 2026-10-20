"""Acceptance study for the LIVE roll call (protocol v3): 93 students, teacher phone as the seed, phones join by themselves.

    python -m sim.live [--trials 40] [--workers 2]

The criteria below were written BEFORE the first run of this study and must not be loosened to make it pass. Radio, phone
models and network numbers are the simulator's assumed ones (docs/NETSIM.md tags them); this is a SIMULATED result, not a
measurement on real phones. Exits non-zero if any criterion fails.
"""
from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np

from app.services.graph import Params, adaptive_edge_m
from netsim import config
from netsim.live import LiveConfig, live_trial

# ---- pre-declared acceptance criteria (93 students, 30 % iPhones, teacher-phone seed) -----------------------------------------
MAX_FALSE_ABSENT_PCT = 2.0          # students in the room not Present at finish
MAX_CORRIDOR_DOOR_OPEN_PCT = 15.0   # phones outside the wall (door open) Present at finish
MAX_TTP_P50_S = 2.5                 # what the student sees: time from "phone learned of the roll call" to the Present arriving
MAX_TTP_P95_S = 5.0
MIN_RELAY_FLAGGED_PCT = 90.0        # an absent friend relayed through an in-room accomplice is flagged, not admitted
MAX_RELAY_ADMITTED_PCT = 10.0
UPLINK = "wifi_good"
IOS_SHARE = 0.3


def _cfg(**ov):
    return config.load("class93", None, {"uplink": UPLINK, "ios_share": str(IOS_SHARE), **ov})


def _job(a):
    cfg, lc, seed = a
    p = Params(max_edge_m=adaptive_edge_m(cfg.students or cfg.capacity))
    return live_trial(cfg, lc, p, seed)


def run(trials: int, workers: int):
    out = {}
    with ProcessPoolExecutor(workers) as pool:
        for name, cfg, lc in (
            ("door_open", _cfg(door_open="true"), LiveConfig()),
            ("door_closed", _cfg(door_open="false"), LiveConfig()),
            ("relay", _cfg(door_open="false"), LiveConfig(relays=1)),
            ("congested", _cfg(door_open="false", uplink="wifi_congested"), LiveConfig()),
        ):
            out[name] = list(pool.map(_job, [(cfg, lc, s) for s in range(trials)], chunksize=2))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--trials", type=int, default=40)
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args(argv)
    t0 = time.time()
    r = run(a.trials, a.workers)

    def pct(rs, num, den):
        return 100.0 * sum(x[num] for x in rs) / max(sum(x[den] for x in rs), 1)

    def ttp(rs, q):
        v = np.concatenate([x["ttp"] for x in rs])
        return float(np.percentile(v, q))

    do, dc, rl, cg = r["door_open"], r["door_closed"], r["relay"], r["congested"]
    rows = [
        ("false-absent at finish (door closed)", pct(dc, "false_absent", "inside"), f"<= {MAX_FALSE_ABSENT_PCT}", pct(dc, "false_absent", "inside") <= MAX_FALSE_ABSENT_PCT),
        ("false-absent at finish (door open)", pct(do, "false_absent", "inside"), f"<= {MAX_FALSE_ABSENT_PCT}", pct(do, "false_absent", "inside") <= MAX_FALSE_ABSENT_PCT),
        ("corridor Present at finish (door open)", pct(do, "false_present", "outside"), f"<= {MAX_CORRIDOR_DOOR_OPEN_PCT}", pct(do, "false_present", "outside") <= MAX_CORRIDOR_DOOR_OPEN_PCT),
        ("time to Present p50 (s)", ttp(dc, 50), f"<= {MAX_TTP_P50_S}", ttp(dc, 50) <= MAX_TTP_P50_S),
        ("time to Present p95 (s)", ttp(dc, 95), f"<= {MAX_TTP_P95_S}", ttp(dc, 95) <= MAX_TTP_P95_S),
        ("relay friend flagged (%)", pct(rl, "relay_flagged", "relays"), f">= {MIN_RELAY_FLAGGED_PCT}", pct(rl, "relay_flagged", "relays") >= MIN_RELAY_FLAGGED_PCT),
        ("relay friend admitted (%)", pct(rl, "relay_admitted", "relays"), f"<= {MAX_RELAY_ADMITTED_PCT}", pct(rl, "relay_admitted", "relays") <= MAX_RELAY_ADMITTED_PCT),
    ]
    print(f"Live roll call, 93 students, {a.trials} classrooms per row, uplink {UPLINK}, {int(IOS_SHARE * 100)}% iPhones, teacher phone as seed")
    print(f"  {'metric':<42}{'value':>9}   criterion   result")
    for name, v, crit, ok in rows:
        print(f"  {name:<42}{v:>9.2f}   {crit:<10}  {'ok' if ok else 'FAIL'}")
    print("\nInformation only (no gate): ")
    print(f"  finish after {np.mean([x['finish_s'] for x in dc]):.1f} s on average (teacher rule: no change for 5 s, never before LIVE_BEST_AFTER_S)")
    print(f"  flicker (Present then not): {sum(x['flicker'] for x in dc)} students over {a.trials} classrooms")
    print(f"  congested Wi-Fi: false-absent {pct(cg, 'false_absent', 'inside'):.2f}%  time to Present p50 {ttp(cg, 50):.1f} s  p95 {ttp(cg, 95):.1f} s")
    print(f"\n{time.time() - t0:.0f} s. SIMULATED with assumed radio/network values - not measured on real phones.")
    return 0 if all(ok for *_, ok in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
