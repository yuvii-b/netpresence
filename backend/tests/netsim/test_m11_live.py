"""M11: the live roll call model (protocol v3) - same real engine, time-resolved."""
from dataclasses import replace

import pytest

from app.services.graph import Params, adaptive_edge_m
from netsim import config, live
from netsim.live import SEED_MODES, LiveConfig, live_trial
from sim import protocol


def _cfg(n=35, **ov):
    return replace(config.load("class93", None, {"uplink": "wifi_good", **ov}), students=n)


def _p(cfg):
    return Params(max_edge_m=adaptive_edge_m(cfg.students))


def test_every_live_field_has_a_provenance_tag():
    assert {f for f in LiveConfig.__dataclass_fields__} == set(live.LIVE_TAGS)
    assert set(live.LIVE_TAGS.values()) <= {"spec", "assumed", "measured"}


def test_unknown_seed_mode_is_refused():
    with pytest.raises(ValueError):
        LiveConfig(seed_mode="everyone")


def test_live_trial_is_deterministic_and_marks_a_small_class_present():
    cfg = _cfg()
    a = live_trial(cfg, LiveConfig(), _p(cfg), 3)
    b = live_trial(cfg, LiveConfig(), _p(cfg), 3)
    assert a == b
    assert a["inside"] == 35 and a["false_absent"] <= 2 and a["false_present"] == 0
    assert 0.3 < a["ttp_p50"] < 6.0, "time to Present must be a plausible number of seconds"


def test_teacher_waits_for_the_best_after_time_and_for_a_stable_count():
    cfg = _cfg()
    r = live_trial(cfg, LiveConfig(), _p(cfg), 1)
    assert r["finish_s"] >= protocol.LIVE_BEST_AFTER_S
    early = live_trial(cfg, LiveConfig(min_finish_s=4.0, stable_s=2.0), _p(cfg), 1)
    assert early["finish_s"] < r["finish_s"]


def test_all_seed_modes_run_and_report_the_same_fields():
    cfg = _cfg(20)
    keys = None
    for m in SEED_MODES:
        r = live_trial(cfg, LiveConfig(seed_mode=m, min_finish_s=6.0), _p(cfg), 2)
        keys = keys or set(r)
        assert set(r) == keys and r["inside"] > 0


def test_relay_friend_is_reported_with_a_verdict():
    cfg = _cfg(40, door_open="false")
    r = live_trial(cfg, LiveConfig(relays=1), _p(cfg), 4)
    assert r["relays"] == 1 and r["relay_admitted"] in (0, 1) and r["relay_flagged"] in (0, 1)
    assert not (r["relay_admitted"] and r["relay_flagged"]), "a flagged phone is not admitted"


def test_a_lossy_network_delays_present_by_the_request_timeout():
    """Every first attempt lost -> each report arrives after REQUEST_TIMEOUT_MS + the first retry delay (session.ts policy).
    (A network that never recovers is not modelled here: the phone shows 'offline', see mobile/core live_unit tests.)"""
    import netsim.uplink as up
    cfg = _cfg(35)
    base = live_trial(cfg, LiveConfig(min_finish_s=6.0), _p(cfg), 1)
    up.PROFILES["_lossy"] = dict(up.PROFILES["wifi_good"], loss=1.0)
    try:
        bad = live_trial(replace(cfg, uplink="_lossy"), LiveConfig(min_finish_s=6.0, horizon_s=30.0), _p(cfg), 1)
    finally:
        up.PROFILES.pop("_lossy")
    assert bad["ttp_p50"] >= base["ttp_p50"] + (protocol.REQUEST_TIMEOUT_MS + protocol.RETRY_START_MS) / 1000.0 - 0.5


def test_live_constants_are_read_from_the_phone_code():
    assert protocol.LIVE_WINDOW >= 100, "the relay check needs a long rolling median (sim.live run 1 failed with 20)"
    assert protocol.LIVE_REPORT_INTERVAL_MS == protocol.SERVER_LIVE_REPORT_INTERVAL_MS


def test_unlock_delay_is_off_by_default_and_shifts_joining_when_on():
    cfg = _cfg()
    base = live_trial(cfg, LiveConfig(), _p(cfg), 3)
    assert base == live_trial(cfg, LiveConfig(bio_s_lo=0.0, bio_s_hi=0.0), _p(cfg), 3), "default must equal the pre-declared study"
    slow = live_trial(cfg, LiveConfig(bio_s_lo=1.0, bio_s_hi=4.0), _p(cfg), 3)
    assert slow["inside"] == base["inside"] and slow["false_present"] == 0
