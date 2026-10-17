"""Export a simulated class as a fixture for the mobile-core integration test.

    python -m sim.export_scene --students 93 --seed 11 --out ../mobile/core/test/fixtures/scene93.json

Each student gets: model, and for every peer it hears a list of raw RSSI samples whose MEDIAN is the simulator's
reading. A Node 'phone' replays exactly these samples through the real mobile-core code and the real server;
`expected` is the graph engine's verdict on the same data (computed independently of the HTTP stack).
"""
import argparse
import json
import random

from app.services.graph import Params, adaptive_edge_m, evaluate
from sim.room import RoomConfig, build_scene, synth_reports


def export(students: int, seed: int, remote: int, door_open: bool):
    cfg = RoomConfig(students=students, door_open=door_open)
    rng = random.Random(seed)
    nodes, seeds, wall = build_scene(cfg, rng)
    raw = synth_reports(cfg, nodes, wall, rng, calibrate=False)      # raw readings incl. per-model bias
    people = {}
    for k, v in nodes.items():
        samples = {}
        for peer, r in raw[k].items():
            r = int(r)
            samples[peer] = [r - 1, r, r + 1, r, r, r - 2, r + 2, r]  # median == r
        people[k] = {"model": v["model"], "inside": v["inside"], "samples": samples}
    away = [f"away{i}" for i in range(remote)]
    inside = [k for k, v in nodes.items() if v["inside"]]
    for a in away:       # remote cheaters: one-sided claims of strong links to six random students
        people[a] = {"model": "ref", "inside": False, "remote": True,
                     "samples": {p: [-55] * 8 for p in rng.sample(inside, 6)}}
    offsets = {m: -b for m, b in cfg.models.items()}
    calibrated = {k: {p: int(r) + offsets[nodes[k]["model"]] for p, r in d.items()} for k, d in raw.items()}
    params = Params(max_edge_m=adaptive_edge_m(len(nodes) + remote))
    present = sorted(evaluate(seeds, calibrated, params)["present"])
    return {
        "students": students, "seed": seed, "seeds": seeds, "calibration_offsets": offsets,
        "people": people, "expected_present": present,
        "expected_not_present": sorted(set(people) - set(present)),
        "params": params.as_dict(),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--students", type=int, default=93)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--remote", type=int, default=5)
    ap.add_argument("--door-closed", action="store_true")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    doc = export(a.students, a.seed, a.remote, not a.door_closed)
    with open(a.out, "w") as f:
        json.dump(doc, f)
    print(f"{a.out}: {len(doc['people'])} phones, {len(doc['expected_present'])} expected present")
