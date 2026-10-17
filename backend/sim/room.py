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
    # layout="bench": Indian-classroom style - bench COLUMNS facing the front, several students per bench,
    # aisles between bench columns. layout="grid": uniform seat grid (rows x cols), kept for comparison.
    layout: str = "bench"
    bench_cols: int = 3           # columns of benches (left / middle / right)
    bench_rows: int = 8           # benches front -> back in each column: 3 x 8 x 4 = 96 seats
    seats_per_bench: int = 4
    capacity: int = 93            # the room never holds more than this many students
    students: int | None = None   # exact head-count to seat (<= capacity); None = use `occupancy`
    seat_pitch: float = 0.5       # m between students sharing a bench (shoulder to shoulder)
    aisle: float = 0.8            # m gap between bench columns
    bench_pitch_y: float = 1.1    # m between consecutive benches (bench + legroom)
    seed_col: int | None = None   # which bench column's FRONT bench the teacher verifies (None = middle)
    fill: str = "random"          # "random": each seat taken with prob=occupancy; "column": fill column by column, front first
    door_open: bool = True        # the door is an opening in the side wall: no wall loss along it
    door_width: float = 1.0
    rows: int = 6                 # grid layout only
    cols: int = 10
    pitch_x: float = 0.9
    pitch_y: float = 1.2
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
    n_seeds: int = 4              # grid layout; the bench layout verifies the whole front bench


def _seg_point_dist(p, a, b):
    ax, ay = a; bx, by = b; px, py = p
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _bench_seats(cfg: RoomConfig):
    """Seat coordinates as (x, y, bench_col, bench_row). y grows toward the back wall (teacher at y=0)."""
    bench_w = cfg.seats_per_bench * cfg.seat_pitch
    seats = []
    for bc in range(cfg.bench_cols):
        x0 = bc * (bench_w + cfg.aisle)
        for br in range(cfg.bench_rows):
            for k in range(cfg.seats_per_bench):
                seats.append((x0 + (k + 0.5) * cfg.seat_pitch, br * cfg.bench_pitch_y, bc, br))
    return seats


def build_scene(cfg: RoomConfig, rng: random.Random):
    if cfg.layout == "bench":
        full = _bench_seats(cfg)
        seats = [(x, y) for x, y, _, _ in full]
        meta = {(x, y): (bc, br) for x, y, bc, br in full}
        if cfg.students is not None and cfg.students > cfg.capacity:
            raise ValueError(f"room capacity is {cfg.capacity}, asked to seat {cfg.students}")
        n_seat = cfg.students if cfg.students is not None else round(cfg.occupancy * len(seats))
        n_seat = min(n_seat, cfg.capacity, len(seats))
        if cfg.fill == "column":      # column-major, front first, until the head-count is seated
            order = sorted(full, key=lambda t: (t[2], t[3], t[0]))
            occupied = [(x, y) for x, y, _, _ in order[:n_seat]]
        elif cfg.students is not None:
            occupied = rng.sample(seats, n_seat)
        else:
            occupied = [s for s in seats if rng.random() < cfg.occupancy]
            if len(occupied) > cfg.capacity:
                occupied = rng.sample(occupied, cfg.capacity)
        width = cfg.bench_cols * cfg.seats_per_bench * cfg.seat_pitch + (cfg.bench_cols - 1) * cfg.aisle
        depth = (cfg.bench_rows - 1) * cfg.bench_pitch_y
    else:
        seats = [(c * cfg.pitch_x, r * cfg.pitch_y) for r in range(cfg.rows) for c in range(cfg.cols)]
        occupied = [s for s in seats if rng.random() < cfg.occupancy]
        meta = {}
        width = (cfg.cols - 1) * cfg.pitch_x
        depth = (cfg.rows - 1) * cfg.pitch_y
    wall_x = width + 0.6                      # side wall with the door near the back
    outside = [(wall_x + rng.uniform(0.8, 3.0), rng.uniform(-0.5, depth + 0.5)) for _ in range(cfg.n_outside)]
    nodes = {}
    names = list(cfg.models)
    for i, pos in enumerate(occupied):
        nodes[f"in{i}"] = {"pos": pos, "inside": True, "model": rng.choices(names, cfg.model_mix)[0]}
    for i, pos in enumerate(outside):
        nodes[f"out{i}"] = {"pos": pos, "inside": False, "model": rng.choices(names, cfg.model_mix)[0]}
    if cfg.layout == "bench":
        col = cfg.bench_cols // 2 if cfg.seed_col is None else cfg.seed_col
        seeds = [k for k, v in nodes.items() if v["inside"] and meta[v["pos"]] == (col, 0)]
        if not seeds:                          # empty front bench: fall back to the nearest-to-teacher students
            seeds = sorted((k for k, v in nodes.items() if v["inside"]), key=lambda k: nodes[k]["pos"][1])[: cfg.seats_per_bench]
    else:
        seeds = sorted((k for k, v in nodes.items() if v["inside"]),
                       key=lambda k: (nodes[k]["pos"][1], nodes[k]["pos"][0]))[: cfg.n_seeds]
    door = (depth - cfg.door_width + 0.5, depth + 0.5) if cfg.door_open else None   # opening at the back corner
    return nodes, seeds, (wall_x, door)


def synth_reports(cfg: RoomConfig, nodes: dict, wall: tuple, rng: random.Random, calibrate: bool = True):
    wall_x, door = wall
    ids = list(nodes)
    inside_pos = [v["pos"] for v in nodes.values() if v["inside"]]
    r_body = cfg.body_radius
    shadow, reports = {}, {k: {} for k in ids}
    for ai, a in enumerate(ids):
        for b in ids[ai + 1:]:
            pa, pb = nodes[a]["pos"], nodes[b]["pos"]
            d = max(0.3, math.dist(pa, pb))
            x0, x1 = (pa[0], pb[0]) if pa[0] < pb[0] else (pb[0], pa[0])
            y0, y1 = (pa[1], pb[1]) if pa[1] < pb[1] else (pb[1], pa[1])
            x0 -= r_body; x1 += r_body; y0 -= r_body; y1 += r_body
            bodies = 0
            for q in inside_pos:   # bounding-box reject first: most seats are nowhere near the a-b segment
                if q[0] < x0 or q[0] > x1 or q[1] < y0 or q[1] > y1 or q == pa or q == pb:
                    continue
                if _seg_point_dist(q, pa, pb) < r_body:
                    bodies += 1
            loss = cfg.body_db * min(bodies, cfg.body_cap)
            if (pa[0] < wall_x) != (pb[0] < wall_x):
                t = (wall_x - pa[0]) / (pb[0] - pa[0])
                y_cross = pa[1] + t * (pb[1] - pa[1])
                if not (door and door[0] <= y_cross <= door[1]):     # open doorway: no wall attenuation
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
    nodes, seeds, wall = build_scene(cfg, rng)
    reports = synth_reports(cfg, nodes, wall, rng, calibrate)
    present = evaluate(seeds, reports, p)["present"]
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
    }


def collusion_trial(cfg: RoomConfig, p: Params, seed: int, colluders: int) -> bool:
    """Remote friend 'R' with `colluders` in-room accomplices who fabricate mutual strong edges. True if R is marked present."""
    rng = random.Random(seed)
    nodes, seeds, wall = build_scene(cfg, rng)
    reports = synth_reports(cfg, nodes, wall, rng)
    ins = [k for k, v in nodes.items() if v["inside"] and k not in seeds]
    reports["R"] = {}
    for c in rng.sample(ins, min(colluders, len(ins))):
        reports[c]["R"] = -60
        reports["R"][c] = -60
    return "R" in evaluate(seeds, reports, p)["present"]
