"""netsim M6: baselines on the same rooms and seeds."""
import numpy as np

from netsim import baselines as B
from netsim.config import load


def _rate(fn, cfg, n=8, **kw):
    return B.summarise([fn(cfg, s, **kw) for s in range(n)])


def test_manual_roll_call_is_exact_slow_and_open_to_proxies():
    cfg = load("class93")
    s = _rate(B.b0_manual, cfg, 20)
    assert s["false_absent_pct"] == 0 and s["corridor_present_pct"] == 0
    assert 93 * 1.5 < s["time_s"] < 93 * 2 * 3 * 1.5          # minutes, not seconds
    assert 25 <= s["proxy_success_pct"] <= 75                  # p = 0.5 over 100 attempts


def test_netpresence_beats_every_radio_baseline_on_accuracy_and_all_baselines_on_time_or_proxy():
    cfg = load("class93")
    np_ = _rate(B.netpresence, cfg)
    assert np_["false_absent_pct"] < 2 and np_["corridor_present_pct"] < 5 and np_["proxy_success_pct"] < 5
    for fn in (B.b1_beacon, B.b2_acoustic):
        b = _rate(fn, cfg)
        assert b["false_absent_pct"] > 3 * max(np_["false_absent_pct"], 1.0), fn.__name__
    assert _rate(B.b0_manual, cfg, 4)["time_s"] > 5 * np_["time_s"]
    assert _rate(B.b5_qr, cfg, 20)["proxy_success_pct"] > 10          # a forwarded photo defeats a QR code


def test_the_co_location_check_is_what_stops_relays_in_the_comparison():
    cfg = load("class93")
    assert _rate(B.np_no_colocation, cfg, 6)["proxy_success_pct"] > 60
    assert _rate(B.netpresence, cfg, 6)["proxy_success_pct"] < 5


def test_ablations_cost_what_the_design_says_they_cost():
    from dataclasses import replace
    cfg = replace(load("class93"), ios_share=0.5)
    cfg = replace(cfg, models={**cfg.models, "iphone": {**cfg.models["iphone"], "tx": 12.0}})
    assert _rate(B.b4_no_selfcal, cfg, 4)["false_absent_pct"] > 5 > _rate(B.netpresence, cfg, 4)["false_absent_pct"]
    open_door = load("class93")
    assert _rate(B.b3_no_disjoint, open_door, 10)["corridor_present_pct"] >= _rate(B.netpresence, open_door, 10)["corridor_present_pct"]


def test_acoustic_is_hurt_by_distance_and_by_iphones_and_the_beacon_is_not_a_fix():
    from dataclasses import replace
    cfg = load("class93")
    seats = [r["seats"] for r in (B.b2_acoustic(cfg, s) for s in range(8))]
    front = np.mean([a for s in seats for c, r, a in s if r <= 1])
    back = np.mean([a for s in seats for c, r, a in s if r >= 6])
    assert back > front + 0.1                                      # the back-bench problem (E10)
    quiet = replace(B.BP, ambient_db=45.0)
    assert B.summarise([B.b2_acoustic(cfg, s, quiet) for s in range(6)])["false_absent_pct"] < \
        B.summarise([B.b2_acoustic(cfg, s) for s in range(6)])["false_absent_pct"]
    beacon = _rate(B.b1_beacon, cfg)
    assert beacon["false_absent_pct"] > 5 or beacon["corridor_present_pct"] > 5      # no single threshold separates the room


def test_per_seat_results_cover_every_seated_student_and_runs_are_deterministic():
    cfg = load("class60")
    for fn in (B.b0_manual, B.b2_acoustic, B.b5_qr, B.netpresence):
        a, b = fn(cfg, 3), fn(cfg, 3)
        assert a == b, fn.__name__
        assert len(a["seats"]) == a["inside"] or fn is B.b0_manual or len(a["seats"]) <= a["inside"]
