"""E09 Baselines: manual roll call, teacher beacon, acoustic (v1), rotating QR, ablations and NetPresence, same classrooms."""
from __future__ import annotations

from dataclasses import replace

from netsim import baselines, metrics, plots
from netsim.experiments import common as C
from netsim.runner import cached_map


def job(j):
    name, cfg, seed = j
    return baselines.BASELINES[name](cfg, seed)


def run(ctx):
    n = ctx.n(EXPERIMENT)
    rows, check = [], {}
    for door in (False, True):
        cfg = replace(C.cfg_for("class93", ios_share=0.30), door_open=door)
        for name in baselines.BASELINES:
            rs = cached_map(f"e09/{door}/{name}", job, [(name, cfg, s) for s in range(n)], ctx.cache, ctx.workers)
            rows.append({"door": "open" if door else "closed", "method": name,
                         "far": metrics.ratio_ci([r["false_absent"] for r in rs], [r["inside"] for r in rs], seed=1),
                         "fpr": metrics.ratio_ci([r["false_present"] for r in rs], [r["outside"] for r in rs], seed=2),
                         "proxy": metrics.ratio_ci([r["proxy_success"] for r in rs], [r["proxy_attempts"] for r in rs], seed=3),
                         "time_s": metrics.mean_ci([r["time_s"] for r in rs], seed=4)})
            check[f"{door}/{name}"] = [sum(r["false_absent"] for r in rs), sum(r["false_present"] for r in rs), sum(r["proxy_success"] for r in rs)]
    return {"rows": rows, "check": check}


def plot(res, figdir):
    if not plots.available():
        return []
    P = plots.plt()
    sel = [r for r in res["rows"] if r["door"] == "open"]
    fig, ax = P.subplots(1, 4, figsize=(8.4, 2.9), sharey=True)
    for a, key, title in zip(ax, ("far", "fpr", "proxy", "time_s"), ("marked absent (%)", "corridor admitted (%)", "proxy succeeds (%)", "time (s)")):
        y = list(range(len(sel)))
        k = 100 if key != "time_s" else 1
        a.errorbar([k * r[key]["est"] for r in sel], y, xerr=[[k * (r[key]["est"] - r[key]["lo"]) for r in sel], [k * (r[key]["hi"] - r[key]["est"]) for r in sel]],
                   fmt="o", capsize=2, markersize=4)
        a.set_title(title, fontsize=8); a.set_xlim(left=0)
    ax[0].set_yticks(range(len(sel))); ax[0].set_yticklabels([r["method"] for r in sel], fontsize=7); ax[0].invert_yaxis()
    return plots.save(fig, figdir, "e09_baselines")


def table(res):
    h = ["door", "method", "false-absent", "corridor admitted", "proxy succeeds", "time (s)"]
    rows = [[r["door"], r["method"], C.pct(r["far"]), C.pct(r["fpr"]), C.pct(r["proxy"]), f"{r['time_s']['est']:.0f}"] for r in res["rows"]]
    return C.md_table(h, rows) + "\n\nAll baseline parameters are `assumed` (see netsim/baselines.py); 30% iPhones.", \
        C.latex_table(h, rows, "NetPresence against alternatives (93 students, 30% iPhones).", "tab:e09")


EXPERIMENT = {"id": "E09", "title": "Baselines", "question": "How does NetPresence compare with the alternatives a teacher could use today?",
              "trials_quick": 4, "trials_full": 60, "run": run, "plot": plot, "table": table}
