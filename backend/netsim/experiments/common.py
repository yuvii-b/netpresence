"""Helpers shared by the experiments."""
from __future__ import annotations

from dataclasses import replace

from app.services.graph import Params, adaptive_edge_m
from netsim import config, metrics
from netsim.runner import cached_map
from netsim.server import trial


def job_trial(job):
    cfg, p, seed = job
    return trial(cfg, p, seed)


def cfg_for(preset: str = "class93", **ov):
    return replace(config.load(preset), **ov)


def params_for(cfg, **kw) -> Params:
    """What the server uses: density-adaptive edge threshold unless overridden."""
    kw.setdefault("max_edge_m", adaptive_edge_m(cfg.students or cfg.capacity))
    return Params(**kw)


def trial_rows(ctx, name: str, cfg, p: Params, n: int, seed0: int = 0) -> list[dict]:
    return cached_map(name, job_trial, [(cfg, p, seed0 + s) for s in range(n)], ctx.cache, ctx.workers)


def rates(rows: list[dict]) -> dict:
    far = metrics.ratio_ci([r["false_absent"] for r in rows], [r["inside"] for r in rows], seed=1)
    fpr = metrics.ratio_ci([r["false_present"] for r in rows], [r["outside"] for r in rows], seed=2)
    return {"far": far, "fpr": fpr, "classrooms": len(rows)}


def counts(rows: list[dict]) -> dict:
    """Integer totals: what the cross-OS determinism hash is built from."""
    return {k: sum(r[k] for r in rows) for k in ("inside", "false_absent", "outside", "false_present")}


def md_table(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def latex_table(headers: list[str], rows: list[list], caption: str, label: str) -> str:
    esc = lambda s: str(s).replace("%", "\\%").replace("_", "\\_").replace("&", "\\&")
    body = "\n".join(" & ".join(esc(c) for c in r) + " \\\\" for r in rows)
    return ("\\begin{table}[t]\n\\centering\n\\caption{" + esc(caption) + "}\\label{" + label + "}\n\\begin{tabular}{"
            + "l" * len(headers) + "}\n\\toprule\n" + " & ".join(esc(h) for h in headers) + " \\\\\n\\midrule\n" + body
            + "\n\\bottomrule\n\\end{tabular}\n\\end{table}\n")


def pct(ci: dict) -> str:
    return metrics.pct(ci)
