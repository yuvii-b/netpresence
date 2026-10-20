"""Android + iOS: cross-platform self-calibration, its security properties, and the faster max-flow."""
import random
from dataclasses import replace

from app.services.graph import (AUTOCAL_MIN_GROUP, Params, disjoint_paths_many, evaluate, platform_of,
                                self_calibrate)
from sim.room import RoomConfig, build_scene, platforms, synth_reports, trial


def _room(ios_tx: float, ios_share: float = 0.5, seed: int = 301):
    cfg = RoomConfig(students=93, door_open=False, ios_share=ios_share)
    m = {k: dict(v) for k, v in cfg.models.items()}
    m["iphone"]["tx"] = ios_tx
    cfg = replace(cfg, models=m)
    rng = random.Random(seed)
    nodes, seeds, wall = build_scene(cfg, rng)
    return cfg, nodes, seeds, synth_reports(cfg, nodes, wall, rng)


def test_platform_of_model_strings():
    assert platform_of("Apple iPhone14,5") == "ios" and platform_of("iphone") == "ios"
    assert platform_of("Xiaomi Redmi Note 12") == "android" and platform_of("ref") == "android"


def test_self_calibration_recovers_the_platform_gap():
    for x in (0.0, 6.0, 12.0, 18.0):
        cfg, nodes, _, rep = _room(x)
        _, c = self_calibrate(rep, platforms(cfg, nodes))
        ios = next(c[k] for k, v in nodes.items() if v["model"] == "iphone")
        andr = next(c[k] for k, v in nodes.items() if v["model"] != "iphone")
        android_tx = (0.55 * 0.0 + 0.30 * -2.0) / 0.85            # mean TX of the Android mix
        assert abs((ios - andr) - -(x - android_tx)) < 1.0, x


def test_twelve_db_imbalance_breaks_without_self_calibration_and_not_with_it():
    cfg = replace(RoomConfig(students=93, door_open=False, ios_share=0.5))
    m = {k: dict(v) for k, v in cfg.models.items()}
    m["iphone"]["tx"] = 12.0
    cfg = replace(cfg, models=m)
    def rate(p):
        rs = [trial(cfg, p, s) for s in range(6)]
        return sum(r["false_absent"] for r in rs) / sum(r["inside"] for r in rs)
    off, on = rate(Params(autocal=False)), rate(Params())
    assert off > 0.10 and on < 0.02      # measured: ~28% of the class lost without, ~1% with


def test_lying_phone_cannot_steer_the_correction():
    cfg, nodes, _, rep = _room(6.0, ios_share=0.3, seed=5)
    groups = platforms(cfg, nodes)
    _, c0 = self_calibrate(rep, groups)
    liar = next(k for k, v in nodes.items() if v["model"] == "ref" and v["inside"])
    lied = {a: dict(b) for a, b in rep.items()}
    lied[liar] = {k: v + 15 for k, v in lied[liar].items()}         # inflates every reading by 15 dB
    fixed, c1 = self_calibrate(lied, groups)
    assert abs(c1[liar] - c0[liar]) < 0.2                           # pooled per platform: one phone barely moves it
    # its own links stay lopsided by ~15 dB, so the agreement test still rejects them
    peers = [b for b in fixed[liar] if liar in fixed.get(b, {})]
    lopsided = sum(1 for b in peers if abs(fixed[liar][b] - fixed[b][liar]) > Params().delta_db)
    assert lopsided > 0.8 * len(peers)


def test_small_platform_groups_are_not_corrected():
    rep = {"a": {"i": -60.0}, "i": {"a": -75.0}, "b": {"i": -61.0}}
    groups = {"a": "android", "b": "android", "i": "ios"}           # one iPhone < AUTOCAL_MIN_GROUP
    assert AUTOCAL_MIN_GROUP > 1
    fixed, c = self_calibrate(rep, groups)
    assert c == {} and fixed == rep
    assert self_calibrate(rep, None) == (rep, {})


def _maxflow_reference(seeds, adj, targets, limit):
    """The original dict-based implementation, kept as an oracle."""
    seeds = set(seeds)
    INFC = limit + 1
    base, nbr = {}, {}

    def add(u, v, c):
        base[(u, v)] = base.get((u, v), 0) + c
        base.setdefault((v, u), 0)
        nbr.setdefault(u, []).append(v)
        nbr.setdefault(v, []).append(u)

    for u, lst in adj.items():
        add(("in", u), ("out", u), INFC if u in seeds else 1)
        for w, _ in lst:
            add(("out", u), ("in", w), 1)
    for sd in seeds:
        if sd in adj:
            add("S", ("in", sd), INFC)
    out = {}
    for t in targets:
        if t in seeds:
            out[t] = limit
            continue
        sink = ("in", t)
        if "S" not in nbr or sink not in nbr:
            out[t] = 0
            continue
        cap, flow = dict(base), 0
        while flow < limit:
            parent, q = {"S": None}, ["S"]
            for u in q:
                for w in nbr[u]:
                    if w not in parent and cap[(u, w)] > 0:
                        parent[w] = u
                        q.append(w)
            if sink not in parent:
                break
            w = sink
            while parent[w] is not None:
                u = parent[w]
                cap[(u, w)] -= 1
                cap[(w, u)] += 1
                w = u
            flow += 1
        out[t] = flow
    return out


def test_fast_maxflow_equals_reference_on_random_graphs():
    for t in range(800):
        R = random.Random(t)
        n = R.randint(2, 22)
        ids = [f"v{i}" for i in range(n)]
        adj = {v: [] for v in ids}
        for i in range(n):
            for j in range(i + 1, n):
                if R.random() < R.uniform(0.05, 0.5):
                    adj[ids[i]].append((ids[j], 1.0))
                    adj[ids[j]].append((ids[i], 1.0))
        seeds = R.sample(ids, R.randint(1, min(4, n))) + (["ghost"] if R.random() < 0.2 else [])
        k = R.randint(1, 3)
        assert disjoint_paths_many(seeds, adj, ids, k) == _maxflow_reference(seeds, adj, ids, k), t


def test_evaluate_without_groups_is_unchanged_by_autocal():
    cfg, nodes, seeds, rep = _room(0.0)
    assert set(evaluate(seeds, rep, Params())["present"]) == set(evaluate(seeds, rep, Params(autocal=False))["present"])
