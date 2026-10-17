"""E07 BLE contention: phones per room x advertising interval x capture, analytical (fast) vs packet-level (DES) model."""
from __future__ import annotations

from dataclasses import replace

from netsim import metrics, plots
from netsim.experiments import common as C

SIZES = (10, 30, 60, 93)
ADV = (100.0, 200.0, 300.0)
CELLS = [("fast", False), ("des", False), ("des", True)]


def _cfg(size, adv, mode, capture):
    cfg = replace(C.cfg_for("class93", students=size, ios_share=0.15), door_open=False, ble_mode=mode, capture=capture)
    ms = {k: {**v, "adv_ms": adv if v["platform"] == "android" else max(v["adv_ms"], adv)} for k, v in cfg.models.items()}
    return replace(cfg, models=ms)


def run(ctx):
    n = ctx.n(EXPERIMENT)
    rows, check = [], {}
    for size in SIZES:
        for adv in ADV:
            for mode, cap in CELLS:
                cfg = _cfg(size, adv, mode, cap)
                rs = C.trial_rows(ctx, f"e07/{size}/{adv}/{mode}/{cap}", cfg, C.params_for(cfg), n)
                d = [r["des"] for r in rs if "des" in r]
                coll = [100.0 * x.get("collided", 0) / max(sum(v for v in x.values() if isinstance(v, (int, float))), 1) for x in d]
                rows.append({"students": size, "adv_ms": adv, "mode": mode, "capture": cap, **C.rates(rs),
                             "collision_pct": metrics.mean_ci(coll, seed=3) if d else None})
                check[f"{size}/{adv}/{mode}/{cap}"] = C.counts(rs)["false_absent"]
    return {"rows": rows, "check": check}


def plot(res, figdir):
    if not plots.available():
        return []
    P = plots.plt()
    fig, ax = P.subplots(1, 3, figsize=(7.4, 2.6), sharey=True)
    for a, adv in zip(ax, ADV):
        for i, (mode, cap) in enumerate(CELLS):
            s = [r for r in res["rows"] if r["adv_ms"] == adv and r["mode"] == mode and r["capture"] == cap]
            plots.errorbar(a, [r["students"] for r in s], [r["far"] for r in s], label=f"{mode}{' + capture' if cap else ''}", marker=i)
        a.set_title(f"advertising {adv:g} ms"); a.set_xlabel("phones in the room"); a.set_ylim(bottom=0)
    ax[0].set_ylabel("students marked absent (%)"); ax[0].legend()
    return plots.save(fig, figdir, "e07_ble")


def table(res):
    h = ["students", "adv (ms)", "model", "false-absent", "PDUs lost to collisions %"]
    rows = [[r["students"], r["adv_ms"], r["mode"] + ("+capture" if r["capture"] else ""), C.pct(r["far"]),
             "-" if not r["collision_pct"] or r["collision_pct"]["est"] != r["collision_pct"]["est"] else f"{r['collision_pct']['est']:.1f}"] for r in res["rows"]]
    return C.md_table(h, rows), C.latex_table(h, rows, "BLE contention: Poisson vs packet-level model.", "tab:e07")


EXPERIMENT = {"id": "E07", "title": "BLE contention", "question": "Do advertising collisions matter at 93 phones, and does the fast model agree with the packet-level one?",
              "trials_quick": 2, "trials_full": 20, "run": run, "plot": plot, "table": table}
