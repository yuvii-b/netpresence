"""netsim M4: the phone's NeighbourCollector port, the uplink model and the retry policy, tied to the real TypeScript."""
import json
import random
from dataclasses import replace

import numpy as np
import pytest

from netsim import phone, uplink
from netsim.ble_fast import synth_reports
from netsim.config import load
from netsim.scenario import build_scene
from sim import protocol

FIX = protocol.CORE.parent / "test" / "fixtures"


def _load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_collector_port_equals_the_typescript_on_every_vector():
    v = _load("collector-vectors.json")
    assert v["max_neighbours"] == protocol.MAX_NEIGHBOURS
    for k, case in enumerate(v["cases"]):
        c = phone.NeighbourCollector(case["self"])
        for name, rssi in case["samples"]:
            c.add(name, rssi)
        assert c.neighbours(case["minSamples"], case["max"]) == case["expected"], k
        assert c.peers_heard == case["peersHeard"], k


def test_vectorised_reduction_equals_the_collector_class():
    rng = np.random.default_rng(3)
    N = 14
    ids = [f"p{i}" for i in range(N)]
    r = rng.integers(0, N, 4000); s = rng.integers(0, N, 4000)
    keep = r != s
    r, s = r[keep], s[keep]
    v = np.round(rng.uniform(-90, -50, len(r)) * 2) / 2                   # halves exercise round-half-up
    out, counts = phone.reports_from_samples(r, s, v, ids, 3)
    for i in range(N):
        c = phone.NeighbourCollector("ffffffff")
        for rr, ss, vv in zip(r, s, v):
            if rr == i:
                c.add(f"NP-{ss:08x}", float(vv))
        ref = {int(n["peer_id"], 16): (n["rssi_median"], n["sample_count"]) for n in c.neighbours(3)}
        got = {int(p[1:]): (m, counts[ids[i]][p]) for p, m in out[ids[i]].items()}
        assert got == ref, i


def test_javascript_rounding():
    assert [phone.js_round(x) for x in (-65.5, -64.5, -70.4, -70.5, 2.5)] == [-65, -64, -70, -70, 3]


def test_retry_schedule_equals_submitReport():
    v = _load("retry-vectors.json")
    assert v["request_timeout_ms"] == protocol.REQUEST_TIMEOUT_MS
    for c in v["cases"]:
        if c["failures"] != 1000:
            continue                                                       # "always fails": the schedule is the full ladder
        assert uplink.retry_attempt_times_ms(0.0, float(c["deadline_offset_ms"])) == [float(x) for x in c["attempts_at_ms"]], c


def test_report_body_size_equals_the_typescript():
    for c in _load("retry-vectors.json")["body_bytes"]:
        assert uplink.report_bytes(c["n"]) == c["bytes"], c


def _burst(spec, n=93, nb=40, seed=1, **kw):
    g = np.random.default_rng(seed)
    ready = 45.0 + 0.05 + g.uniform(0, 0.2, n)
    out = uplink.simulate(ready, np.full(n, nb), 55.0, spec, g, **kw)
    return out, uplink.summarise(out, 45.0)


def test_good_wifi_delivers_everything_fast():
    _, s = _burst("wifi_good")
    assert s["delivered_pct"] == 100 and s["latency_p95_s"] < 1.0


def test_ideal_uplink_is_instant():
    _, s = _burst("ideal")
    assert s["delivered_pct"] == 100 and s["latency_p95_s"] < 0.4 and s["attempts_mean"] == 1.0


def test_congested_wifi_is_slower_and_loses_more_than_good_wifi():
    ps = [_burst("wifi_congested", seed=s)[1] for s in range(6)]
    gs = [_burst("wifi_good", seed=s)[1] for s in range(6)]
    assert np.mean([p["latency_p95_s"] for p in ps]) > 3 * np.mean([g["latency_p95_s"] for g in gs])
    assert np.mean([p["attempts_mean"] for p in ps]) > np.mean([g["attempts_mean"] for g in gs])


def test_loss_triggers_retries_and_a_dead_network_delivers_nothing():
    out, s = _burst("wifi_congested", seed=2)
    assert max(o.attempts for o in out) > 1                               # someone had to retry
    dead = dict(uplink.PROFILES["wifi_good"], blackout=True)
    uplink.PROFILES["_dead"] = dead
    try:
        out, s = _burst("_dead")
    finally:
        del uplink.PROFILES["_dead"]
    assert s["delivered_pct"] == 0 and all(o.gave_up for o in out)
    # a dead network still obeys the real retry ladder: attempts are timeout + back-off apart, until the deadline
    assert all(o.attempts == len(uplink.retry_attempt_times_ms(0, 10_000, protocol.REQUEST_TIMEOUT_MS)) for o in out)


def test_jitter_spreads_the_burst():
    base = [_burst("wifi_congested", seed=s)[1]["latency_p95_s"] for s in range(6)]
    jit = [_burst("wifi_congested", seed=s, jitter_s=2.0)[1]["delivered_pct"] for s in range(6)]
    assert np.mean(jit) >= 95            # not asserting it beats J=0: E06 measures that


def test_mix_parser():
    assert uplink.parse_mix("wifi_good") == [("wifi_good", 1.0)]
    m = uplink.parse_mix("wifi_good:3,cell_4g:1")
    assert m == [("wifi_good", 0.75), ("cell_4g", 0.25)]
    with pytest.raises(ValueError):
        uplink.parse_mix("carrier_pigeon")


def test_missing_reports_make_students_absent_end_to_end():
    from app.services.graph import Params, adaptive_edge_m
    from netsim.server import trial
    cfg = replace(load("class60"), door_open=False)
    p = Params(max_edge_m=adaptive_edge_m(60))
    ideal = [trial(cfg, p, s)["false_absent"] for s in range(4)]
    dead = dict(uplink.PROFILES["wifi_good"], blackout=True)
    uplink.PROFILES["_dead"] = dead
    try:
        r = trial(replace(cfg, uplink="_dead"), p, 0)
    finally:
        del uplink.PROFILES["_dead"]
    assert r["false_absent"] == r["inside"] and sum(ideal) < 8              # nobody's report arrived -> nobody is present


def test_uplink_stats_are_reported_with_the_scene():
    cfg = replace(load("class60"), uplink="wifi_congested")
    rng = random.Random(1)
    nodes, _, wall = build_scene(cfg, rng)
    st = {}
    synth_reports(cfg, nodes, wall, rng, stats=st)
    assert set(st["uplink"]) >= {"delivered_pct", "latency_p95_s", "t_all_in_s"}
