"""E13 Trace-driven channel vs the parametric model. With no BLE-lab data the trace is SYNTHETIC (drawn from the parametric model),
so agreement only proves the plumbing; the table says so. Put real CSV v2 files in <real_dir>/traces/ to make it a real comparison."""
from __future__ import annotations

import tempfile
from dataclasses import replace
from pathlib import Path

from netsim import traces
from netsim.experiments import common as C


def trace_source(ctx) -> tuple[str, bool]:
    d = Path(ctx.real_dir or ".") / "traces"
    if d.is_dir() and any(d.glob("*.csv")):
        return str(d), False
    f = Path(tempfile.gettempdir()) / "netpresence_synthetic_trace" / "synthetic.csv"
    if not f.is_file():
        f.parent.mkdir(parents=True, exist_ok=True)
        traces.synthesize(C.cfg_for("class93"), f, seed=0)
    return str(f), True


def run(ctx):
    n = ctx.n(EXPERIMENT)
    src, synthetic = trace_source(ctx)
    rows, check = [], {}
    for size in (35, 93):
        for door in (False, True):
            base = replace(C.cfg_for("class93", students=size, ios_share=0.15), door_open=door)
            for chan in ("parametric", "trace"):
                cfg = replace(base, channel=chan, trace_file=src if chan == "trace" else None)
                rs = C.trial_rows(ctx, f"e13/{size}/{door}/{chan}", cfg, C.params_for(cfg), n)
                rows.append({"students": size, "door": "open" if door else "closed", "channel": chan, **C.rates(rs)})
                check[f"{size}/{door}/{chan}"] = C.counts(rs)
    return {"trace": "SYNTHETIC (drawn from the parametric model; not measured)" if synthetic else "REAL BLE-lab trace", "rows": rows, "check": check}


def plot(res, figdir):
    return []


def table(res):
    h = ["students", "door", "channel", "false-absent", "corridor admitted"]
    rows = [[r["students"], r["door"], r["channel"], C.pct(r["far"]), C.pct(r["fpr"])] for r in res["rows"]]
    return f"Trace source: **{res['trace']}**\n\n" + C.md_table(h, rows), C.latex_table(h, rows, "Trace-driven vs parametric channel (" + res["trace"] + ").", "tab:e13")


EXPERIMENT = {"id": "E13", "title": "Trace-driven channel", "question": "Do empirical RSSI tables from the BLE lab change the conclusions?",
              "trials_quick": 3, "trials_full": 40, "run": run, "plot": plot, "table": table}
