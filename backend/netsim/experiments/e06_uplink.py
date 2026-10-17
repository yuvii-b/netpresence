"""E06 Uplink: network profile x upload jitter x head-count (real retry ladder and 5 s request timeout)."""
from __future__ import annotations

from dataclasses import replace

from netsim import metrics, plots
from netsim.experiments import common as C

PROFILES = ("ideal", "wifi_good", "wifi_congested", "cell_4g", "wifi_congested:0.7,cell_4g:0.3")
JITTERS = (0.0, 2.0, 5.0)
SIZES = (35, 93)


def run(ctx):
    n = ctx.n(EXPERIMENT)
    rows, check = [], {}
    for prof in PROFILES:
        for j in JITTERS:
            for size in SIZES:
                cfg = replace(C.cfg_for("class93", students=size, ios_share=0.15), door_open=False, uplink=prof, upload_jitter_s=j)
                rs = C.trial_rows(ctx, f"e06/{prof}/{j}/{size}", cfg, C.params_for(cfg), n)
                up = [r["uplink"] for r in rs if "uplink" in r]
                rows.append({"profile": prof, "jitter_s": j, "students": size, **C.rates(rs),
                             "delivered": metrics.mean_ci([u["delivered_pct"] for u in up], seed=3) if up else None,
                             "t_all_in": metrics.mean_ci([u["t_all_in_s"] for u in up], seed=4) if up else None,
                             "attempts": metrics.mean_ci([u["attempts_mean"] for u in up], seed=5) if up else None})
                check[f"{prof}/{j}/{size}"] = C.counts(rs)["false_absent"]
    return {"rows": rows, "check": check}


def plot(res, figdir):
    if not plots.available():
        return []
    P = plots.plt()
    fig, ax = P.subplots(1, 2, figsize=(6.8, 2.7))
    sel = [r for r in res["rows"] if r["students"] == 93]
    for i, j in enumerate(JITTERS):
        s = [r for r in sel if r["jitter_s"] == j]
        ax[0].bar([k + 0.27 * (i - 1) for k in range(len(s))], [100 * r["far"]["est"] for r in s], 0.27, label=f"jitter {j:g} s")
        ax[1].bar([k + 0.27 * (i - 1) for k in range(len(s))], [r["t_all_in"]["est"] if r["t_all_in"] else 0 for r in s], 0.27)
    for a in ax:
        a.set_xticks(range(len(PROFILES))); a.set_xticklabels(["ideal", "wifi", "wifi\ncongested", "4G", "mix"], fontsize=7)
    ax[0].set_ylabel("students marked absent (%)"); ax[1].set_ylabel("last report processed (s)"); ax[0].legend()
    return plots.save(fig, figdir, "e06_uplink")


def table(res):
    h = ["profile", "jitter (s)", "students", "false-absent", "delivered %", "last report (s)", "attempts"]
    f = lambda c: "-" if c is None else f"{c['est']:.1f}"
    rows = [[r["profile"], r["jitter_s"], r["students"], C.pct(r["far"]), f(r["delivered"]), f(r["t_all_in"]), f(r["attempts"])] for r in res["rows"]]
    return C.md_table(h, rows), C.latex_table(h, rows, "Report upload under different networks.", "tab:e06")


EXPERIMENT = {"id": "E06", "title": "Uplink", "question": "Is the network ever the bottleneck, and does upload jitter help?",
              "trials_quick": 3, "trials_full": 30, "run": run, "plot": plot, "table": table}
