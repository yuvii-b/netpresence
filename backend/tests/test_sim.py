from app.services.graph import Params
from sim.room import RoomConfig, collusion_trial, trial


def test_default_params_cover_room_and_block_wall_leak():
    cfg, p = RoomConfig(), Params()
    res = [trial(cfg, p, s) for s in range(40)]
    fa = sum(r["false_absent"] for r in res) / sum(r["inside"] for r in res)
    fp = sum(r["false_present"] for r in res) / sum(r["outside"] for r in res)
    assert fa < 0.02 and fp < 0.15      # measured: ~0.3% and ~8% at 12 dB wall loss


def test_collusion_threshold_is_exactly_k():
    cfg, p = RoomConfig(), Params(k=2)
    assert not any(collusion_trial(cfg, p, s, 1) for s in range(6))
    assert all(collusion_trial(cfg, p, s, 2) for s in range(6))
