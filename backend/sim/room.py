"""Monte-Carlo classroom for tuning the proximity-graph parameters (plan phase 3).

Radio model per ordered pair (i hears j):
    rssi = A - 10 n log10(d) - body_db * (#occupied seats near the segment, capped)
           - wall_db (if the segment crosses the wall) + shadow_ij + noise_dir + bias(model_i)
shadow_ij is symmetric (same physical path), noise_dir is independent per direction.
Replace n, sigma, body_db with values fitted from the real-room measurements (tools/fit_pathloss.py).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from app.services.graph import Params, evaluate


@dataclass
class RoomConfig:
    rows: int = 6
    cols: int = 10
    pitch_x: float = 0.9          # m along a bench
    pitch_y: float = 1.2          # m between benches
    occupancy: float = 0.9
    A: float = -59.0
    n: float = 3.0
    shadow_sigma: float = 5.0     # dB, symmetric per pair
    dir_sigma: float = 2.0        # dB, per direction (fast fading residue after median filtering)
    body_db: float = 3.0
    body_cap: int = 3
    body_radius: float = 0.35
    wall_db: float = 12.0
    sensitivity: float = -95.0
    p_detect: float = 0.97        # chance a phone hears a given in-range peer in the window (advert collisions)
    n_outside: int = 8            # phones just past the wall (corridor / next class)
    models: dict = field(default_factory=lambda: {"ref": 0.0, "lowend": -4.0, "iphone": -9.0})
    model_mix: tuple = (0.55, 0.30, 0.15)
    n_seeds: int = 4


def _seg_point_dist(p, a, b):
    ax, ay = a; bx, by = b; px, py = p
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def build_scene(cfg: RoomConfig, rng: random.Random):
    seats = [(c * cfg.pitch_x, r * cfg.pitch_y) for r in range(cfg.rows) for c in range(cfg.cols)]
    occupied = [s for s in seats if rng.random() < cfg.occupancy]
    width = (cfg.cols - 1) * cfg.pitch_x
    wall_x = width + 0.6                      # side wall with the door
    outside = [(wall_x + rng.uniform(0.8, 3.0), rng.uniform(0, (cfg.rows - 1) * cfg.pitch_y)) for _ in range(cfg.n_outside)]
    nodes = {}
    names = list(cfg.models)
    for i, pos in enumerate(occupied):
        nodes[f"in{i}"] = {"pos": pos, "inside": True, "model": rng.choices(names, cfg.model_mix)[0]}
    for i, pos in enumerate(outside):
        nodes[f"out{i}"] = {"pos": pos, "inside": False, "model": rng.choices(names, cfg.model_mix)[0]}
    seeds = sorted((k for k, v in nodes.items() if v["inside"]), key=lambda k: (nodes[k]["pos"][1], nodes[k]["pos"][0]))[: cfg.n_seeds]
    return nodes, seeds, wall_x


def synth_reports(cfg: RoomConfig, nodes: dict, wall_x: float, rng: random.Random, calibrate: bool = True):
    ids = list(nodes)
    inside_pos = [v["pos"] for v in nodes.values() if v["inside"]]
    shadow, reports = {}, {k: {} for k in ids}
    for ai, a in enumerate(ids):
        for b in ids[ai + 1:]:
            pa, pb = nodes[a]["pos"], nodes[b]["pos"]
            d = max(0.3, math.dist(pa, pb))
            bodies = sum(1 for q in inside_pos if q not in (pa, pb) and _seg_point_dist(q, pa, pb) < cfg.body_radius)
            loss = cfg.body_db * min(bodies, cfg.body_cap)
            if (pa[0] < wall_x) != (pb[0] < wall_x):
                loss += cfg.wall_db
            shadow[(a, b)] = rng.gauss(0, cfg.shadow_sigma)
            mean = cfg.A - 10 * cfg.n * math.log10(d) - loss + shadow[(a, b)]
            for x, y in ((a, b), (b, a)):
                r = mean + rng.gauss(0, cfg.dir_sigma) + cfg.models[nodes[x]["model"]]
                if r > cfg.sensitivity and rng.random() < cfg.p_detect:
                    reports[x][y] = round(r + (-cfg.models[nodes[x]["model"]] if calibrate else 0))
    return reports


def trial(cfg: RoomConfig, p: Params, seed: int, calibrate: bool = True) -> dict:
    rng = random.Random(seed)
    nodes, seeds, wall_x = build_scene(cfg, rng)
    reports = synth_reports(cfg, nodes, wall_x, rng, calibrate)
    present = evaluate(seeds, reports, p)["present"]
    ins = [k for k, v in nodes.items() if v["inside"] and k not in seeds]
    outs = [k for k, v in nodes.items() if not v["inside"]]
    return {
        "inside": len(ins),
        "false_absent": sum(1 for k in ins if k not in present),
        "outside": len(outs),
        "false_present": sum(1 for k in outs if k in present),
    }


def collusion_trial(cfg: RoomConfig, p: Params, seed: int, colluders: int) -> bool:
    """Remote friend 'R' with `colluders` in-room accomplices who fabricate mutual strong edges. True if R is marked present."""
    rng = random.Random(seed)
    nodes, seeds, wall_x = build_scene(cfg, rng)
    reports = synth_reports(cfg, nodes, wall_x, rng)
    ins = [k for k, v in nodes.items() if v["inside"] and k not in seeds]
    reports["R"] = {}
    for c in rng.sample(ins, min(colluders, len(ins))):
        reports[c]["R"] = -60
        reports["R"][c] = -60
    return "R" in evaluate(seeds, reports, p)["present"]
