"""E16 Who the server trusts as the root: teacher phone alone, the verified front bench (v2 behaviour), or both."""
from __future__ import annotations

from dataclasses import replace

import numpy as np

from app.services.graph import Params, adaptive_edge_m
from netsim import plots
from netsim.experiments import common as C
from netsim.live import SEED_MODES, LiveConfig, live_trial
from netsim.runner import cached_map

LABEL = {"teacher_phone": "teacher phone", "front_bench": "front bench verified", "teacher_phone_plus_front": "teacher phone + front bench"}


def job(j):
    cfg, mode, seed = j
    r = live_trial(cfg, LiveConfig(seed_mode=mode), Params(max_edge_m=adaptive_edge_m(cfg.students)), seed)
    r.pop("ttp")
    return r


def run(ctx):
    n = ctx.n(EXPERIMENT)
    rows = []
    for door in (False, True):
        cfg = replace(C.cfg_for("class93", ios_share=0.30, uplink="wifi_good"), students=93, door_open=door)
        for mode in SEED_MODES:
            rs = cached_map(f"e16/{door}/{mode}", job, [(cfg, mode, s) for s in range(n)], ctx.cache, ctx.workers)
            c = C.rates(rs)
            rows.append({"door_open": door, "mode": LABEL[mode], "far": c["far"], "fpr": c["fpr"],
                         "ttp_p50": float(np.mean([r["ttp_p50"] for r in rs])), "check": C.counts(rs)})
    return {"rows": rows}


def plot(res, figdir):
    return []


def table(res):
    h = ["seed", "door", "false-absent %", "corridor present %", "time to Present p50 (s)"]
    rows = [[r["mode"], "open" if r["door_open"] else "closed", f"{100 * r['far']['est']:.2f}", f"{100 * r['fpr']['est']:.2f}", f"{r['ttp_p50']:.1f}"] for r in res["rows"]]
    return C.md_table(h, rows), C.latex_table(h, rows, "Live roll call: which phones the server trusts as the root (simulated).", "tab:e16")


EXPERIMENT = {"id": "E16", "title": "Seed mode", "question": "Is the teacher phone alone enough as the root of trust?",
              "trials_quick": 2, "trials_full": 30, "run": run, "plot": plot, "table": table}
