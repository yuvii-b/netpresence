from app.services.graph import Params
from sim.room import RoomConfig, collusion_trial, trial


def _rates(cfg, p, n=60):
    res = [trial(cfg, p, s) for s in range(n)]
    return (sum(r["false_absent"] for r in res) / sum(r["inside"] for r in res),
            sum(r["false_present"] for r in res) / sum(r["outside"] for r in res))


def test_closed_door_blocks_corridor_completely():
    fa, fp = _rates(RoomConfig(door_open=False), Params())
    assert fa < 0.02 and fp == 0.0


def test_open_door_leak_is_small_with_disjoint_paths_and_large_without():
    cfg = RoomConfig(door_open=True)
    fa, fp = _rates(cfg, Params(independent=True))
    _, fp_loose = _rates(cfg, Params(independent=False))
    # 3x8x4 room, door open: k-witness alone leaks ~8% of corridor phones, disjoint paths ~2% (measured with the
    # sample-count radio model); leaks are bursty (a class either leaks several phones or none)
    assert fa < 0.02 and fp < 0.08
    assert fp_loose > 0.05 and fp_loose > 3 * fp


def test_sparse_room_keeps_coverage():
    fa, _ = _rates(RoomConfig(occupancy=0.6), Params())
    assert fa < 0.05                         # measured ~2%


def test_column_fill_layout_runs():
    fa, _ = _rates(RoomConfig(fill="column", occupancy=0.75), Params(), n=10)
    assert fa < 0.05


def test_collusion_threshold_is_exactly_k():
    cfg, p = RoomConfig(), Params(k=2)
    assert not any(collusion_trial(cfg, p, s, 1) for s in range(6))
    assert all(collusion_trial(cfg, p, s, 2) for s in range(6))
