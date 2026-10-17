"""Room geometry, people and phones: who sits where, which phone each one has, where the wall and door are."""
from __future__ import annotations

import random

from netsim.config import RoomConfig


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
    weights = list(cfg.model_mix)
    if cfg.ios_share is not None:
        ios = [m for m in names if cfg.models[m]["platform"] == "ios"]
        andr = [m for m in names if m not in ios]
        aw = sum(w for m, w in zip(names, weights) if m in andr) or 1.0
        weights = [(cfg.ios_share / len(ios)) if m in ios else (1 - cfg.ios_share) * w / aw
                   for m, w in zip(names, weights)]
    for i, pos in enumerate(occupied):
        nodes[f"in{i}"] = {"pos": pos, "inside": True, "model": rng.choices(names, weights)[0]}
    for i, pos in enumerate(outside):
        nodes[f"out{i}"] = {"pos": pos, "inside": False, "model": rng.choices(names, weights)[0]}
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


def seat_of(nodes: dict, cfg: RoomConfig) -> dict[str, tuple[int, int]]:
    """phone -> (bench column, bench row) for every seated phone, so results can be broken down per seat (E10)."""
    if cfg.layout != "bench":
        return {}
    meta = {(x, y): (bc, br) for x, y, bc, br in _bench_seats(cfg)}
    return {k: meta[v["pos"]] for k, v in nodes.items() if v["inside"] and v["pos"] in meta}


def platforms(cfg: RoomConfig, nodes: dict) -> dict[str, str]:
    """phone -> platform, what the server derives from each enrolled model string."""
    return {k: cfg.models[v["model"]]["platform"] for k, v in nodes.items()}


def link_budget(cfg: RoomConfig, model: str) -> float:
    """rx + tx of a phone model: what the server's per-model calibration offset removes (offset = -link_budget)."""
    m = cfg.models[model]
    return m["rx"] + m["tx"]
