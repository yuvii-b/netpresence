"""python -m sim.run [--trials 40] [--out sim/out/sweep.csv]

Bench-column classroom. Sweeps edge threshold x k x shadowing x body loss, then door/occupancy robustness and the
cascade-rule ablation; prints false-absent / false-present (corridor) rates and writes CSVs to sim/out/.
"""
import argparse
import csv
import itertools
import os
import statistics

from app.services.graph import Params
from sim.room import RoomConfig, collusion_trial, trial


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=40)
    ap.add_argument("--out", default="sim/out/sweep.csv")
    ap.add_argument("--uncalibrated", action="store_true", help="skip the per-model RSSI offset correction")
    a = ap.parse_args()

    rows = []
    grid = itertools.product((1.5, 2.0, 3.0), (1, 2, 3), (4.0, 7.0), (0.0, 4.0))
    for edge_m, k, sigma, body in grid:
        cfg = RoomConfig(shadow_sigma=sigma, body_db=body)
        p = Params(max_edge_m=edge_m, k=k, ttl=8, max_path_m=15.0)
        res = [trial(cfg, p, s, calibrate=not a.uncalibrated) for s in range(a.trials)]
        fa = sum(r["false_absent"] for r in res) / sum(r["inside"] for r in res)
        fp = sum(r["false_present"] for r in res) / sum(r["outside"] for r in res)
        rows.append({"max_edge_m": edge_m, "k": k, "shadow_sigma_db": sigma, "body_db": body,
                     "false_absent": round(fa, 4), "false_present_outside": round(fp, 4)})
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)

    print(f"{'edge_m':>6} {'k':>2} {'sigma':>5} {'body':>4} | {'false_absent':>12} {'false_present':>13}")
    for r in rows:
        print(f"{r['max_edge_m']:>6} {r['k']:>2} {r['shadow_sigma_db']:>5} {r['body_db']:>4} | "
              f"{r['false_absent']:>12.1%} {r['false_present_outside']:>13.1%}")
    print(f"\nwritten {a.out}")

    print("\nRobustness (k=2, sigma=5 dB, disjoint paths ON): edge threshold vs door and occupancy")
    print(f"{'edge_m':>6} {'door':>6} {'occup':>6} | {'false_absent':>12} {'false_present':>13}")
    rob = []
    for edge_m, door, occ in itertools.product((1.5, 2.0, 2.5), (False, True), (0.6, 0.75, 0.9)):
        cfg = RoomConfig(door_open=door, occupancy=occ)
        p = Params(max_edge_m=edge_m, k=2, ttl=8, max_path_m=15.0)
        res = [trial(cfg, p, 1000 + s, calibrate=not a.uncalibrated) for s in range(a.trials)]
        fa = sum(r["false_absent"] for r in res) / sum(r["inside"] for r in res)
        fp = sum(r["false_present"] for r in res) / sum(r["outside"] for r in res)
        rob.append({"max_edge_m": edge_m, "door_open": door, "occupancy": occ, "false_absent": round(fa, 4), "false_present_outside": round(fp, 4)})
        print(f"{edge_m:>6} {('open' if door else 'closed'):>6} {occ:>6} | {fa:>12.1%} {fp:>13.1%}")
    with open(a.out.replace(".csv", "_robustness.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rob[0]))
        w.writeheader(); w.writerows(rob)

    print("\nCascade rule: plain k-witness vs k vertex-disjoint paths (edge 2.0 m, k=2)")
    print(f"{'rule':<12}{'door':>7} {'occup':>6} | {'false_absent':>12} {'false_present':>13} {'classes w/ leak':>16}")
    for indep, door, occ in itertools.product((False, True), (False, True), (0.6, 0.9)):
        cfg = RoomConfig(door_open=door, occupancy=occ)
        p = Params(max_edge_m=2.0, k=2, independent=indep)
        res = [trial(cfg, p, 2000 + s, calibrate=not a.uncalibrated) for s in range(a.trials)]
        fa = sum(r["false_absent"] for r in res) / sum(r["inside"] for r in res)
        fp = sum(r["false_present"] for r in res) / sum(r["outside"] for r in res)
        print(f"{('disjoint' if indep else 'k-witness'):<12}{('open' if door else 'closed'):>7} {occ:>6} | {fa:>12.1%} {fp:>13.1%} "
              f"{sum(r['false_present'] > 0 for r in res):>11}/{a.trials}")

    cfg, p = RoomConfig(), Params(max_edge_m=2.0, k=2)
    print("\nCollusion (k=2, edge=2 m): P(remote friend marked PRESENT) vs #accomplices")
    for c in range(0, 5):
        hits = [collusion_trial(cfg, p, s, c) for s in range(a.trials)]
        print(f"  accomplices={c}: {statistics.mean(hits):.0%}")


if __name__ == "__main__":
    main()
