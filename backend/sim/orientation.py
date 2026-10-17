"""Acceptance study for the target classroom: THREE bench columns, 4 students per bench, 8 benches deep
(96 seats), at most 93 students, teacher verifies the front bench.

    python -m sim.orientation [--trials 40] [--workers 2]

Runs the real graph engine over Monte-Carlo radio scenes (see sim.room for the radio model) and checks the
results against explicit acceptance criteria; exits non-zero if any fail.
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace

from app.services.graph import Params, adaptive_edge_m
from sim.room import RoomConfig, collusion_trial, trial

BASE = RoomConfig(students=93)          # 3 x 8 x 4 = 96 seats, 93 seated


def adaptive(n_seated: int, cfg: RoomConfig = BASE) -> Params:
    """What the server does by default: edge threshold chosen from the number of CHECK-INS (seated + corridor phones)."""
    return Params(max_edge_m=adaptive_edge_m(n_seated + cfg.n_outside))


def _job(args):
    kind, cfg, p, seed, extra = args
    if kind == "trial":
        return trial(cfg, p, seed)
    return {"hit": collusion_trial(cfg, p, seed, extra)}


def _run(pool, jobs):
    return list(pool.map(_job, jobs, chunksize=4))


def _agg(res):
    ins, outs = sum(r["inside"] for r in res), sum(r["outside"] for r in res)
    hops = sorted(r["max_hops"] for r in res)
    path = sorted(r["max_path_m"] for r in res)
    q = lambda xs, f: xs[min(len(xs) - 1, int(f * len(xs)))]   # noqa: E731
    return {
        "fa": sum(r["false_absent"] for r in res) / ins,
        "fp": sum(r["false_present"] for r in res) / outs if outs else 0.0,
        "leak_classes": sum(r["false_present"] > 0 for r in res) / len(res),
        "hops_p95": q(hops, 0.95), "hops_max": hops[-1],
        "path_p95": q(path, 0.95), "path_max": path[-1],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=40)
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()
    N, t0 = a.trials, time.time()
    checks: list[tuple[str, bool, str]] = []
    P = Params()
    cfg0 = BASE
    seats = cfg0.bench_cols * cfg0.bench_rows * cfg0.seats_per_bench
    width = cfg0.bench_cols * cfg0.seats_per_bench * cfg0.seat_pitch + (cfg0.bench_cols - 1) * cfg0.aisle
    print(f"Room: {cfg0.bench_cols} bench columns x {cfg0.bench_rows} benches x {cfg0.seats_per_bench} seats = {seats} seats "
          f"(capacity {cfg0.capacity}); {width:.1f} m wide, {(cfg0.bench_rows - 1) * cfg0.bench_pitch_y:.1f} m deep; "
          f"teacher verifies the front bench of the middle column.")
    print(f"Params: edge<={P.max_edge_m} m, k={P.k}, disjoint paths={P.independent}, ttl={P.ttl}, max path {P.max_path_m} m; {N} classes per row\n")

    with ProcessPoolExecutor(a.workers) as pool:
        # A. head-count sweep x door: fixed 2.0 m vs the server's density-adaptive threshold --------------
        print("A) Head-count sweep (random seating): fixed 2.0 m edge vs the server's adaptive edge")
        print(f"{'students':>8} {'door':>6} | {'FIXED 2.0 m':^21} | {'ADAPTIVE':^32} | {'hops p95/max':>12} {'path m max':>10}")
        print(f"{'':>8} {'':>6} | {'false-abs':>9} {'corr✓':>10} | {'edge':>5} {'false-abs':>9} {'corr✓':>8} {'leak cls':>7} |")
        A, AF = {}, {}
        for n in (93, 80, 65, 50, 35, 20):
            for door in (False, True):
                cfg = replace(BASE, students=n, door_open=door)
                fx = _agg(_run(pool, [("trial", cfg, P, s, 0) for s in range(N)]))
                pa = adaptive(n)
                ad = _agg(_run(pool, [("trial", cfg, pa, s, 0) for s in range(N)]))
                A[(n, door)], AF[(n, door)] = ad, fx
                print(f"{n:>8} {('open' if door else 'closed'):>6} | {fx['fa']:>9.1%} {fx['fp']:>10.1%} | {pa.max_edge_m:>5} {ad['fa']:>9.1%} "
                      f"{ad['fp']:>8.1%} {ad['leak_classes']:>7.0%} | {ad['hops_p95']:>5}/{ad['hops_max']:<5} {ad['path_max']:>10.1f}")
        # B. which front bench does the teacher verify? -----------------------------------------
        print("\nB) Which column's front bench is verified (door open, adaptive edge)")
        print(f"{'students':>8} {'seed column':>12} | {'false-abs':>9} {'corridor✓':>10}")
        B = {}
        for n in (93, 60):
            for col in (0, 1, 2):
                cfg = replace(BASE, students=n, seed_col=col)
                r = _agg(_run(pool, [("trial", cfg, adaptive(n), 500 + s, 0) for s in range(N)]))
                B[(n, col)] = r
                print(f"{n:>8} {['left', 'middle', 'right'][col]:>12} | {r['fa']:>9.1%} {r['fp']:>10.1%}")
        # C. is the default TTL / path bound enough for a room 7.7 m deep? ------------------------
        print("\nC) TTL and path-length bounds at 93 students (door closed): false-absent")
        print(f"{'ttl':>4} | " + " ".join(f"path<={m:>4}m" for m in (10, 15, 25)))
        C = {}
        for ttl in (4, 6, 8, 12):
            row = []
            for mp in (10.0, 15.0, 25.0):
                p = replace(P, ttl=ttl, max_path_m=mp)
                r = _agg(_run(pool, [("trial", replace(BASE, door_open=False), p, 900 + s, 0) for s in range(N)]))
                C[(ttl, mp)] = r["fa"]
                row.append(f"{r['fa']:>10.1%}")
            print(f"{ttl:>4} | " + " ".join(row))
        # D. students seated front-first, column by column ----------------------------------------
        print("\nD) Column-by-column seating, front first (door open, adaptive edge)")
        print(f"{'students':>8} | {'false-abs':>9} {'corridor✓':>10}")
        D = {}
        for n in (40, 60, 93):
            r = _agg(_run(pool, [("trial", replace(BASE, students=n, fill="column"), adaptive(n), 700 + s, 0) for s in range(N)]))
            D[n] = r
            print(f"{n:>8} | {r['fa']:>9.1%} {r['fp']:>10.1%}")
        # E. edge threshold in the densest room ---------------------------------------------------
        print("\nE) Edge-distance threshold (door open)")
        print(f"{'students':>8} {'edge m':>7} | {'false-abs':>9} {'corridor✓':>10}")
        E = {}
        for n in (93, 60):
            for em in (1.5, 2.0, 2.5):
                r = _agg(_run(pool, [("trial", replace(BASE, students=n), replace(P, max_edge_m=em), 1100 + s, 0) for s in range(N)]))
                E[(n, em)] = r
                print(f"{n:>8} {em:>7} | {r['fa']:>9.1%} {r['fp']:>10.1%}")
        # F. collusion at full class ---------------------------------------------------------------
        print("\nF) Collusion at 93 students: P(remote friend marked PRESENT) vs in-room accomplices")
        print(f"{'accomplices':>11} | " + " ".join(f"{'k=' + str(k):>6}" for k in (2, 3)))
        F = {}
        for acc in range(0, 5):
            row = []
            for k in (2, 3):
                hits = _run(pool, [("collude", BASE, replace(P, k=k), 1300 + s, acc) for s in range(max(10, N // 2))])
                F[(acc, k)] = sum(h["hit"] for h in hits) / len(hits)
                row.append(f"{F[(acc, k)]:>6.0%}")
            print(f"{acc:>11} | " + " ".join(row))

    # ---------------- acceptance criteria (written BEFORE the adaptive run; see README) ----------------
    full_c, full_o = A[(93, False)], A[(93, True)]
    dense = (93, 80, 65, 50, 35)
    worst = lambda d, keys: max(d[k]["fa"] for k in keys)   # noqa: E731
    checks += [
        ("93 students, door closed: false-absent <= 2%", full_c["fa"] <= 0.02, f"{full_c['fa']:.1%}"),
        ("93 students, door closed: no corridor phone admitted", full_c["fp"] == 0.0, f"{full_c['fp']:.1%}"),
        ("93 students, door open: corridor admission <= 15%", full_o["fp"] <= 0.15, f"{full_o['fp']:.1%}"),
        ("adaptive edge, 35..93 students, door closed: false-absent <= 3%",
         worst(A, [(n, False) for n in dense]) <= 0.03, f"worst {worst(A, [(n, False) for n in dense]):.1%}"),
        ("adaptive edge, 35..93 students, door open: corridor admission <= 15%",
         max(A[(n, True)]["fp"] for n in dense) <= 0.15, f"worst {max(A[(n, True)]['fp'] for n in dense):.1%}"),
        ("20 students (stated limitation): false-absent <= 15%", A[(20, False)]["fa"] <= 0.15, f"{A[(20, False)]['fa']:.1%}"),
        ("adaptive is never worse than fixed 2.0 m on false-absent (door closed)",
         all(A[(n, False)]["fa"] <= AF[(n, False)]["fa"] + 0.005 for n in (93, 80, 65, 50, 35, 20)), "all head-counts"),
        ("verified front bench, middle column: false-absent <= 2% at 93 and 60", max(B[(n, 1)]["fa"] for n in (93, 60)) <= 0.02,
         f"worst {max(B[(n, 1)]['fa'] for n in (93, 60)):.1%}"),
        ("verified front bench, ANY column: false-absent <= 5% at 93 and 60", max(v["fa"] for v in B.values()) <= 0.05,
         f"worst {max(v['fa'] for v in B.values()):.1%}"),
        ("default ttl=8 / path<=15 m is not the bottleneck at 93", C[(8, 15.0)] <= C[(12, 25.0)] + 0.005,
         f"{C[(8, 15.0)]:.2%} vs unbounded {C[(12, 25.0)]:.2%}"),
        ("column-by-column seating: false-absent <= 3%", max(v["fa"] for v in D.values()) <= 0.03, f"worst {max(v['fa'] for v in D.values()):.1%}"),
        ("collusion needs >= k accomplices (k=2: 1 fails, 2 works)", F[(1, 2)] == 0 and F[(2, 2)] == 1.0, f"1->{F[(1, 2)]:.0%}, 2->{F[(2, 2)]:.0%}"),
        ("raising server k to 3 stops 2 accomplices", F[(2, 3)] == 0.0, f"{F[(2, 3)]:.0%}"),
    ]
    print(f"\nAcceptance criteria ({time.time() - t0:.0f} s):")
    for name, ok, detail in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}  ({detail})")
    sys.exit(0 if all(ok for _, ok, _ in checks) else 1)


if __name__ == "__main__":
    main()
