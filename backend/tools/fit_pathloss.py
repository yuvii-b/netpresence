"""Fit RSSI = A - 10 n log10(d) from the BLE lab-app CSV export (plan phase 0.3).

CSV columns: model,distance_m,rssi            (one row per RSSI sample; optional: condition)
Usage: python -m tools.fit_pathloss samples.csv [--ref-model "Pixel 6"]

Prints per-model A, n, shadowing sigma, a 3 m vs 6 m confusion estimate at the chosen threshold,
and the per-model RSSI offset to enter via PUT /api/devices/calibration.
"""
import argparse
import csv
import math
import statistics
from collections import defaultdict


def fit(points):
    xs = [-10 * math.log10(d) for d, _ in points]
    ys = [r for _, r in points]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    n = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    A = my - n * mx
    resid = [y - (A + n * x) for x, y in zip(xs, ys)]
    return A, n, statistics.pstdev(resid)


def phi(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--ref-model")
    ap.add_argument("--near", type=float, default=3.0)
    ap.add_argument("--far", type=float, default=6.0)
    a = ap.parse_args()
    by = defaultdict(list)
    with open(a.csv) as f:
        for r in csv.DictReader(f):
            by[r["model"]].append((float(r["distance_m"]), float(r["rssi"])))
    fits = {m: fit(pts) for m, pts in by.items() if len({d for d, _ in pts}) >= 3}
    ref = a.ref_model or max(fits, key=lambda m: len(by[m]))
    A_ref = fits[ref][0]
    print(f"reference model: {ref}\n")
    print(f"{'model':<18}{'A (dBm@1m)':>11}{'n':>7}{'sigma dB':>10}{'offset dB':>11}{'P(mistake 3m vs 6m)':>22}")
    for m, (A, n, s) in sorted(fits.items()):
        # midpoint decision threshold between the mean RSSI at near and far; error = tail of each class
        mu_n, mu_f = A - 10 * n * math.log10(a.near), A - 10 * n * math.log10(a.far)
        err = phi(-abs(mu_n - mu_f) / 2 / s) if s > 0 else 0.0
        print(f"{m:<18}{A:>11.1f}{n:>7.2f}{s:>10.2f}{A_ref - A:>11.1f}{err:>22.1%}")
    print("\nsigma includes shadowing; use n and sigma in sim.room.RoomConfig and the offset column in the calibration table.")


if __name__ == "__main__":
    main()
