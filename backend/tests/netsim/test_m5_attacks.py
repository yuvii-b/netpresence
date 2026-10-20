"""netsim M5: attacks on the roll call and the co-location (relay/Sybil) defence."""
import time
from dataclasses import replace

import numpy as np
import pytest

from app.services.graph import Params, adaptive_edge_m, colocated_pairs, evaluate
from netsim import attacks
from netsim.config import load


def _p(n, **kw):
    return Params(max_edge_m=adaptive_edge_m(n), **kw)


def _agg(cfg, p, seeds, relays=1):
    rs = [attacks.relay_trial(cfg, p, s, relays) for s in seeds]
    return {k: sum(r[k] for r in rs) for k in rs[0]}


def test_relay_with_one_accomplice_beats_k2_without_the_defence():
    # the gap found while planning: one in-room accomplice rebroadcasting an absent friend's id gives the friend a full set
    # of honest witnesses. This is the baseline the defence has to beat.
    cfg = load("class93")
    a = _agg(cfg, _p(93, colocation_db=0.0), range(20))
    assert a["relay_admitted"] >= 0.8 * a["relays"]


@pytest.mark.parametrize("name", ["class93", "class60"])
def test_colocation_flags_relays_and_leaves_honest_students_alone(name):
    cfg = load(name)
    n = cfg.students
    a = _agg(cfg, _p(n), range(60))
    assert a["relay_flagged"] >= 0.95 * a["relays"], a
    assert a["relay_admitted"] <= 0.03 * a["relays"], a          # the few it misses are relays heard by < 6 common observers
    assert a["honest_flagged"] <= 0.01 * a["honest"], a
    assert a["honest_absent"] <= 0.03 * a["honest"], a          # and the defence costs no accuracy


def test_relay_is_flagged_with_correlated_shadowing_too():
    cfg = replace(load("class93"), shadow_model="gudmundson")
    a = _agg(cfg, _p(93), range(30))
    assert a["relay_flagged"] >= 0.95 * a["relays"] and a["honest_flagged"] <= 0.01 * a["honest"], a


def test_several_relays_in_one_class():
    a = _agg(load("class93"), _p(93), range(20), relays=5)
    assert a["relay_flagged"] >= 0.95 * a["relays"] and a["relay_admitted"] <= 0.03 * a["relays"], a


def test_relay_also_works_over_the_packet_level_link_layer():
    cfg = replace(load("class60"), ble_mode="des")
    a = _agg(cfg, _p(60), range(6))
    assert a["relay_flagged"] >= 0.8 * a["relays"] and a["honest_flagged"] <= 0.02 * a["honest"], a


def test_a_different_tx_power_does_not_hide_a_relay():
    # robust spread is computed on differences with the median removed, so a constant dB offset between the two ids is ignored
    rep = {f"o{i}": {"A": -60.0 - i % 7, "F": -60.0 - i % 7 - 9.0 + (i % 3) * 0.5} for i in range(20)}
    pairs = colocated_pairs(rep, Params())
    assert [(u, v) for u, v, *_ in pairs] == [("A", "F")]


def test_colocation_ignores_pairs_with_too_few_common_observers():
    rep = {f"o{i}": {"A": -60.0, "F": -60.0} for i in range(4)}
    assert colocated_pairs(rep, Params()) == []
    assert colocated_pairs(rep, Params(colocation_min_obs=3)) != []


def test_a_phone_behind_a_wall_is_not_mistaken_for_a_relay():
    # a corridor phone is an attenuated copy of the wall-side students but is heard by only a few of A's observers
    rep = {f"o{i}": {"A": -55.0 - i, **({"W": -67.0 - i} if i < 8 else {})} for i in range(30)}
    assert colocated_pairs(rep, Params()) == []


def test_lying_observers_cannot_flag_an_honest_pair():
    honest = {f"o{i}": {"A": -55.0 - i, "B": -70.0 + (i * 7) % 11} for i in range(30)}
    assert colocated_pairs(honest, Params()) == []
    lied = {o: dict(seen) for o, seen in honest.items()}
    for i in range(3):                                   # three observers copy A's reading into B: 10% of 30 is not enough
        lied[f"o{i}"]["B"] = lied[f"o{i}"]["A"]
    assert colocated_pairs(lied, Params()) == []


def test_seeds_are_never_flagged():
    rep = {f"o{i}": {"S": -60.0 - i % 5, "T": -60.0 - i % 5} for i in range(15)}
    res = evaluate(["S"], {**rep, "S": {f"o{i}": -60.0 for i in range(15)}}, Params())
    assert "S" not in res["colocated"] and "T" in res["colocated"]


def test_colocation_costs_little_time():
    cfg = load("class93")
    from random import Random
    from netsim.ble_fast import synth_reports
    from netsim.scenario import build_scene
    rng = Random(1)
    nodes, seeds, wall = build_scene(cfg, rng)
    rep = synth_reports(cfg, nodes, wall, rng)
    t = time.perf_counter()
    for _ in range(5):
        colocated_pairs(rep, Params())
    assert (time.perf_counter() - t) / 5 < 0.1               # plan: stays well under 50-100 ms at ~100 phones


def test_forger_without_reverse_readings_is_never_admitted():
    cfg = load("class60")
    assert not any(attacks.forger_trial(cfg, _p(60), s) for s in range(20))


def test_collusion_succeeds_exactly_when_accomplices_reach_k():
    cfg = load("class60")
    for c, expect in ((0, False), (1, False), (2, True), (3, True)):
        got = sum(attacks.collusion_trial(cfg, _p(60), s, c) for s in range(10))
        assert (got >= 8) if expect else (got <= 1), (c, got)


def test_rssi_inflation_cannot_get_a_corridor_phone_in():
    cfg = replace(load("class60"), door_open=False)
    for x in (0, 10, 20):
        rs = [attacks.inflation_trial(cfg, _p(60), s, x) for s in range(10)]
        assert not any(r["liar_admitted"] for r in rs), x
        assert sum(r["false_absent"] for r in rs) <= 0.03 * sum(r["inside"] for r in rs), x
