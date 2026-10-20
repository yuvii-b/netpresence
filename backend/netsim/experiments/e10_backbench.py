"""E10 Who gets missed: per-seat false-absent heatmaps (bench column x bench row) for acoustic v1, teacher beacon and NetPresence."""
from __future__ import annotations

from dataclasses import replace

from netsim import baselines, plots
from netsim.experiments import common as C
from netsim.runner import cached_map

METHODS = ("B2 acoustic (v1)", "B1 teacher beacon", "NetPresence")


def job(j):
    name, cfg, seed = j
    return {"seats": baselines.BASELINES[name](cfg, seed)["seats"]}


def run(ctx):
    n = ctx.n(EXPERIMENT)
    cfg = replace(C.cfg_for("class93", ios_share=0.30), door_open=False)
    out, check = {}, {}
    for m in METHODS:
        rs = cached_map(f"e10/{m}", job, [(m, cfg, s) for s in range(n)], ctx.cache, ctx.workers)
        cell = {}
        for r in rs:
            for bc, br, absent in r["seats"]:
                a, t = cell.get(f"{bc},{br}", (0, 0))
                cell[f"{bc},{br}"] = (a + int(absent), t + 1)
        out[m] = {k: {"absent": a, "total": t} for k, (a, t) in sorted(cell.items())}
        check[m] = sum(v["absent"] for v in out[m].values())
    return {"cols": cfg.bench_cols, "rows": cfg.bench_rows, "methods": out, "check": check}


def _grid(res, m):
    import numpy as np
    G = np.full((res["rows"], res["cols"]), np.nan)
    for k, v in res["methods"][m].items():
        bc, br = (int(x) for x in k.split(","))
        if v["total"]:
            G[br, bc] = 100.0 * v["absent"] / v["total"]
    return G


def plot(res, figdir):
    if not plots.available():
        return []
    P = plots.plt()
    fig, axes = P.subplots(1, len(METHODS), figsize=(7.4, 3.2), sharey=True)
    for ax, m in zip(axes, METHODS):
        G = _grid(res, m)
        im = ax.imshow(G, vmin=0, vmax=100, cmap="magma_r", aspect="auto")
        ax.set_title(m, fontsize=8); ax.set_xticks(range(res["cols"])); ax.set_xlabel("bench column"); ax.grid(False)
    axes[0].set_ylabel("bench row (0 = front, teacher)"); fig.colorbar(im, ax=axes, label="marked absent (%)")
    return plots.save(fig, figdir, "e10_backbench")


def table(res):
    h = ["method", "front half absent %", "back half absent %"]
    rows = []
    for m in METHODS:
        half = res["rows"] // 2
        f = [v for k, v in res["methods"][m].items() if int(k.split(",")[1]) < half]
        b = [v for k, v in res["methods"][m].items() if int(k.split(",")[1]) >= half]
        rate = lambda xs: "-" if not sum(x["total"] for x in xs) else f"{100 * sum(x['absent'] for x in xs) / sum(x['total'] for x in xs):.1f}"
        rows.append([m, rate(f), rate(b)])
    return C.md_table(h, rows), C.latex_table(h, rows, "Where the missed students sit (93 students, 30% iPhones).", "tab:e10")


EXPERIMENT = {"id": "E10", "title": "Who gets missed", "question": "Do the back benches get missed, and does the multi-hop flood fix that?",
              "trials_quick": 4, "trials_full": 60, "run": run, "plot": plot, "table": table}
