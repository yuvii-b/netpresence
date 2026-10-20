"""E12 Simulator vs real phones. Reads <real_dir>/sessions.csv (format in paper/real/README.md); without it the experiment records
that no real data exists and reports only the simulator's prediction, so no result can pass as measured by accident."""
from __future__ import annotations

import csv
from dataclasses import replace
from pathlib import Path

from netsim import metrics, plots
from netsim.experiments import common as C

COLUMNS = ("session", "preset", "students_inside", "marked_absent_inside", "outside", "marked_present_outside", "ios_share")


def read_real(real_dir) -> list[dict]:
    f = Path(real_dir or ".") / "sessions.csv"
    if not f.is_file():
        return []
    with open(f, newline="", encoding="utf-8") as fh:
        rd = csv.DictReader(fh)
        missing = [c for c in COLUMNS if c not in (rd.fieldnames or [])]
        if missing:
            raise ValueError(f"{f}: missing columns {missing}; expected {COLUMNS}")
        return [{"session": r["session"], "preset": r["preset"], "inside": int(r["students_inside"]), "absent": int(r["marked_absent_inside"]),
                 "outside": int(r["outside"]), "present_out": int(r["marked_present_outside"]), "ios": float(r["ios_share"])} for r in rd]


def run(ctx):
    n = ctx.n(EXPERIMENT)
    real = read_real(ctx.real_dir)
    presets = sorted({r["preset"] for r in real}) or ["lab6"]
    rows, check = [], {}
    for pr in presets:
        mine = [r for r in real if r["preset"] == pr]
        ios = (sum(r["ios"] for r in mine) / len(mine)) if mine else 0.0
        cfg = replace(C.cfg_for(pr, ios_share=ios), door_open=False)
        rs = C.trial_rows(ctx, f"e12/{pr}", cfg, C.params_for(cfg), n)
        row = {"preset": pr, "sessions_real": len(mine), "sim": C.rates(rs)}
        if mine:
            row["real_far"] = metrics.ratio_ci([r["absent"] for r in mine], [r["inside"] for r in mine], seed=1)
            row["real_fpr"] = metrics.ratio_ci([r["present_out"] for r in mine], [max(r["outside"], 1) for r in mine], seed=2)
        rows.append(row)
        check[pr] = [C.counts(rs)["false_absent"], len(mine)]
    return {"status": "compared" if real else "NO REAL DATA: simulator prediction only", "rows": rows, "check": check}


def plot(res, figdir):
    if not plots.available() or not any("real_far" in r for r in res["rows"]):
        return []
    P = plots.plt()
    fig, ax = P.subplots(figsize=(3.6, 2.6))
    for i, r in enumerate(x for x in res["rows"] if "real_far" in x):
        ax.errorbar([i - 0.1], [100 * r["sim"]["far"]["est"]], fmt="o", label="simulated" if i == 0 else None, color=plots.OKABE_ITO[0])
        ax.errorbar([i + 0.1], [100 * r["real_far"]["est"]], fmt="s", label="real phones" if i == 0 else None, color=plots.OKABE_ITO[1])
    ax.set_ylabel("students marked absent (%)"); ax.legend()
    return plots.save(fig, figdir, "e12_simreal")


def table(res):
    h = ["preset", "real sessions", "simulated false-absent", "real false-absent", "simulated corridor", "real corridor"]
    rows = [[r["preset"], r["sessions_real"], C.pct(r["sim"]["far"]), C.pct(r["real_far"]) if "real_far" in r else "n/a",
             C.pct(r["sim"]["fpr"]), C.pct(r["real_fpr"]) if "real_fpr" in r else "n/a"] for r in res["rows"]]
    return f"**{res['status']}**\n\n" + C.md_table(h, rows), C.latex_table(h, rows, "Simulator against real phones (" + res["status"] + ").", "tab:e12")


EXPERIMENT = {"id": "E12", "title": "Simulator vs real phones", "question": "Does the simulator predict what real phones do?",
              "trials_quick": 4, "trials_full": 100, "run": run, "plot": plot, "table": table}
