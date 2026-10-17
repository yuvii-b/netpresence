"""netsim M3: packet-level BLE advertising channel."""
import random
from dataclasses import replace

import numpy as np
import pytest

from netsim import ble_des
from netsim.ble_fast import synth_reports
from netsim.config import RoomConfig, load
from netsim.scenario import build_scene
from sim import protocol


def _cfg(**kw):
    return replace(RoomConfig(), p_bg=(0, 0, 0), rician_k_db=40.0, ios_min_report_ms=0.0, **kw)


MODEL = {"platform": "android", "rx": 0.0, "tx": 0.0, "adv_ms": 100.0, "scan_eff": 1.0}


def test_airtime_formula_and_source():
    assert abs((1 + 4 + 2 + (6 + 21) + 3) * 8 / 1000 - protocol.ADV_AIRTIME_MS) < 1e-12
    assert abs(RoomConfig().airtime_ms - 0.296) < 1e-9


def test_advertising_events_obey_interval_and_delay_bounds():
    cfg = _cfg()
    g = np.random.default_rng(1)
    on, joined, adv = np.zeros(2), np.array([True, False]), np.array([100.0, 100.0])
    t, ch, snd = ble_des.schedule(cfg, on, joined, adv, g)
    assert set(snd) == {0}                                             # the phone that did not join sends nothing
    first = t[ch == 0]
    gaps = np.diff(first)
    assert gaps.min() >= 100.0 - 1e-9 and gaps.max() <= 100.0 + cfg.adv_delay_max_ms + 1e-9
    # 37 -> 38 -> 39 inside one event, one PDU-plus-ifs apart
    e = np.flatnonzero(ch == 0)[:5]
    for i in e:
        assert abs(t[ch == 1][t[ch == 1] > t[i]][0] - t[i] - (cfg.airtime_ms + cfg.t_ifs_adv_ms)) < 1e-9
    assert t.max() + cfg.airtime_ms <= (cfg.window_s + cfg.tail_s) * 1000


def test_overlap_pairs_are_exactly_the_pdus_closer_than_an_airtime():
    t = np.array([0.0, 0.1, 0.5, 0.6, 5.0])
    a, b = ble_des.overlaps(t, 0.296)
    assert sorted(zip(a.tolist(), b.tolist())) == [(0, 1), (1, 0), (2, 3), (3, 2)]


def _run(cfg, M, t, ch, snd, phase=(0, 0, 0), models=None):
    n = M.shape[0]
    models = models or [dict(MODEL) for _ in range(n)]
    g = np.random.default_rng(0)
    return ble_des.simulate(cfg, M, models, np.zeros(n), np.ones(n, dtype=bool), g, np.random.default_rng(1),
                            pdus=(np.array(t, float), np.array(ch), np.array(snd)), phase=phase)


def _M(ac, bc, ab=-40.0):
    M = np.full((3, 3), -200.0)
    M[0, 2] = M[2, 0] = ac; M[1, 2] = M[2, 1] = bc; M[0, 1] = M[1, 0] = ab
    return M


def _pair_series(k=300):
    """k PDUs from phone A and k from phone B that overlap pairwise on channel 0 (scanner C listens on channel 0)."""
    t = []
    for i in range(k):
        t += [10.0 * i + 0.00, 10.0 * i + 0.10]
    return t, [0] * (2 * k), [0, 1] * k


def test_overlapping_pdus_on_one_channel_collide_without_capture():
    t, ch, snd = _pair_series()
    r, s, v, st = _run(_cfg(capture=False), _M(-60, -60), t, ch, snd)
    assert len(r[r == 2]) == 0 and st["collided"] > 0


def test_capture_keeps_the_stronger_pdu_only_when_it_is_far_enough_above():
    t, ch, snd = _pair_series()
    r, s, v, st = _run(_cfg(capture=True), _M(-50, -70), t, ch, snd)          # A is 20 dB above B at the scanner
    heard = s[r == 2]
    assert (heard == 0).sum() > 250 and (heard == 1).sum() == 0
    r, s, v, st = _run(_cfg(capture=True), _M(-60, -63), t, ch, snd)          # 3 dB apart: below the 6 dB capture margin
    assert len(r[r == 2]) == 0


def test_different_channels_never_collide():
    t, ch, snd = _pair_series()
    ch = [0, 1] * 300                                                          # B moves to channel 1 (scanner is on 0)
    r, s, v, st = _run(_cfg(capture=False), _M(-60, -60), t, ch, snd)
    heard = s[r == 2]
    assert (heard == 0).sum() > 290 and st["collided"] == 0


def test_half_duplex_phone_cannot_receive_while_it_transmits():
    # B transmits on channel 1 while A sends on channel 0; B listens on channel 0 but is busy sending
    t = [10.0 * i + d for i in range(200) for d in (0.0, 0.1)]
    ch = [0, 1] * 200
    snd = [0, 1] * 200
    M = np.full((3, 3), -200.0); M[0, 1] = M[1, 0] = -50.0
    r, s, v, st = _run(_cfg(capture=False), M, t, ch, snd)
    assert len(r[r == 1]) == 0 and st["half_duplex"] > 150


def test_scanner_only_hears_the_channel_it_is_on_and_android_hops_every_interval():
    cfg = _cfg()
    M = _M(-50, -200)
    t = np.arange(0.0, 3 * 4096.0, 25.0)
    for c in range(3):
        r, s, v, st = _run(cfg, M, t, np.full(len(t), c), np.zeros(len(t), int))
        # all deliveries to C (receiver 2) fall in C's window for channel c: [c*4096, (c+1)*4096)
        idx = np.flatnonzero((np.floor(t / 4096) % 3) == c)
        assert (r == 2).sum() == len(idx)


def test_below_sensitivity_pdus_are_not_delivered():
    t, ch, snd = _pair_series(50)
    r, s, v, st = _run(_cfg(), _M(-120, -120), t, ch, snd)
    assert len(r) == 0 and st["below_sensitivity"] > 0


def test_ios_coalescing_limits_reports_per_peer():
    cfg = replace(_cfg(), ios_min_report_ms=1000.0)
    ios = {"platform": "ios", "rx": 0.0, "tx": 0.0, "adv_ms": 100.0, "scan_eff": 1.0}
    t = list(np.arange(0.0, 4000.0, 100.0))
    r, s, v, st = _run(cfg, _M(-50, -200), t, [0] * len(t), [0] * len(t), models=[dict(MODEL), dict(MODEL), ios])
    n_ios = (r == 2).sum()
    assert n_ios <= 4 and n_ios >= 1


def test_des_and_fast_agree_on_samples_per_pair_without_background():
    for n in (10, 30, 93):
        base = replace(load("class20"), students=n, door_open=False, n_outside=0, p_bg=(0, 0, 0), tap_median_s=0.0)
        ratios = []
        for seed in range(2):
            out = {}
            for mode in ("fast", "des"):
                cfg = replace(base, ble_mode=mode)
                rng = random.Random(seed)
                nodes, _, wall = build_scene(cfg, rng)
                out[mode] = synth_reports(cfg, nodes, wall, rng, with_counts=True)[1]
            both = [(out["fast"][a][b], out["des"][a][b]) for a in out["fast"] for b in out["fast"][a] if b in out["des"].get(a, {})]
            ratios.append(np.mean([y for _, y in both]) / np.mean([x for x, _ in both]))
        assert all(abs(r - 1) < 0.15 for r in ratios), (n, ratios)


def test_des_is_fast_enough_and_deterministic():
    import time
    cfg = replace(load("class93"), ble_mode="des")
    outs = []
    for _ in range(2):
        rng = random.Random(7)
        nodes, _, wall = build_scene(cfg, rng)
        t0 = time.time()
        outs.append(synth_reports(cfg, nodes, wall, rng))
        dt = time.time() - t0
    assert outs[0] == outs[1] and dt < 5.0          # plan R4: a 93-phone run in under 5 s


def test_des_end_to_end_trial_keeps_the_acceptance_level():
    from app.services.graph import Params, adaptive_edge_m
    from netsim.server import trial
    cfg = replace(load("class93"), ble_mode="des", door_open=False)
    rs = [trial(cfg, Params(max_edge_m=adaptive_edge_m(93)), s) for s in range(4)]
    assert sum(r["false_absent"] for r in rs) / sum(r["inside"] for r in rs) < 0.03
