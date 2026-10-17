"""E05 Speed: check-in window x tap delay (accuracy), and how long each student waits compared with calling names."""
from __future__ import annotations

from dataclasses import replace

import numpy as np

from netsim import baselines, metrics, plots
from netsim.experiments import common as C
from netsim.phone import tap_times

WINDOWS = (10, 15, 20, 30, 45)
TAPS = (2.0, 4.0, 6.0, 10.0)
GRACE_S = 10.0     # server-side report grace after the window closes (protocol)


def waits(cfg, n=20000):
    """Per-student wait from tapping to the verdict: the check closes at window+tail+grace, whatever the tap time."""
    t = tap_times(cfg, np.random.default_rng(7), n)
    t = t[t <= cfg.window_s]
    w = cfg.window_s + cfg.tail_s + GRACE_S - t
    return metrics.quantiles(w, (0.5, 0.95))


def run(ctx):
    n = ctx.n(EXPERIMENT)
    rows, check = [], {}
    for w in WINDOWS:
        for tap in TAPS:
            cfg = replace(C.cfg_for("class93", ios_share=0.15), door_open=False, window_s=float(w), tap_median_s=tap)
            rs = C.trial_rows(ctx, f"e05/{w}/{tap}", cfg, C.params_for(cfg), n)
            q = waits(cfg)
            rows.append({"window_s": w, "tap_median_s": tap, **C.rates(rs), "wait_p50_s": q[0], "wait_p95_s": q[1]})
            check[f"{w}/{tap}"] = C.counts(rs)["false_absent"]
    man = [baselines.b0_manual(replace(C.cfg_for("class93"), door_open=False), s) for s in range(max(n, 4))]
    total = float(np.mean([m["time_s"] for m in man]))
    # a student is reached uniformly through the call: wait is U(0, total)
    manual = {"total_s": total, "wait_p50_s": total / 2, "wait_p95_s": 0.95 * total}
    return {"rows": rows, "manual": manual, "check": check}


def plot(res, figdir):
    if not plots.available():
        return []
    P = plots.plt()
    fig, ax = P.subplots(1, 2, figsize=(6.8, 2.6))
    for i, tap in enumerate(TAPS):
        sel = [r for r in res["rows"] if r["tap_median_s"] == tap]
        plots.errorbar(ax[0], [r["window_s"] for r in sel], [r["far"] for r in sel], label=f"tap median {tap:g} s", marker=i)
    ax[0].set_xlabel("check-in window (s)"); ax[0].set_ylabel("students marked absent (%)"); ax[0].legend(); ax[0].set_ylim(bottom=0)
    sel = [r for r in res["rows"] if r["tap_median_s"] == 4.0]
    ax[1].bar(["NetPresence\n(median)", "NetPresence\n(95th)", "manual\n(median)", "manual\n(95th)"],
              [next(r["wait_p50_s"] for r in sel if r["window_s"] == 20), next(r["wait_p95_s"] for r in sel if r["window_s"] == 20),
               res["manual"]["wait_p50_s"], res["manual"]["wait_p95_s"]], color=plots.OKABE_ITO[:1] * 2 + plots.OKABE_ITO[1:2] * 2)
    ax[1].set_ylabel("seconds a student waits for the verdict")
    return plots.save(fig, figdir, "e05_speed")


def table(res):
    h = ["window (s)", "tap median (s)", "false-absent", "wait p50 / p95 (s)"]
    rows = [[r["window_s"], r["tap_median_s"], C.pct(r["far"]), f"{r['wait_p50_s']:.0f} / {r['wait_p95_s']:.0f}"] for r in res["rows"]]
    m = res["manual"]
    rows.append(["manual roll call", "-", "0% (proxies possible)", f"{m['wait_p50_s']:.0f} / {m['wait_p95_s']:.0f}"])
    return C.md_table(h, rows), C.latex_table(h, rows, "Check-in window, tap delay and waiting time (93 students).", "tab:e05")


EXPERIMENT = {"id": "E05", "title": "Speed", "question": "How short can the window be, and how long does a student wait compared with calling names?",
              "trials_quick": 3, "trials_full": 40, "run": run, "plot": plot, "table": table}
