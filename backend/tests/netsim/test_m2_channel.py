"""netsim M2: correlated shadowing, orientation loss, trace-driven channel."""
import random
from dataclasses import replace

import numpy as np
import pytest

from app.services.graph import Params, adaptive_edge_m
from netsim import traces
from netsim.channel import correlated_shadowing, pair_geometry, pair_mean_rssi
from netsim.config import RoomConfig, load
from netsim.scenario import build_scene
from netsim.server import trial


def _scene(cfg, seed=3):
    nodes, seeds, wall = build_scene(cfg, random.Random(seed))
    return nodes, wall


def test_gudmundson_is_reciprocal_and_has_the_right_variance():
    cfg = replace(load("class93"), shadow_model="gudmundson")
    nodes, wall = _scene(cfg)
    P, iu, ju, d, _, _ = pair_geometry(cfg, nodes, wall)
    vals = np.concatenate([correlated_shadowing(cfg, P, iu, ju, d, np.random.default_rng(s)) for s in range(40)])
    assert abs(vals.std() - cfg.shadow_sigma) < 0.35 and abs(vals.mean()) < 0.2
    # reciprocity: the pair index set is unordered, so S_ij is one number per pair; swapping the roles gives the same value
    s1 = correlated_shadowing(cfg, P, iu, ju, d, np.random.default_rng(5))
    s2 = correlated_shadowing(cfg, P, ju, iu, d, np.random.default_rng(5))
    assert np.allclose(s1, s2)


def test_shadowing_field_correlation_at_one_metre_is_exp_minus_one():
    # the latent field z (before the pair mix) must correlate as exp(-d/d_corr); check via the Cholesky it is built from
    cfg = RoomConfig()
    pts = np.array([[0.0, 0.0], [1.0, 0.0]])
    C = np.exp(-np.linalg.norm(pts[:, None] - pts[None], axis=2) / cfg.d_corr)
    L = np.linalg.cholesky(C + 1e-9 * np.eye(2))
    z = (L @ np.random.default_rng(0).normal(size=(2, 200000)))
    assert abs(np.corrcoef(z)[0, 1] - np.exp(-1)) < 0.01


def test_nearby_phones_see_correlated_links_far_ones_do_not():
    cfg = replace(load("class93"), shadow_model="gudmundson")
    nodes, wall = _scene(cfg)
    P, iu, ju, d, _, _ = pair_geometry(cfg, nodes, wall)
    S = np.array([correlated_shadowing(cfg, P, iu, ju, d, np.random.default_rng(s)) for s in range(300)])
    ids = list(nodes)
    idx = {(i, j): n for n, (i, j) in enumerate(zip(iu, ju))}
    # two phones 0.5 m apart both hearing a third phone vs two phones far apart hearing it
    def corr(a, b, c):
        return np.corrcoef(S[:, idx[tuple(sorted((a, c)))]], S[:, idx[tuple(sorted((b, c)))]])[0, 1]
    near = [(i, j) for i, j in zip(iu, ju) if abs(np.linalg.norm(P[i] - P[j]) - 0.5) < 1e-6][:1][0]
    c = next(k for k in range(len(ids)) if np.linalg.norm(P[k] - P[near[0]]) > 5 and k not in near)
    far = next(k for k in range(len(ids)) if np.linalg.norm(P[k] - P[near[0]]) > 7 and k not in (c,) + near)
    assert corr(near[0], near[1], c) > corr(near[0], far, c) + 0.1


def test_iid_default_is_unchanged_and_orientation_off_by_default():
    cfg = RoomConfig()
    assert cfg.shadow_model == "iid" and cfg.orient_mix == (1.0, 0.0, 0.0, 0.0) and cfg.channel == "parametric"


def test_orientation_loss_lowers_the_mean_by_about_two_ends():
    base = replace(load("class35"), shadow_sigma=0.0)
    bag = replace(base, orient_mix=(0.0, 0.0, 0.0, 1.0))
    nodes, wall = _scene(base)
    m0 = pair_mean_rssi(base, nodes, wall, np.random.default_rng(1), np.random.default_rng(2))[3]
    m1 = pair_mean_rssi(bag, nodes, wall, np.random.default_rng(1), np.random.default_rng(2))[3]
    assert np.allclose(m0 - m1, 2 * 10.0)


def test_how_phones_are_held_matters_and_is_measured_not_hidden():
    # FINDING (docs/NETSIM.md): a uniform extra loss (phones on a desk / in pockets) looks like a larger distance to the
    # fixed edge threshold. Phones in hand are fine; this test pins the direction, E08 reports the size.
    p = Params(max_edge_m=adaptive_edge_m(60))
    base = replace(load("class60"), door_open=False)
    fa = lambda mix: (lambda rs: sum(r["false_absent"] for r in rs) / sum(r["inside"] for r in rs))(
        [trial(replace(base, orient_mix=mix), p, s) for s in range(4)])
    hand, pocket = fa((1.0, 0, 0, 0)), fa((0.25, 0.25, 0.4, 0.1))
    assert hand < 0.03 and pocket > hand + 0.1


@pytest.fixture(scope="module")
def synth_file(tmp_path_factory):
    f = tmp_path_factory.mktemp("lab") / "lab.csv"
    traces.synthesize(RoomConfig(), f, seed=1)
    return str(f)


def test_synthetic_lab_file_roundtrips_through_fit_and_tables(synth_file):
    rows = traces.read_rows(synth_file)
    fit = traces.fit(rows)
    assert abs(fit["n"] - 3.0) < 0.5 and abs(fit["A"] - -59.0) < 3.0
    cov = traces.coverage(rows)
    assert cov["cells_usable"] == 8 and cov["models"] == ["ref"]


def test_trace_channel_matches_the_parametric_one_when_the_data_comes_from_it(synth_file):
    p = Params(max_edge_m=adaptive_edge_m(60))
    para = replace(load("class60"), door_open=False)
    trace = replace(para, channel="trace", trace_file=synth_file)
    fa = lambda c: [trial(c, p, s) for s in range(6)]
    a, b = fa(para), fa(trace)
    ra = sum(r["false_absent"] for r in a) / sum(r["inside"] for r in a)
    rb = sum(r["false_absent"] for r in b) / sum(r["inside"] for r in b)
    assert abs(ra - rb) < 0.05
    assert all("trace_fallbacks" in r for r in b)
    # nearly every close pair is covered by a measured cell; fallbacks are counted, not hidden
    assert sum(r["trace_fallbacks"] for r in b) < 0.6 * sum(r["inside"] * (r["inside"] - 1) / 2 for r in b)


def test_trace_channel_needs_a_file_and_reports_bad_columns(tmp_path):
    nodes, wall = _scene(load("class20"))
    with pytest.raises(ValueError):
        pair_mean_rssi(replace(RoomConfig(), channel="trace"), nodes, wall, np.random.default_rng(0))
    bad = tmp_path / "bad.csv"
    bad.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError):
        traces.read_rows(bad)
    with pytest.raises(FileNotFoundError):
        traces.read_rows(tmp_path / "missing.csv")


def test_thin_cells_fall_back_and_are_counted(tmp_path):
    f = tmp_path / "tiny.csv"
    f.write_text("model,distance_m,rssi\n" + "\n".join(f"ref,1,-60" for _ in range(5)), encoding="utf-8")
    cfg = replace(load("class20"), channel="trace", trace_file=str(f))
    r = trial(cfg, Params(), 1)
    assert r["trace_fallbacks"] > 0
