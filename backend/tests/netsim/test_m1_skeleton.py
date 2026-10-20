"""netsim M1: configuration, presets, provenance tags, and that the old sim.* entry points are thin wrappers."""
import json
import random
from dataclasses import fields

import pytest

import netsim.server
import sim.room
from app.services.graph import Params
from netsim import config
from netsim.scenario import build_scene, seat_of


def test_every_config_field_has_a_provenance_tag():
    names = {f.name for f in fields(config.RoomConfig)}
    assert names == set(config.TAGS), (names ^ set(config.TAGS))
    assert set(config.TAGS.values()) <= {"measured", "spec", "assumed"}
    assert "A" in config.assumed_fields() and "window_s" not in config.assumed_fields()


def test_protocol_defaults_are_tagged_spec_and_read_from_the_code():
    from sim import protocol as P
    c = config.RoomConfig()
    assert (c.window_s, c.tail_s, c.min_samples) == (P.WINDOW_S, P.TAIL_S, P.MIN_SAMPLES)
    for k in ("window_s", "tail_s", "min_samples", "sample_cap", "airtime_ms"):
        assert config.TAGS[k] == "spec"


def test_presets():
    assert config.load("class93").students == 93
    assert config.load("class20").students == 20
    lab = config.load("lab6")
    assert lab.students == 6 and lab.capacity >= 6
    rng = random.Random(1)
    nodes, seeds, _ = build_scene(lab, rng)
    assert sum(1 for v in nodes.values() if v["inside"]) == 6 and seeds
    with pytest.raises(KeyError):
        config.load("nope")


def test_overrides_from_cli_strings():
    c = config.load("class93", overrides={"door_open": "false", "window_s": "30", "ios_share": "0.5",
                                          "sample_cap": "none", "models.iphone.tx": "12"})
    assert c.door_open is False and c.window_s == 30.0 and c.ios_share == 0.5 and c.sample_cap is None
    assert c.models["iphone"]["tx"] == 12.0
    assert config.RoomConfig().models["iphone"]["tx"] == 3.0          # the default table is not mutated
    with pytest.raises(KeyError):
        config.apply(config.RoomConfig(), {"no_such_field": 1})
    with pytest.raises(ValueError):
        config.apply(config.RoomConfig(), {"door_open": "maybe"})


def test_toml_file_overrides_preset(tmp_path):
    f = tmp_path / "mine.toml"
    f.write_text("students = 35\nn = 2.6\n", encoding="utf-8")
    c = config.load("class93", toml=f)
    assert c.students == 35 and c.n == 2.6


def test_old_entry_points_are_the_netsim_ones():
    assert sim.room.trial is netsim.server.trial and sim.room.RoomConfig is config.RoomConfig


def test_same_seed_gives_identical_results():
    cfg = config.load("class60")
    a = [netsim.server.trial(cfg, Params(), s) for s in range(3)]
    b = [netsim.server.trial(cfg, Params(), s) for s in range(3)]
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_seat_of_covers_every_seated_phone():
    cfg = config.load("class93")
    nodes, _, _ = build_scene(cfg, random.Random(4))
    seats = seat_of(nodes, cfg)
    assert set(seats) == {k for k, v in nodes.items() if v["inside"]}
    assert {c for c, _ in seats.values()} <= {0, 1, 2} and {r for _, r in seats.values()} <= set(range(8))
