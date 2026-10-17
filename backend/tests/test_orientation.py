"""The target classroom: 3 bench columns x 4 students per bench x 8 benches (96 seats), at most 93 students."""
import math
import random

import pytest

from app.services.graph import Params, adaptive_edge_m
from sim.e2e import run_scenario
from sim.orientation import BASE, adaptive
from sim.room import RoomConfig, build_scene, trial


# ---------------------------------------------------------------- layout geometry
def test_layout_is_three_columns_of_four_seat_benches():
    cfg = RoomConfig(students=93)
    nodes, seeds, (wall_x, door) = build_scene(cfg, random.Random(7))
    ins = {k: v["pos"] for k, v in nodes.items() if v["inside"]}
    assert len(ins) == 93 and cfg.bench_cols * cfg.bench_rows * cfg.seats_per_bench == 96
    xs = sorted({round(x, 2) for x, _ in ins.values()})
    # seats group into exactly 3 x-bands of 4 seat positions separated by aisles
    bands, band = [], [xs[0]]
    for x in xs[1:]:
        (band.append(x) if x - band[-1] < cfg.aisle - 1e-6 else (bands.append(band), band := [x]))
    bands.append(band)
    assert [len(b) for b in bands] == [4, 4, 4]
    aisle_gap = bands[1][0] - bands[0][-1]
    assert abs(aisle_gap - (cfg.aisle + cfg.seat_pitch)) < 1e-6         # centre-to-centre across an aisle
    ys = sorted({round(y, 2) for _, y in ins.values()})
    assert len(ys) == 8 and all(abs((b - a) - cfg.bench_pitch_y) < 1e-6 for a, b in zip(ys, ys[1:]))
    assert min(math.dist(p, q) for p in ins.values() for q in ins.values() if p != q) >= cfg.seat_pitch - 1e-9   # nobody shares a seat
    assert max(x for x, _ in ins.values()) < wall_x and door is not None


def test_capacity_is_enforced_and_93_leaves_three_empty_seats():
    with pytest.raises(ValueError):
        build_scene(RoomConfig(students=94), random.Random(1))
    nodes, _, _ = build_scene(RoomConfig(students=93), random.Random(1))
    assert sum(v["inside"] for v in nodes.values()) == 93
    # occupancy-based seating can never exceed the cap either
    for s in range(5):
        nodes, _, _ = build_scene(RoomConfig(occupancy=1.0), random.Random(s))
        assert sum(v["inside"] for v in nodes.values()) <= 93


def test_teacher_verifies_the_front_bench_of_the_chosen_column():
    for col in (0, 1, 2):
        cfg = RoomConfig(students=93, seed_col=col)
        nodes, seeds, _ = build_scene(cfg, random.Random(3))
        assert 3 <= len(seeds) <= 4
        assert {nodes[k]["pos"][1] for k in seeds} == {0.0}                       # front bench only
        bench_w = cfg.seats_per_bench * cfg.seat_pitch
        lo = col * (bench_w + cfg.aisle)
        assert all(lo <= nodes[k]["pos"][0] <= lo + bench_w for k in seeds)        # the chosen column only


def test_column_fill_seats_front_first_column_by_column():
    nodes, _, _ = build_scene(RoomConfig(students=30, fill="column"), random.Random(1))
    ins = [v["pos"] for v in nodes.values() if v["inside"]]
    assert len(ins) == 30
    assert max(x for x, _ in ins) < 4 * 0.5 + 0.01             # 30 students fit in the first column (32 seats)


# ---------------------------------------------------------------- adaptive profile
def test_adaptive_edge_threshold_profile():
    assert [adaptive_edge_m(n) for n in (101, 70, 69, 50, 49, 28)] == [2.0, 2.0, 2.5, 2.5, 3.0, 3.0]


def test_adaptive_fixes_the_sparse_room_without_hurting_the_full_one():
    def fa(n, params, seeds=range(12)):
        res = [trial(RoomConfig(students=n, door_open=False), params, s) for s in seeds]
        return sum(r["false_absent"] for r in res) / sum(r["inside"] for r in res)
    assert fa(35, Params()) > 0.15                       # fixed 2.0 m strands students in a sparse room (measured ~30%)
    assert fa(35, adaptive(35)) < 0.03                   # adaptive recovers them (measured <1%)
    assert fa(93, adaptive(93)) <= fa(93, Params()) + 0.005


# ---------------------------------------------------------------- full 93-student class through the real API
async def test_full_class_of_93_through_the_api():
    r = await run_scenario(BASE, seed=11, remote=5)
    assert r["inside"] >= 85                                           # 93 seated minus the verified front bench
    assert r["false_absent"] / r["inside"] < 0.02
    assert r["remote_present"] == 0                                    # 5 remote cheaters, none admitted
    assert r["phones"] >= 93 + 5 + 8
    assert r["seconds"] < 20                                           # check-in + 106 signed reports + close, in-process


async def test_full_class_collusion_and_headcount():
    k2 = await run_scenario(BASE, seed=12, remote=0, accomplices=2)
    k1 = await run_scenario(BASE, seed=12, remote=0, accomplices=1)
    assert (k1["friend_present"], k2["friend_present"]) == (0, 1)      # exactly k accomplices are needed
    r = await run_scenario(RoomConfig(students=93, door_open=True), seed=100, remote=0, params={"independent": False}, headcount=True)
    assert r["corridor_present"] > 0 and r["corridor_caught"] / r["corridor_present"] >= 0.5


async def test_api_matches_graph_engine_at_93_and_35_students():
    for n in (93, 35):
        cfg = RoomConfig(students=n)
        api = await run_scenario(cfg, seed=21, remote=0)
        ref = trial(cfg, adaptive(n), 21)
        assert (api["false_absent"], api["corridor_present"]) == (ref["false_absent"], ref["false_present"]), n
