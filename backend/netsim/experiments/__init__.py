"""Paper experiments E01..E14 (docs/SIM_PLAN.md section 6). Each module exposes EXPERIMENT = {id, title, question,
trials_quick, trials_full, run(ctx) -> dict, plot(result, figdir) -> [files], table(result) -> (markdown, latex)}.
`python -m paper.make` runs them; each is also runnable alone: python -m paper.make --only E03."""
from __future__ import annotations

import importlib
from dataclasses import dataclass

from netsim.runner import Cache

IDS = ["e01_accuracy", "e02_mechanisms", "e03_attacks", "e04_platforms", "e05_speed", "e06_uplink", "e07_ble",
       "e08_robustness", "e09_baselines", "e10_backbench", "e11_scalability", "e12_simreal", "e13_traces", "e14_energy"]


@dataclass
class Ctx:
    quick: bool = True
    workers: int = 1
    cache: Cache | None = None
    real_dir: str | None = None          # paper/real: measurements from real phones (E12, E13)

    def n(self, exp: dict) -> int:
        return exp["trials_quick"] if self.quick else exp["trials_full"]


def load(exp_id: str | None = None):
    """All experiments (or the one whose id/module starts with exp_id), in order."""
    mods = [m for m in IDS if exp_id is None or m.lower().startswith(exp_id.lower())]
    return [importlib.import_module(f"netsim.experiments.{m}").EXPERIMENT for m in mods]
