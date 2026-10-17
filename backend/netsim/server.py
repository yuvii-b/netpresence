"""The server layer: the REAL engine (app.services.graph.evaluate) fed with simulated reports. Never re-implemented."""
from __future__ import annotations

import random

from app.services.graph import Params, evaluate
from netsim.ble_fast import synth_reports
from netsim.config import RoomConfig
from netsim.scenario import build_scene, platforms


def trial(cfg: RoomConfig, p: Params, seed: int, calibrate: bool = True) -> dict:
    rng = random.Random(seed)
    nodes, seeds, wall = build_scene(cfg, rng)
    st: dict = {}
    reports = synth_reports(cfg, nodes, wall, rng, calibrate, stats=st)
    present = evaluate(seeds, reports, p, platforms(cfg, nodes))["present"]
    ins = [k for k, v in nodes.items() if v["inside"] and k not in seeds]
    outs = [k for k, v in nodes.items() if not v["inside"]]
    in_present = [present[k] for k in ins if k in present]
    return {
        "inside": len(ins),
        "max_hops": max((v["hops"] for v in in_present), default=0),
        "max_path_m": max((v["path_m"] for v in in_present), default=0.0),
        "false_absent": sum(1 for k in ins if k not in present),
        "outside": len(outs),
        "false_present": sum(1 for k in outs if k in present),
        **st,
    }


def collusion_trial(cfg: RoomConfig, p: Params, seed: int, colluders: int) -> bool:
    from netsim import attacks
    return attacks.collusion_trial(cfg, p, seed, colluders)
