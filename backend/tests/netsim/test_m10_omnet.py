"""M10: the OMNeT++ model. The export and the engine bridge are always tested; the simulation itself runs when the model is built."""
import csv
import random
from dataclasses import replace

import numpy as np
import pytest

from app.services.graph import Params, adaptive_edge_m, evaluate
from netsim import config, omnet_eval, omnet_export, omnet_run
from netsim.ble_fast import synth_reports
from netsim.scenario import build_scene, platforms
from sim import protocol


def _rows(p):
    return list(csv.DictReader(open(p, newline="", encoding="ascii")))


def test_export_scene_files_and_protocol_constants(tmp_path):
    cfg = config.load("class35")
    omnet_export.export(cfg, 3, tmp_path)
    prm = dict(line.split(",", 1) for line in (tmp_path / "params.csv").read_text().splitlines() if line and not line.startswith("#"))
    assert float(prm["window_s"]) == protocol.WINDOW_S and float(prm["tail_s"]) == protocol.TAIL_S and float(prm["grace_s"]) == protocol.GRACE_S
    assert int(prm["min_samples"]) == protocol.MIN_SAMPLES and int(prm["max_neighbours"]) == protocol.MAX_NEIGHBOURS
    assert int(prm["retry_start_ms"]) == protocol.RETRY_START_MS and int(prm["request_timeout_ms"]) == protocol.REQUEST_TIMEOUT_MS
    phones = _rows(tmp_path / "phones.csv")
    assert len(phones) == 35 + cfg.n_outside
    M = np.array([[float(x) for x in l.split(",")] for l in (tmp_path / "matrix.csv").read_text().split()])
    assert M.shape == (len(phones), len(phones)) and np.allclose(M, M.T)
    assert [r["id"] for r in _rows(tmp_path / "seeds.csv")] and len(_rows(tmp_path / "bytes.csv")) == protocol.MAX_NEIGHBOURS + 1


def test_export_is_the_same_room_as_the_python_simulator(tmp_path):
    cfg = config.load("class20")
    nodes, seeds, _, _ = omnet_export.build(cfg, 5)
    n2, s2, _ = build_scene(cfg, random.Random(5))
    assert list(nodes) == list(n2) and seeds == s2 and all(nodes[k]["pos"] == n2[k]["pos"] for k in nodes)
    assert omnet_export.build(cfg, 5)[3].tolist() == omnet_export.build(cfg, 5)[3].tolist()      # deterministic


def test_relay_export_clones_one_radio(tmp_path):
    cfg = replace(config.load("class35"), n_outside=0)
    nodes, seeds, _, M = omnet_export.build(cfg, 2, relays=2)
    ids = list(nodes)
    for f in [k for k in ids if k.startswith("F")]:
        a = nodes[f]["clone_of"]
        assert nodes[f]["pos"] == nodes[a]["pos"] and M[ids.index(f), ids.index(a)] == -200.0
        others = [i for i, k in enumerate(ids) if k not in (f, a)]
        assert np.allclose(M[ids.index(f), others], M[ids.index(a), others])


def test_engine_bridge_gives_the_real_engines_verdict(tmp_path):
    """reports.csv -> omnet_eval -> verdict.csv must equal calling evaluate() directly on the same reports."""
    cfg = replace(config.load("class35"), door_open=False)
    omnet_export.export(cfg, 1, tmp_path)
    rng = random.Random(1)
    nodes, seeds, wall = build_scene(cfg, rng)
    reports = synth_reports(cfg, nodes, wall, rng)
    with open(tmp_path / "reports.csv", "w", newline="", encoding="ascii") as f:
        w = csv.writer(f); w.writerow(["reporter", "peer", "rssi_median", "sample_count"])
        for a, seen in reports.items():
            for b, v in seen.items():
                w.writerow([a, b, v, 10])
    (tmp_path / "checkins.csv").write_text("id\n" + "".join(f"{k}\n" for k in nodes), encoding="ascii")
    (tmp_path / "reporters.csv").write_text("id\n" + "".join(f"{k}\n" for k in reports), encoding="ascii")
    omnet_eval.run(tmp_path)
    present = {l.split(",")[1] for l in (tmp_path / "verdict.csv").read_text().splitlines() if l.startswith("P,")}
    direct = evaluate(seeds, reports, Params(max_edge_m=adaptive_edge_m(len(nodes))), platforms(cfg, nodes))
    assert present == set(direct["present"]) and len(present) > 20
    assert sum(1 for l in (tmp_path / "verdict.csv").read_text().splitlines() if l.startswith("E,")) == direct["edges"]


needs_omnet = pytest.mark.skipif(not omnet_run.available(), reason="OMNeT++ model not built (omnet/README.md)")


@needs_omnet
def test_omnet_roll_call_end_to_end(tmp_path):
    cfg = replace(config.load("class35"), door_open=False)
    sc = omnet_run.run_one(cfg, 1, tmp_path)
    assert sc["inside"] > 20 and sc["pdus"] > 10000 and sc["delivered"] > 10000
    assert sc["reportsDelivered"] >= 0.95 * (sc["inside"] + sc["outside"])      # ideal uplink: everybody gets through
    assert sc["falseAbsent"] <= 0.1 * sc["inside"] and sc["falsePresent"] == 0


@needs_omnet
def test_omnet_agrees_with_the_python_simulator(tmp_path):
    """Two independent link-layer implementations on identical classrooms: aggregate false-absent within 3 pp, corridor both ~0."""
    res = omnet_run.compare("class60", 6, {"door_open": "false"})
    r = res["rows"]
    inside = sum(x["inside"] for x in r)
    far_py = 100 * sum(x["py_far"] for x in r) / inside
    far_om = 100 * sum(x["om_far"] for x in r) / inside
    assert abs(far_py - far_om) <= 3.0, (far_py, far_om)
    assert sum(x["om_fpr"] for x in r) == 0 and sum(x["py_fpr"] for x in r) == 0


@needs_omnet
def test_omnet_relay_is_detected(tmp_path):
    cfg = replace(config.load("class60"), door_open=False)
    sc = omnet_run.run_one(cfg, 1, tmp_path, relays=2)
    rows = (tmp_path / "scene" / "verdict.csv").read_text().splitlines()
    assert any(l.startswith("C,") for l in rows)           # at least one id flagged as the same radio as another
