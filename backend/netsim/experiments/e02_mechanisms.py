"""E02 What each mechanism buys: switch one design element off at a time (mixed Android/iOS class, TX asymmetry 12 dB)."""
from __future__ import annotations

from dataclasses import replace

from netsim import attacks, metrics, plots
from netsim.experiments import common as C
from netsim.runner import cached_map
from netsim.server import trial

SIZES = (93, 35)
VARIANTS = ["full system", "no disjoint paths", "no self-calibration", "no adaptive edge", "no discovery tail", "k = 1", "k = 3",
            "no co-location check"]


def _variant(name: str, cfg, size: int):
    p = C.params_for(cfg)
    if name == "no disjoint paths": p = replace(p, independent=False)
    elif name == "no self-calibration": p = replace(p, autocal=False)
    elif name == "no adaptive edge": p = replace(p, max_edge_m=2.0)
    elif name == "no discovery tail": cfg = replace(cfg, tail_s=0.0)
    elif name == "k = 1": p = replace(p, k=1)
    elif name == "k = 3": p = replace(p, k=3)
    elif name == "no co-location check": p = replace(p, colocation_db=0.0)
    return cfg, p


def job(j):
    cfg, p, seed = j
    return {"t": trial(cfg, p, seed), "r": attacks.relay_trial(cfg, p, seed, 3)}


def run(ctx):
    n = ctx.n(EXPERIMENT)
    out, check = [], {}
    for size in SIZES:
        base = replace(C.cfg_for("class93", students=size, ios_share=0.5), door_open=True)
        base = replace(base, models={**base.models, "iphone": {**base.models["iphone"], "tx": 12.0}})
        full = None
        for name in VARIANTS:
            cfg, p = _variant(name, base, size)
            rs = cached_map(f"e02/{size}/{name}", job, [(cfg, p, s) for s in range(n)], ctx.cache, ctx.workers)
            far_n, far_d = [r["t"]["false_absent"] for r in rs], [r["t"]["inside"] for r in rs]
            fpr_n, fpr_d = [r["t"]["false_present"] for r in rs], [r["t"]["outside"] for r in rs]
            rel_n, rel_d = [r["r"]["relay_admitted"] for r in rs], [r["r"]["relays"] for r in rs]
            row = {"students": size, "variant": name, "far": metrics.ratio_ci(far_n, far_d, seed=1),
                   "fpr": metrics.ratio_ci(fpr_n, fpr_d, seed=2), "relay": metrics.ratio_ci(rel_n, rel_d, seed=3)}
            if name == "full system":
                full = (far_n, far_d, fpr_n, fpr_d, rel_n, rel_d)
            else:
                row["d_far"] = metrics.paired_diff_ci(far_n, far_d, full[0], full[1], seed=4)
                row["d_fpr"] = metrics.paired_diff_ci(fpr_n, fpr_d, full[2], full[3], seed=5)
                row["d_relay"] = metrics.paired_diff_ci(rel_n, rel_d, full[4], full[5], seed=6)
            out.append(row)
            check[f"{size}/{name}"] = [sum(far_n), sum(fpr_n), sum(rel_n)]
    return {"rows": out, "check": check}


def plot(res, figdir):
    if not plots.available():
        return []
    P = plots.plt()
    fig, axes = P.subplots(1, 3, figsize=(7.2, 2.8), sharey=True)
    sel = [r for r in res["rows"] if r["students"] == 93]
    for ax, key, title in zip(axes, ("far", "fpr", "relay"), ("students marked absent", "corridor admitted", "relay friend admitted")):
        y = list(range(len(sel)))
        ax.errorbar([100 * r[key]["est"] for r in sel], y, xerr=[[100 * (r[key]["est"] - r[key]["lo"]) for r in sel],
                    [100 * (r[key]["hi"] - r[key]["est"]) for r in sel]], fmt="o", capsize=2, markersize=4)
        ax.set_title(title); ax.set_xlabel("%"); ax.set_xlim(left=0)
    axes[0].set_yticks(range(len(sel))); axes[0].set_yticklabels([r["variant"] for r in sel]); axes[0].invert_yaxis()
    return plots.save(fig, figdir, "e02_mechanisms")


def table(res):
    h = ["students", "variant", "false-absent", "corridor admitted", "relay admitted", "vs full (FAR)"]
    def d(r):
        x = r.get("d_far")
        return "-" if x is None else f"{100 * x['est']:+.2f} pp{' *' if x['significant'] else ''}"
    rows = [[r["students"], r["variant"], C.pct(r["far"]), C.pct(r["fpr"]), C.pct(r["relay"]), d(r)] for r in res["rows"]]
    return C.md_table(h, rows) + "\n\n`*` = paired 95% CI excludes 0.", C.latex_table(h, rows, "Effect of removing one mechanism (50% iOS, +12 dB iOS TX).", "tab:e02")


EXPERIMENT = {"id": "E02", "title": "What each mechanism buys", "question": "What does each design element contribute to accuracy and security?",
              "trials_quick": 6, "trials_full": 60, "run": run, "plot": plot, "table": table}
