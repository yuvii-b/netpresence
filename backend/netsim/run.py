"""Run one configuration over many random classrooms.

    python -m netsim.run --preset class93 --trials 60
    python -m netsim.run --preset class60 --set door_open=false --set ios_share=0.5 --set models.iphone.tx=12 --trials 40

Prints false-absent and corridor false-present rates (mean over classrooms). Deterministic for a given seed range.
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace

from app.services.graph import Params, adaptive_edge_m
from netsim import config
from netsim.server import trial


def _one(args):
    cfg, p, seed = args
    return trial(cfg, p, seed)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preset", default="class93", help=f"one of: {', '.join(sorted(config.PRESETS))} or a presets/*.toml")
    ap.add_argument("--toml", help="extra TOML file of RoomConfig fields")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="override a RoomConfig field")
    ap.add_argument("--trials", type=int, default=30)
    ap.add_argument("--seed0", type=int, default=0)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--no-autocal", action="store_true", help="switch the server's self-calibration off (ablation)")
    ap.add_argument("--json", action="store_true", help="print machine-readable results")
    a = ap.parse_args(argv)
    ov = dict(s.split("=", 1) for s in a.set)
    cfg = config.load(a.preset, a.toml, ov)
    p = Params(max_edge_m=adaptive_edge_m(cfg.students or cfg.capacity))
    if a.no_autocal:
        p = replace(p, autocal=False)
    jobs = [(cfg, p, a.seed0 + s) for s in range(a.trials)]
    with ProcessPoolExecutor(a.workers) as pool:
        rs = list(pool.map(_one, jobs, chunksize=2))
    ins = sum(r["inside"] for r in rs) or 1
    outs = sum(r["outside"] for r in rs) or 1
    res = {"preset": a.preset, "overrides": ov, "trials": a.trials,
           "false_absent_pct": 100 * sum(r["false_absent"] for r in rs) / ins,
           "corridor_false_present_pct": 100 * sum(r["false_present"] for r in rs) / outs}
    print(json.dumps(res, sort_keys=True) if a.json else
          f"{a.preset} {ov or ''}: false-absent {res['false_absent_pct']:.2f}%  "
          f"corridor admitted {res['corridor_false_present_pct']:.2f}%  ({a.trials} classrooms)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
