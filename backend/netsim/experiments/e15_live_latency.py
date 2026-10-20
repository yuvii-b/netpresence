"""E15 Time to Present in the live flow: how long after the teacher starts the class does a student's phone say Present?

Protocol v3 (docs/PIVOT_PLAN.md): phones join by themselves, report every second, the server re-evaluates continuously. The number
that matters to a student is the time from "my phone learned a roll call is open" to "the server said Present", per class size and
uplink. SIMULATED with the assumed radio / network values (tags in netsim.config and netsim.live)."""
from __future__ import annotations

from dataclasses import replace

import numpy as np

from app.services.graph import Params, adaptive_edge_m
from netsim import plots
from netsim.experiments import common as C
from netsim.live import LiveConfig, live_trial
from netsim.runner import cached_map

SIZES = (35, 60, 93)
UPLINKS = (("good Wi-Fi", "wifi_good"), ("congested Wi-Fi", "wifi_congested"), ("70% Wi-Fi + 30% 4G", "wifi_good:0.7,cell_4g:0.3"))


def job(j):
    cfg, seed = j
    r = live_trial(cfg, LiveConfig(), Params(max_edge_m=adaptive_edge_m(cfg.students)), seed)
    r["ttp"] = [round(x, 2) for x in r["ttp"]]
    return r


def run(ctx):
    n = ctx.n(EXPERIMENT)
    rows = []
    for size in SIZES:
        for label, up in UPLINKS:
            cfg = replace(C.cfg_for("class93", ios_share=0.30, uplink=up), students=size, door_open=False)
            rs = cached_map(f"e15/{size}/{up}", job, [(cfg, s) for s in range(n)], ctx.cache, ctx.workers)
            v = np.concatenate([r["ttp"] for r in rs]) if rs else np.array([np.nan])
            rows.append({"students": size, "uplink": label,
                         "ttp_p50": float(np.percentile(v, 50)), "ttp_p95": float(np.percentile(v, 95)), "ttp_max": float(v.max()),
                         "cdf": [float(x) for x in np.percentile(v, range(0, 101, 5))],
                         "false_absent": C.rates(rs)["far"], "finish_s": float(np.mean([r["finish_s"] for r in rs])),
                         "check": C.counts(rs)})
    return {"rows": rows}


def plot(res, figdir):
    if not plots.available():
        return []
    P = plots.plt()
    fig, axes = P.subplots(1, len(SIZES), figsize=(7.4, 2.6), sharey=True)
    for ax, size in zip(axes, SIZES):
        for r in (x for x in res["rows"] if x["students"] == size):
            ax.plot(r["cdf"], list(range(0, 101, 5)), label=r["uplink"])
        ax.set_title(f"{size} students"); ax.set_xlabel("time to Present (s)")
    axes[0].set_ylabel("students (%)"); axes[-1].legend(loc="lower right")
    return plots.save(fig, figdir, "e15_live_latency")


def table(res):
    h = ["students", "uplink", "time to Present p50 (s)", "p95 (s)", "false-absent %"]
    rows = [[r["students"], r["uplink"], f"{r['ttp_p50']:.1f}", f"{r['ttp_p95']:.1f}", f"{100 * r['false_absent']['est']:.2f}"] for r in res["rows"]]
    return C.md_table(h, rows), C.latex_table(h, rows, "Live roll call: time until a student's phone says Present (simulated, assumed radio and network values).", "tab:e15")


EXPERIMENT = {"id": "E15", "title": "Live time-to-Present", "question": "How fast does a student's phone say Present once the teacher starts the class?",
              "trials_quick": 2, "trials_full": 30, "run": run, "plot": plot, "table": table}
