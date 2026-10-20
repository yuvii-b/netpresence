"""E08 Robustness: one-at-a-time sweep (tornado) over every `assumed` radio/phone parameter; which assumption matters most?"""
from __future__ import annotations

from dataclasses import replace

from netsim import plots
from netsim.experiments import common as C

# field -> (low, high) around the default; chosen as the plausible range of a real classroom [assumed]
RANGE = {"n": (2.4, 3.6), "shadow_sigma": (3.0, 8.0), "fast_sigma": (2.0, 6.0), "dir_sigma": (0.0, 3.0), "body_db": (1.0, 5.0),
         "wall_db": (6.0, 18.0), "p_detect": (0.9, 1.0), "tap_median_s": (2.0, 8.0), "seat_pitch": (0.4, 0.7), "A": (-65.0, -53.0)}


def run(ctx):
    n = ctx.n(EXPERIMENT)
    base = replace(C.cfg_for("class93", ios_share=0.15), door_open=True)
    rows, check = [], {}
    b = C.rates(C.trial_rows(ctx, "e08/base", base, C.params_for(base), n))
    base_c = C.counts(C.trial_rows(ctx, "e08/base", base, C.params_for(base), n))
    check["base"] = [base_c["false_absent"], base_c["false_present"]]
    for f, (lo, hi) in RANGE.items():
        for tag, v in (("low", lo), ("high", hi)):
            cfg = replace(base, **{f: v})
            rs = C.trial_rows(ctx, f"e08/{f}/{tag}", cfg, C.params_for(cfg), n)
            c = C.counts(rs)
            rows.append({"field": f, "side": tag, "value": v, **C.rates(rs)})
            check[f"{f}/{tag}"] = [c["false_absent"], c["false_present"]]
    return {"base": b, "rows": rows, "check": check}


def plot(res, figdir):
    if not plots.available():
        return []
    P = plots.plt()
    fields = sorted({r["field"] for r in res["rows"]},
                    key=lambda f: -max(abs(r["far"]["est"] - res["base"]["far"]["est"]) + abs(r["fpr"]["est"] - res["base"]["fpr"]["est"])
                                       for r in res["rows"] if r["field"] == f))
    fig, ax = P.subplots(1, 2, figsize=(7.0, 3.0), sharey=True)
    for a, key, title in zip(ax, ("far", "fpr"), ("students marked absent", "corridor admitted")):
        b = 100 * res["base"][key]["est"]
        for i, f in enumerate(fields):
            for r in (x for x in res["rows"] if x["field"] == f):
                a.barh(i, 100 * r[key]["est"] - b, left=b, height=0.6, color=plots.OKABE_ITO[0 if r["side"] == "low" else 1], alpha=0.8)
        a.axvline(b, color="k", lw=0.8); a.set_title(title); a.set_xlabel("%")
    ax[0].set_yticks(range(len(fields))); ax[0].set_yticklabels(fields); ax[0].invert_yaxis()
    return plots.save(fig, figdir, "e08_robustness")


def table(res):
    h = ["parameter", "side", "value", "false-absent", "corridor admitted"]
    rows = [["baseline", "-", "-", C.pct(res["base"]["far"]), C.pct(res["base"]["fpr"])]]
    rows += [[r["field"], r["side"], r["value"], C.pct(r["far"]), C.pct(r["fpr"])] for r in res["rows"]]
    return C.md_table(h, rows), C.latex_table(h, rows, "One-at-a-time sensitivity to assumed parameters (93 students, door open).", "tab:e08")


EXPERIMENT = {"id": "E08", "title": "Robustness to assumptions", "question": "Which assumed value would hurt most if reality differs?",
              "trials_quick": 3, "trials_full": 40, "run": run, "plot": plot, "table": table}
