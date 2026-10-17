"""E04 Android/iOS mix: iOS share x TX-power asymmetry, with and without the server's self-calibration."""
from __future__ import annotations

from dataclasses import replace

from netsim import plots
from netsim.experiments import common as C

SHARES = (0.0, 0.25, 0.5, 0.75, 1.0)
ASYM = (0.0, 6.0, 12.0, 18.0)


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
    return {"rows": rows, "check": check}


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
    return C.md_table(h, rows), C.latex_table(h, rows, "Mixed Android/iOS classes at 93 students, door closed.", "tab:e04")


EXPERIMENT = {"id": "E04", "title": "Android/iOS mix", "question": "Does the system hold up for any mix of phones, and what does self-calibration buy?",
              "trials_quick": 4, "trials_full": 40, "run": run, "plot": plot, "table": table}
