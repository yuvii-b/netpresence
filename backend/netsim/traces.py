"""Trace-driven channel: empirical RSSI tables from BLE-lab measurements (CSV v2).

CSV v2 columns (written by the app's BLE lab screen): t_ms,model,platform,peer_eph,distance_m,orientation,bodies,wall,rssi
(one row per RSSI sample). A "pair measurement" is the median of the samples of one (model, peer, distance, orientation,
bodies, wall) group, i.e. what a phone would report for that link. The table holds those medians per condition
(bodies 0-3, wall 0/1) and measured distance. The channel draws one measured link per unordered pair from the nearest measured
distance (within half an octave, shifted by the path-loss difference); conditions or distances with fewer than MIN_CELL
measurements fall back to the parametric model and are COUNTED (reported in result JSON as
`trace_fallbacks`) so the paper can say how much of a run was really measured.

Rows come from a reference-model pair, so the draws are "reference RSSI"; per-phone rx/tx gains are added afterwards by the
link layer exactly as for the parametric channel.

    python -m netsim.traces --synthesize out.csv     # write a synthetic lab file from the parametric model (template/tests)
    python -m netsim.traces lab.csv                  # coverage and fitted A, n, sigma
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import numpy as np

MAX_M = 8.0
MIN_CELL = 3
COLUMNS = ("t_ms", "model", "platform", "peer_eph", "distance_m", "orientation", "bodies", "wall", "rssi")


def _files(path: str | Path) -> list[Path]:
    p = Path(path)
    if p.is_dir():
        return sorted(p.glob("*.csv"))
    if not p.is_file():
        raise FileNotFoundError(f"trace file not found: {p}")
    return [p]


def read_rows(path: str | Path) -> list[dict]:
    rows = []
    for f in _files(path):
        with open(f, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                missing = [c for c in ("model", "distance_m", "rssi") if c not in r]
                if missing:
                    raise ValueError(f"{f.name}: missing columns {missing} (expected CSV v2: {','.join(COLUMNS)})")
                rows.append({"file": f.name, "model": r["model"], "peer": r.get("peer_eph", ""),
                             "d": float(r["distance_m"]), "orient": r.get("orientation") or "desk",
                             "bodies": int(r.get("bodies") or 0), "wall": int(r.get("wall") or 0),
                             "rssi": float(r["rssi"])})
    return rows


def pair_medians(rows: list[dict], orientation: str | None = None) -> list[tuple[float, int, int, float]]:
    """(distance, bodies, wall, median rssi) for every measured link."""
    groups = defaultdict(list)
    for r in rows:
        if orientation is None or r["orient"] == orientation:
            groups[(r["file"], r["model"], r["peer"], r["d"], r["orient"], r["bodies"], r["wall"])].append(r["rssi"])
    return [(k[3], k[5], k[6], statistics.median(v)) for k, v in sorted(groups.items())]


class Table:
    """Pair measurements per (bodies, wall) condition and measured distance.

    A pair at distance d is served by the measured distance closest to it (within a factor of 1.41 = half an octave),
    drawing one measured link at random and shifting it by the path-loss difference -10 n log10(d / d_measured)."""
    REACH = 2 ** 0.5

    def __init__(self, links: list[tuple[float, int, int, float]]):
        raw: dict[tuple[int, int], dict[float, list[float]]] = defaultdict(lambda: defaultdict(list))
        for d, b, w, m in links:
            if 0 < d <= MAX_M:
                raw[(min(b, 3), 1 if w else 0)][round(d, 2)].append(m)
        self.cells = {}
        for k, by_d in raw.items():
            ds = sorted(d for d, v in by_d.items() if len(v) >= MIN_CELL)
            if ds:
                self.cells[k] = (np.array(ds), [np.sort(np.array(by_d[d])) for d in ds])
        self.n_links = len(links)

    def draw(self, d: np.ndarray, bodies: np.ndarray, wall: np.ndarray, g: np.random.Generator, n: float):
        """(values, found): empirical draw per pair; `found` False where no measurement is close enough."""
        u = g.random(d.shape)
        out = np.zeros(d.shape)
        found = np.zeros(d.shape, dtype=bool)
        b = np.minimum(bodies, 3)
        w = wall.astype(int)
        for (cb, cw), (ds, arrs) in sorted(self.cells.items()):
            sel = np.flatnonzero((b == cb) & (w == cw) & (d <= MAX_M))
            if not sel.size:
                continue
            ratio = np.abs(np.log(d[sel][:, None] / ds[None, :]))
            near = ratio.argmin(1)
            ok = ratio[np.arange(sel.size), near] <= np.log(self.REACH)
            for j in np.unique(near[ok]):
                m = sel[ok & (near == j)]
                arr = arrs[j]
                out[m] = arr[np.minimum((u[m] * len(arr)).astype(int), len(arr) - 1)] - 10 * n * np.log10(d[m] / ds[j])
            found[sel[ok]] = True
        return out, found


@lru_cache(maxsize=8)
def _table(path: str, orientation: str, mtimes: tuple) -> Table:
    return Table(pair_medians(read_rows(path), orientation))


def table_for(path: str, orientation: str) -> Table:
    return _table(str(path), orientation, tuple(f.stat().st_mtime_ns for f in _files(path)))


def draw_pair_means(cfg, d, bodies, walled, g: np.random.Generator):
    """Channel hook: per-pair mean RSSI from the trace tables; parametric fallback where the data is thin."""
    if not cfg.trace_file:
        raise ValueError("channel = 'trace' needs trace_file (a BLE-lab CSV v2 file or a directory of them)")
    tab = table_for(cfg.trace_file, cfg.trace_orientation)
    emp, found = tab.draw(d, bodies, walled, g, cfg.n)
    para = (cfg.A - 10 * cfg.n * np.log10(d) - cfg.body_db * np.minimum(bodies, cfg.body_cap)
            - np.where(walled, cfg.wall_db, 0.0) + g.normal(0, cfg.shadow_sigma, d.shape))
    near = d <= cfg.body_max_m                      # farther pairs are too weak to matter; don't count them as fallbacks
    return np.where(found, emp, para), int(np.count_nonzero(near & ~found))


def coverage(rows: list[dict], orientation: str | None = None) -> dict:
    t = Table(pair_medians(rows, orientation))
    return {"links": t.n_links, "cells_usable": len(t.cells), "orientations": sorted({r["orient"] for r in rows}),
            "models": sorted({r["model"] for r in rows}), "distances_m": sorted({r["d"] for r in rows})}


def fit(rows: list[dict], orientation: str | None = None) -> dict:
    """Fitted A, n and sigma from clear line-of-sight links (no bodies, no wall)."""
    from tools.fit_pathloss import fit as fit_pl
    pts = [(d, m) for d, b, w, m in pair_medians(rows, orientation) if b == 0 and not w]
    if len({d for d, _ in pts}) < 3:
        raise ValueError("need clear-line-of-sight links at >= 3 distances to fit A, n, sigma")
    A, n, s = fit_pl(pts)
    return {"A": A, "n": n, "sigma": s}


def synthesize(cfg, path: str | Path, seed: int = 0, per_group: int = 40, groups_per_cell: int = 6) -> int:
    """Write a CSV v2 file drawn from the parametric model (all `assumed`): a template for the measurement campaign and a
    stand-in for real data in tests. Returns the number of rows."""
    g = np.random.default_rng(seed)
    rows = []
    for d in (0.5, 1, 1.5, 2, 3, 4, 6, 8):
        for bodies in range(4):
            for wall in (0, 1):
                for k in range(groups_per_cell):
                    mean = (cfg.A - 10 * cfg.n * np.log10(max(d, 0.3)) - cfg.body_db * min(bodies, cfg.body_cap)
                            - (cfg.wall_db if wall else 0.0) + g.normal(0, cfg.shadow_sigma))
                    for i in range(per_group):
                        rows.append((i * 100, "ref", "android", f"{k:08x}", d, "desk", bodies, wall,
                                     int(round(mean + g.normal(0, cfg.fast_sigma)))))
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(COLUMNS)
        w.writerows(rows)
    return len(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="?")
    ap.add_argument("--synthesize", metavar="OUT")
    ap.add_argument("--orientation")
    a = ap.parse_args(argv)
    if a.synthesize:
        from netsim.config import RoomConfig
        print(f"wrote {synthesize(RoomConfig(), a.synthesize)} rows to {a.synthesize}")
        return 0
    if not a.csv:
        ap.error("give a CSV file/directory or --synthesize OUT")
    rows = read_rows(a.csv)
    print(coverage(rows, a.orientation))
    try:
        f = fit(rows, a.orientation)
        print(f"fit: A {f['A']:.1f} dBm @ 1 m, n {f['n']:.2f}, sigma {f['sigma']:.1f} dB")
    except ValueError as e:
        print(e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
