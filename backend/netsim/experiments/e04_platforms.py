"""E04 Android/iOS mix: iOS share x TX-power asymmetry, with and without the server's self-calibration."""
from __future__ import annotations

from dataclasses import replace

from netsim import metrics, plots
from netsim.experiments import common as C
from netsim.runner import cached_map
from netsim.server import trial

SHARES = (0.0, 0.25, 0.5, 0.75, 1.0)
ASYM = (0.0, 6.0, 12.0, 18.0)


def job_raw(j):
    cfg, p, seed, cal = j
    return trial(cfg, p, seed, calibrate=cal)


def run(ctx):
    n = ctx.n(EXPERIMENT)
    rows, check = [], {}
    for share in SHARES:
        for x in ASYM:
            cfg = replace(C.cfg_for("class93", ios_share=share), door_open=False)
            cfg = replace(cfg, models={**cfg.models, "iphone": {**cfg.models["iphone"], "tx": 3.0 + x}})
            p = C.params_for(cfg)
            for cal in (True, False):
                rs = C.trial_rows(ctx, f"e04/{share}/{x}/{cal}", cfg, replace(p, autocal=cal), n)
                rows.append({"ios_share": share, "asym_db": x, "selfcal": cal, **C.rates(rs)})
                check[f"{share}/{x}/{cal}"] = C.counts(rs)["false_absent"]
    # Does the server need a per-model offset table? calibrate=True models a table with every phone model in it (the simulator's
    # default elsewhere); calibrate=False is a fresh server: raw readings, only the engine's per-platform self-calibration.
    table_rows = []
    for size in (20, 35, 60, 93):
        cfg = replace(C.cfg_for("class93", students=size, ios_share=0.30), door_open=False)
        for cal in (True, False):
            rs = cached_map(f"e04/table/{size}/{cal}", job_raw, [(cfg, C.params_for(cfg), s, cal) for s in range(n)], ctx.cache, ctx.workers)
            table_rows.append({"students": size, "model_table": cal,
                               "far": metrics.ratio_ci([r["false_absent"] for r in rs], [r["inside"] for r in rs], seed=1)})
            check[f"table/{size}/{cal}"] = sum(r["false_absent"] for r in rs)
    return {"rows": rows, "table_rows": table_rows, "check": check}


def plot(res, figdir):
    if not plots.available():
        return []
    import numpy as np
    P = plots.plt()
    fig, axes = P.subplots(1, 2, figsize=(6.6, 2.7), sharey=True)
    for ax, cal in zip(axes, (False, True)):
        M = np.array([[next(100 * r["far"]["est"] for r in res["rows"] if r["ios_share"] == s and r["asym_db"] == x and r["selfcal"] == cal)
                       for x in ASYM] for s in SHARES])
        im = ax.imshow(M, vmin=0, vmax=50, cmap="viridis_r", aspect="auto", origin="lower")
        ax.set_xticks(range(len(ASYM))); ax.set_xticklabels([f"{x:g}" for x in ASYM]); ax.set_yticks(range(len(SHARES)))
        ax.set_yticklabels([f"{int(100 * s)}%" for s in SHARES]); ax.set_xlabel("extra iPhone TX power (dB)")
        ax.set_title("self-calibration " + ("ON" if cal else "OFF")); ax.grid(False)
        for i in range(M.shape[0]):
            for j in range(M.shape[1]):
                ax.text(j, i, f"{M[i, j]:.1f}", ha="center", va="center", fontsize=6, color="white" if M[i, j] < 25 else "black")
    axes[0].set_ylabel("iPhone share"); fig.colorbar(im, ax=axes, label="students marked absent (%)")
    return plots.save(fig, figdir, "e04_platforms")


def table(res):
    h = ["iOS share", "TX asymmetry (dB)", "self-cal", "false-absent"]
    rows = [[f"{int(100 * r['ios_share'])}%", r["asym_db"], "on" if r["selfcal"] else "off", C.pct(r["far"])] for r in res["rows"]]
    h2 = ["students", "per-model offset table on the server", "false-absent (30% iOS)"]
    rows2 = [[r["students"], "yes" if r["model_table"] else "NO (fresh server)", C.pct(r["far"])] for r in res["table_rows"]]
    return C.md_table(h, rows) + "\n\n" + C.md_table(h2, rows2), C.latex_table(h, rows, "Mixed Android/iOS classes at 93 students, door closed.", "tab:e04")


EXPERIMENT = {"id": "E04", "title": "Android/iOS mix", "question": "Does the system hold up for any mix of phones, and what does self-calibration buy?",
              "trials_quick": 4, "trials_full": 40, "run": run, "plot": plot, "table": table}
