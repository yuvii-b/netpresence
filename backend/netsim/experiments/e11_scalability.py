"""E11 Scalability: accuracy and compute time from 50 to 500 students (larger lecture halls; same bench geometry, more rows)."""
from __future__ import annotations

import math
import time
from dataclasses import replace

from netsim import plots
from netsim.experiments import common as C
from netsim.server import trial

SIZES_QUICK = (50, 100, 200)
SIZES_FULL = (50, 100, 200, 300, 500)


def _cfg(size):
    rows = math.ceil(size / 12)
    return replace(C.cfg_for("class93", ios_share=0.15), door_open=False, capacity=size, students=size, bench_rows=rows)


def run(ctx):
    n = ctx.n(EXPERIMENT)
    rows, check, secs = [], {}, {}
    for size in (SIZES_QUICK if ctx.quick else SIZES_FULL):
        cfg = _cfg(size)
        p = C.params_for(cfg)
        rs = C.trial_rows(ctx, f"e11/{size}", cfg, p, n)
        t0 = time.time(); trial(cfg, p, 10_000 + size); secs[str(size)] = round(time.time() - t0, 2)   # wall time: not hashed
        c = C.counts(rs)
        big = C.trial_rows(ctx, f"e11/{size}/ttl12", cfg, replace(p, ttl=12, max_path_m=25.0), n)
        rows.append({"students": size, "bench_rows": cfg.bench_rows, **C.rates(rs), "far_ttl12": C.rates(big)["far"],
                     "hops_max": max(r["max_hops"] for r in rs), "path_m_max": max(r["max_path_m"] for r in rs)})
        check[str(size)] = [c["false_absent"], max(r["max_hops"] for r in rs), C.counts(big)["false_absent"]]
    return {"rows": rows, "check": check, "timing": {"seconds_per_trial": secs}}


def plot(res, figdir):
    if not plots.available():
        return []
    P = plots.plt()
    fig, ax = P.subplots(1, 2, figsize=(6.4, 2.6))
    plots.errorbar(ax[0], [r["students"] for r in res["rows"]], [r["far"] for r in res["rows"]], label="false-absent", marker=0)
    ax[0].set_xlabel("students"); ax[0].set_ylabel("marked absent (%)"); ax[0].set_ylim(bottom=0)
    ax[1].plot([r["students"] for r in res["rows"]], [r["hops_max"] for r in res["rows"]], "o-")
    ax[1].set_xlabel("students"); ax[1].set_ylabel("deepest admitted student (hops)"); ax[1].axhline(8, ls="--", color="gray", lw=0.8)
    return plots.save(fig, figdir, "e11_scalability")


def table(res):
    h = ["students", "bench rows", "false-absent (ttl 8, 15 m)", "false-absent (ttl 12, 25 m)", "max hops", "max path (m)"]
    rows = [[r["students"], r["bench_rows"], C.pct(r["far"]), C.pct(r["far_ttl12"]), r["hops_max"], f"{r['path_m_max']:.1f}"] for r in res["rows"]]
    return C.md_table(h, rows) + "\n\nDefault TTL is 8 hops / 15 m (dashed line).", C.latex_table(h, rows, "Larger rooms.", "tab:e11")


EXPERIMENT = {"id": "E11", "title": "Scalability", "question": "Does the system still work in a 200- or 500-seat hall, and what does it cost to compute?",
              "trials_quick": 2, "trials_full": 12, "run": run, "plot": plot, "table": table}
