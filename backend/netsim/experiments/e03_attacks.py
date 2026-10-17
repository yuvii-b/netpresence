"""E03 Attacks and the co-location defence: collusion vs k, relay with/without the defence, RSSI inflation, ROC of colocation_db."""
from __future__ import annotations

from dataclasses import replace

from netsim import attacks, metrics, plots
from netsim.experiments import common as C
from netsim.runner import cached_map

THRESHOLDS = (0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0)


def job_collusion(j):
    cfg, p, seed, c = j
    return {"ok": int(attacks.collusion_trial(cfg, p, seed, c))}


def job_relay(j):
    cfg, p, seed, relays = j
    return attacks.relay_trial(cfg, p, seed, relays)


def job_inflate(j):
    cfg, p, seed, x = j
    r = attacks.inflation_trial(cfg, p, seed, x)
    return {"admitted": int(r["liar_admitted"]), "false_absent": r["false_absent"], "inside": r["inside"]}


def run(ctx):
    n = ctx.n(EXPERIMENT)
    cfg = replace(C.cfg_for("class60"), door_open=False)
    p = C.params_for(cfg)
    res = {"collusion": [], "relay": [], "inflation": [], "roc": [], "check": {}}
    for k in (1, 2, 3):
        for c in range(0, 5):
            rs = cached_map(f"e03/col/{k}/{c}", job_collusion, [(cfg, replace(p, k=k), s, c) for s in range(n)], ctx.cache, ctx.workers)
            res["collusion"].append({"k": k, "accomplices": c, "success": metrics.ratio_ci([r["ok"] for r in rs], [1] * len(rs), seed=1)})
            res["check"][f"col/{k}/{c}"] = sum(r["ok"] for r in rs)
    for defence in (False, True):
        for relays in (1, 3, 5):
            pp = replace(p, colocation_db=2.5 if defence else 0.0)
            rs = cached_map(f"e03/relay/{defence}/{relays}", job_relay, [(cfg, pp, s, relays) for s in range(n)], ctx.cache, ctx.workers)
            res["relay"].append({"defence": defence, "relays": relays,
                                 "admitted": metrics.ratio_ci([r["relay_admitted"] for r in rs], [r["relays"] for r in rs], seed=2),
                                 "flagged": metrics.ratio_ci([r["relay_flagged"] for r in rs], [r["relays"] for r in rs], seed=3),
                                 "honest_flagged": metrics.ratio_ci([r["honest_flagged"] for r in rs], [r["honest"] for r in rs], seed=4)})
            res["check"][f"relay/{defence}/{relays}"] = [sum(r["relay_admitted"] for r in rs), sum(r["honest_flagged"] for r in rs)]
    for x in (0, 5, 10, 15, 20):
        rs = cached_map(f"e03/inf/{x}", job_inflate, [(cfg, p, s, x) for s in range(n)], ctx.cache, ctx.workers)
        res["inflation"].append({"x_db": x, "liar_admitted": metrics.ratio_ci([r["admitted"] for r in rs], [1] * len(rs), seed=5),
                                 "far": metrics.ratio_ci([r["false_absent"] for r in rs], [r["inside"] for r in rs], seed=6)})
        res["check"][f"inf/{x}"] = sum(r["admitted"] for r in rs)
    for thr in THRESHOLDS:
        pp = replace(p, colocation_db=thr)
        rs = cached_map(f"e03/roc/{thr}", job_relay, [(cfg, pp, s, 5) for s in range(n)], ctx.cache, ctx.workers)
        res["roc"].append({"threshold_db": thr,
                           "tpr": metrics.ratio_ci([r["relay_flagged"] for r in rs], [r["relays"] for r in rs], seed=7),
                           "fpr": metrics.ratio_ci([r["honest_flagged"] for r in rs], [r["honest"] for r in rs], seed=8)})
        res["check"][f"roc/{thr}"] = [sum(r["relay_flagged"] for r in rs), sum(r["honest_flagged"] for r in rs)]
    return res


def plot(res, figdir):
    if not plots.available():
        return []
    P = plots.plt()
    fig, ax = P.subplots(1, 3, figsize=(7.4, 2.6))
    for i, k in enumerate((1, 2, 3)):
        sel = [r for r in res["collusion"] if r["k"] == k]
        plots.errorbar(ax[0], [r["accomplices"] for r in sel], [r["success"] for r in sel], label=f"k = {k}", marker=i)
    ax[0].set_xlabel("in-room accomplices"); ax[0].set_ylabel("absent friend admitted (%)"); ax[0].legend(); ax[0].set_title("A3 collusion")
    for i, d in enumerate((False, True)):
        sel = [r for r in res["relay"] if r["defence"] == d]
        plots.errorbar(ax[1], [r["relays"] for r in sel], [r["admitted"] for r in sel], label="with co-location check" if d else "without", marker=i)
    ax[1].set_xlabel("relays in the class"); ax[1].set_ylabel("friend admitted (%)"); ax[1].legend(); ax[1].set_title("A4 relay")
    ax[2].plot([100 * r["fpr"]["est"] for r in res["roc"]], [100 * r["tpr"]["est"] for r in res["roc"]], "o-", markersize=3)
    for r in res["roc"]:
        ax[2].annotate(f"{r['threshold_db']:g}", (100 * r["fpr"]["est"], 100 * r["tpr"]["est"]), fontsize=6, xytext=(3, -8), textcoords="offset points")
    ax[2].set_xlabel("honest students flagged (%)"); ax[2].set_ylabel("relays flagged (%)"); ax[2].set_title("ROC of colocation_db (dB)")
    return plots.save(fig, figdir, "e03_attacks")


def table(res):
    h = ["attack", "setting", "outcome"]
    rows = [["A3 collusion", f"k={r['k']}, accomplices={r['accomplices']}", "friend admitted " + C.pct(r["success"])] for r in res["collusion"]]
    rows += [["A4 relay", f"{'with' if r['defence'] else 'without'} co-location, {r['relays']} relays",
              f"admitted {C.pct(r['admitted'])}, flagged {C.pct(r['flagged'])}, honest flagged {C.pct(r['honest_flagged'])}"] for r in res["relay"]]
    rows += [["A5 inflation", f"+{r['x_db']} dB", f"corridor phone admitted {C.pct(r['liar_admitted'])}, false-absent {C.pct(r['far'])}"] for r in res["inflation"]]
    rows += [["ROC", f"colocation_db={r['threshold_db']}", f"relays flagged {C.pct(r['tpr'])}, honest flagged {C.pct(r['fpr'])}"] for r in res["roc"]]
    return C.md_table(h, rows), C.latex_table(h, rows, "Attacks on the roll call (60 students, door closed).", "tab:e03")


EXPERIMENT = {"id": "E03", "title": "Attacks and the co-location defence", "question": "Which attacks work, and how well does the co-location check stop relays?",
              "trials_quick": 6, "trials_full": 60, "run": run, "plot": plot, "table": table}
