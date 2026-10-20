"""The bridge from OMNeT++ to the REAL server engine: reads reports.csv written by the simulated server, runs
app.services.graph.evaluate exactly as the API does, writes verdict.csv for OMNeT++ to display.

    python -m netsim.omnet_eval --dir omnet/generated/scene
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from app.services.graph import Params, adaptive_edge_m, evaluate


def read_col(path: Path, col: str = "id") -> list[str]:
    with open(path, newline="", encoding="ascii") as f:
        return [r[col] for r in csv.DictReader(f)]


def run(d: Path, **kw) -> dict:
    checked = read_col(d / "checkins.csv")
    models = {r["id"]: r["platform"] for r in csv.DictReader(open(d / "models.csv", newline="", encoding="ascii"))}
    seeds = [s for s in read_col(d / "seeds.csv") if s in set(checked)]
    reports: dict[str, dict[str, float]] = {k: {} for k in read_col(d / "reporters.csv")}
    for r in csv.DictReader(open(d / "reports.csv", newline="", encoding="ascii")):
        reports.setdefault(r["reporter"], {})[r["peer"]] = float(r["rssi_median"])
    p = Params(max_edge_m=adaptive_edge_m(len(checked)), **kw)          # the server's density-adaptive edge threshold
    res = evaluate(seeds, reports, p, {k: models.get(k, "android") for k in checked})
    lines = [f"P,{k}," for k in sorted(res["present"])]
    lines += [f"E,{a},{b}" for a, b in sorted(tuple(sorted(e)) for e in res["edge_list"])]
    lines += [f"C,{k},{v['partner']}" for k, v in sorted(res.get("colocated", {}).items())]
    (d / "verdict.csv").write_text("\n".join(lines) + "\n", encoding="ascii")
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", required=True)
    ap.add_argument("--k", type=int, default=None)
    ap.add_argument("--colocation-db", type=float, default=None)
    a = ap.parse_args(argv)
    kw = {k: v for k, v in (("k", a.k), ("colocation_db", a.colocation_db)) if v is not None}
    res = run(Path(a.dir), **kw)
    print(f"engine: {len(res['present'])} present, {res['edges']} edges")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
