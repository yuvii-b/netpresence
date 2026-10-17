"""Attacks on the roll call. Each function runs the REAL engine on a simulated room with one attacker model applied.

A1 corridor        honest phones behind the wall/door             -> netsim.server.trial (false_present)
A2 remote forger   an absent student uploads a report claiming strong links to random in-room ids
A3 collusion       c in-room accomplices add fabricated mutual links with an absent friend
A4 relay/wormhole  an in-room accomplice's radio ALSO advertises the absent friend's id (the friend's report mirrors what the
                   accomplice's honest neighbours measured: the best case for the attacker)
A5 RSSI inflation  a phone adds +X dB to every reading it reports
A6 replay          resubmitting an old signed report: refused by the session binding in the signature (API test in
                   tests/netsim/test_m5_attacks.py)
A7 id spoof        advertising a classmate's id from your own radio: to the server this is A4 (two ids, one radio) whenever the
                   stolen id belongs to someone who is not in the room. A present classmate whose id is also sent by a second
                   radio (readings become a blend of two sources) is NOT modelled yet.
"""
from __future__ import annotations

import random

from app.services.graph import Params, evaluate
from netsim.ble_fast import synth_reports
from netsim.config import RoomConfig
from netsim.scenario import build_scene, platforms


def add_relays(nodes: dict, accomplices: list[str]) -> list[str]:
    """Give each accomplice's radio a second id owned by an absent friend; returns the friends' ids."""
    friends = []
    for i, a in enumerate(accomplices):
        f = f"F{i}"
        nodes[f] = dict(nodes[a], clone_of=a, inside=False, attack="relay", tap_s=1.0)   # the friend's phone taps at once
        friends.append(f)
    return friends


def relay_trial(cfg: RoomConfig, p: Params, seed: int, relays: int = 1) -> dict:
    """A4. `relays` independent (accomplice, absent friend) pairs in one honest class."""
    rng = random.Random(seed)
    nodes, seeds, wall = build_scene(cfg, rng)
    cand = [k for k, v in nodes.items() if v["inside"] and k not in seeds]
    accomplices = rng.sample(cand, min(relays, len(cand)))
    friends = add_relays(nodes, accomplices)
    reports = synth_reports(cfg, nodes, wall, rng)
    res = evaluate(seeds, reports, p, platforms(cfg, nodes))
    present, col = res["present"], res.get("colocated", {})
    honest = [k for k in cand if k not in accomplices]
    return {
        "relays": len(friends),
        "relay_admitted": sum(1 for f in friends if f in present),            # the attack worked
        "relay_flagged": sum(1 for f in friends if f in col),
        "accomplices_flagged": sum(1 for a in accomplices if a in col),
        "honest": len(honest),
        "honest_flagged": sum(1 for k in honest if k in col),
        "honest_absent": sum(1 for k in honest if k not in present),
    }


def forger_trial(cfg: RoomConfig, p: Params, seed: int, claims: int = 8) -> bool:
    """A2. True if the absent forger 'R' is admitted. R never gets a reverse reading from anyone, so no edge can form."""
    rng = random.Random(seed)
    nodes, seeds, wall = build_scene(cfg, rng)
    reports = synth_reports(cfg, nodes, wall, rng)
    ins = [k for k, v in nodes.items() if v["inside"]]
    reports["R"] = {k: -55 for k in rng.sample(ins, min(claims, len(ins)))}
    groups = platforms(cfg, nodes); groups["R"] = "android"
    return "R" in evaluate(seeds, reports, p, groups)["present"]


def collusion_trial(cfg: RoomConfig, p: Params, seed: int, colluders: int) -> bool:
    """A3. Remote friend 'R' with `colluders` in-room accomplices who fabricate mutual strong edges. True if R is marked present."""
    rng = random.Random(seed)
    nodes, seeds, wall = build_scene(cfg, rng)
    reports = synth_reports(cfg, nodes, wall, rng)
    ins = [k for k, v in nodes.items() if v["inside"] and k not in seeds]
    reports["R"] = {}
    for c in rng.sample(ins, min(colluders, len(ins))):
        reports[c]["R"] = -60
        reports["R"][c] = -60
    groups = platforms(cfg, nodes)
    groups["R"] = "android"
    return "R" in evaluate(seeds, reports, p, groups)["present"]


def inflation_trial(cfg: RoomConfig, p: Params, seed: int, x_db: float) -> dict:
    """A5. One corridor phone adds +x_db to every reading it reports. Returns whether it was admitted and how many honest
    in-room students were lost."""
    rng = random.Random(seed)
    nodes, seeds, wall = build_scene(cfg, rng)
    reports = synth_reports(cfg, nodes, wall, rng)
    out = sorted(k for k, v in nodes.items() if not v["inside"])
    liar = out[0]
    reports[liar] = {b: r + x_db for b, r in reports.get(liar, {}).items()}
    present = evaluate(seeds, reports, p, platforms(cfg, nodes))["present"]
    ins = [k for k, v in nodes.items() if v["inside"] and k not in seeds]
    return {"liar_admitted": liar in present, "false_absent": sum(1 for k in ins if k not in present), "inside": len(ins)}
