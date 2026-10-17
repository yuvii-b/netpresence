"""Android + iOS fleet study: does the system hold up when the class is any mix of phones?

Same 93-seat room as sim.orientation (3 bench columns x 8 benches x 4 seats). Every result is a mean over `--trials`
random seatings. Pre-declared pass/fail criteria; exits non-zero if any fails.

    python -m sim.platforms [--trials 60] [--workers 2]

  A. iOS share 0% / 15% / 50% / 100% at 93 students (door closed: false-absent; door open: corridor admission)
  B. TX-power asymmetry between platforms (iOS cannot set TX power) with and without the server's self-calibration
  C. Check-in window x head-count (students tap over several seconds; discovery runs 5 s past check-in): how short
     can the roll call be?
  D. Pessimistic iOS radio (heavily coalesced scan reports, slow advertising)
"""
from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace

from app.services.graph import Params, adaptive_edge_m
from sim.room import RoomConfig, trial

BASE = RoomConfig(students=93)


def _one(args):
    cfg, p, seed = args
    return trial(cfg, p, seed)


def _rate(pool, cfg, p, n, seed0):
    rs = list(pool.map(_one, [(cfg, p, seed0 + s) for s in range(n)], chunksize=4))
    ins = sum(r["inside"] for r in rs) or 1
    outs = sum(r["outside"] for r in rs) or 1
    return 100 * sum(r["false_absent"] for r in rs) / ins, 100 * sum(r["false_present"] for r in rs) / outs


def ios(cfg: RoomConfig, **kw) -> RoomConfig:
    """Same room, iPhone profile changed."""
    m = {k: dict(v) for k, v in cfg.models.items()}
    m["iphone"].update(kw)
    return replace(cfg, models=m)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=60)
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()
    N, t0 = a.trials, time.time()
    checks: list[tuple[str, bool, str]] = []
    P = lambda n: Params(max_edge_m=adaptive_edge_m(n))   # what the server uses (density-adaptive edge)

    with ProcessPoolExecutor(a.workers) as pool:
        print(f"A) iOS share, 93 students, {BASE.window_s:.0f} s check-in + {BASE.tail_s:.0f} s tail ({N} trials each)")
        print(f"   {'iOS share':>9} | {'false-absent (door closed)':>27} | {'corridor admitted (door open)':>30}")
        share = {}
        for sh in (0.0, 0.15, 0.5, 1.0):
            fa, _ = _rate(pool, replace(BASE, ios_share=sh, door_open=False), P(93), N, 100)
            _, leak = _rate(pool, replace(BASE, ios_share=sh), P(93), N, 200)
            share[sh] = (fa, leak)
            print(f"   {sh:>9.0%} | {fa:>26.2f}% | {leak:>29.2f}%")
        checks += [
            ("any iOS share 0-100%: false-absent <= 2% at 93 (door closed)", max(v[0] for v in share.values()) <= 2,
             f"worst {max(v[0] for v in share.values()):.2f}%"),
            ("any iOS share 0-100%: corridor admission <= 15% (door open)", max(v[1] for v in share.values()) <= 15,
             f"worst {max(v[1] for v in share.values()):.2f}%"),
        ]

        print("\nB) TX-power asymmetry: iPhones transmit X dB hotter than Android, 50% iOS, 93 students, door closed")
        print(f"   {'X dB':>5} | {'self-cal OFF':>12} | {'self-cal ON':>11}")
        asym = {}
        for x in (0, 6, 12):
            cfg = replace(ios(BASE, tx=float(x)), ios_share=0.5, door_open=False)
            off, _ = _rate(pool, cfg, replace(P(93), autocal=False), N, 300)
            on, _ = _rate(pool, cfg, P(93), N, 300)
            asym[x] = (off, on)
            print(f"   {x:>5} | {off:>11.2f}% | {on:>10.2f}%")
        checks += [
            ("self-calibration keeps false-absent <= 3% up to 12 dB TX asymmetry", max(v[1] for v in asym.values()) <= 3,
             f"worst {max(v[1] for v in asym.values()):.2f}%"),
            ("self-calibration is never worse than none (within 0.5 pp)", all(v[1] <= v[0] + 0.5 for v in asym.values()),
             ", ".join(f"{x}dB {v[0]:.1f}->{v[1]:.1f}" for x, v in asym.items())),
        ]

        print(f"\nC) Check-in window x head-count, 15% iOS, door closed, tap delay median {BASE.tap_median_s:.0f} s: false-absent %")
        windows = (10, 15, 20, 30, 45)
        heads = (35, 60, 93)
        print(f"   {'students':>8} | " + " ".join(f"{w:>5}s" for w in windows))
        table = {}
        for n in heads:
            row = []
            for w in windows:
                fa, _ = _rate(pool, replace(BASE, students=n, window_s=float(w), door_open=False), P(n), N, 400 + n)
                table[(n, w)] = fa
                row.append(fa)
            print(f"   {n:>8} | " + " ".join(f"{v:>5.2f}%" for v in row))
        dflt = int(BASE.window_s)
        worst_gap = max(table[(n, dflt)] - table[(n, 45)] for n in heads)
        checks.append((f"default {dflt} s check-in within 1 pp of a 45 s check-in at every head-count", worst_gap <= 1.0,
                       f"worst gap {worst_gap:+.2f} pp"))

        print("\nD) Pessimistic iPhones: scan reports coalesced (eff 0.3), advertising every 300 ms, 50% iOS, 93 students")
        fa, _ = _rate(pool, replace(ios(BASE, scan_eff=0.3, adv_ms=300.0), ios_share=0.5, door_open=False), P(93), N, 600)
        print(f"   false-absent {fa:.2f}%")
        checks.append(("pessimistic iPhones: false-absent <= 5% at 93", fa <= 5, f"{fa:.2f}%"))

    print(f"\nAcceptance ({time.time() - t0:.0f} s):")
    ok = True
    for name, passed, detail in checks:
        ok &= passed
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}  ({detail})")
    print("\nAssumptions to replace with BLE-lab measurements: iOS TX power and advertising interval, iOS duplicate-report "
          "rate, per-model receiver gain, path-loss exponent and shadowing sigma.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
