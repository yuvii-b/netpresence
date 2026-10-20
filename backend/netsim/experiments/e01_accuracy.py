"""E01 Accuracy at classroom scale: false-absent and corridor admission vs head-count, door open and closed."""
from __future__ import annotations

from dataclasses import replace

from netsim import plots
from netsim.experiments import common as C

SIZES = (20, 35, 50, 60, 75, 93)


def run(ctx):
    n = ctx.n(EXPERIMENT)
    rows, check = [], {}
    for size in SIZES:
        for door in (True, False):
            cfg = replace(C.cfg_for(f"class93", students=size), door_open=door, ios_share=0.15)
            rs = C.trial_rows(ctx, f"e01/{size}/{door}", cfg, C.params_for(cfg), n)
            rows.append({"students": size, "door": "open" if door else "closed", **C.rates(rs)})
            check[f"{size}/{door}"] = C.counts(rs)
    return {"rows": rows, "check": check}


def plot(res, figdir):
    if not plots.available():
        return []
    P = plots.plt()
    fig, ax = P.subplots(1, 2, figsize=(6.6, 2.6))
    for k, door in enumerate(("closed", "open")):
        sel = [r for r in res["rows"] if r["door"] == door]
        plots.errorbar(ax[0], [r["students"] for r in sel], [r["far"] for r in sel], label=f"door {door}", marker=k)
        plots.errorbar(ax[1], [r["students"] for r in sel], [r["fpr"] for r in sel], label=f"door {door}", marker=k)
    ax[0].set_ylabel("students marked absent (%)"); ax[1].set_ylabel("corridor phones admitted (%)")
    for a in ax:
        a.set_xlabel("students in the room"); a.set_ylim(bottom=0)
    ax[0].legend()
    return plots.save(fig, figdir, "e01_accuracy")


def table(res):
    h = ["students", "door", "false-absent", "corridor admitted", "classrooms"]
    rows = [[r["students"], r["door"], C.pct(r["far"]), C.pct(r["fpr"]), r["classrooms"]] for r in res["rows"]]
    return C.md_table(h, rows), C.latex_table(h, rows, "Accuracy vs head-count (mean and 95% CI over classrooms).", "tab:e01")


EXPERIMENT = {"id": "E01", "title": "Accuracy at classroom scale", "question": "How accurate is the roll call from 20 to 93 students, door open and closed?",
              "trials_quick": 6, "trials_full": 100, "run": run, "plot": plot, "table": table}
