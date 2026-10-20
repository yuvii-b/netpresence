"""Baselines on the same rooms and seeds as NetPresence, so the comparison is like for like (experiments E09, E10).

Every function returns the same dict:
    inside / false_absent        seated non-seed students and how many were marked absent
    outside / false_present      corridor phones and how many were marked present
    proxy_attempts / proxy_success  absent friends trying to be marked present by a classmate or a forwarded photo
    time_s                       how long the whole roll call takes
    seats                        [(bench_col, bench_row, absent)] for the per-seat heatmap
All parameters are tagged `assumed` below; the paper must say so (E08 sweeps them).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace

import numpy as np

from app.services.graph import Params, adaptive_edge_m
from netsim import attacks
from netsim.ble_fast import synth_reports
from netsim.channel import pair_geometry
from netsim.config import RoomConfig
from netsim.scenario import build_scene, seat_of
from netsim.server import trial_detail

PROXY_FRIENDS = 5          # absent students with a friend in the room who try to be marked present [assumed]


@dataclass(frozen=True)
class BaselineParams:
    # B0 manual roll call
    call_s: tuple = (1.5, 3.0)        # seconds to call a name and hear the answer [assumed]
    repeat_p: float = 0.20            # share of names that need a second call [assumed]
    proxy_answer_p: float = 0.5       # a friend answers "present" for an absentee without being noticed [assumed]
    # B1 teacher beacon
    beacon_y: float = -1.0            # m in front of the first bench, at the middle of the room
    # B2 acoustic broadcast (v1)
    spl_1m_db: float = 75.0           # teacher phone speaker at 1 m [assumed]
    body_db: float = 1.0              # per body in the path [assumed]
    acoustic_wall_db: float = 25.0    # through the side wall [assumed]
    fade_sigma_db: float = 3.0        # multipath / seat position [assumed]
    ambient_db: float = 58.0          # classroom noise with fans [assumed]
    ambient_sigma_db: float = 3.0
    snr_android_db: float = -6.0      # broadband SNR needed to detect the narrow-band tone (~14 dB processing gain) [assumed; E10 sweeps it]
    snr_ios_extra_db: float = 13.0    # iPhone microphone needs ~13 dB more (measured in the v1 trials, email thread)
    # B5 rotating QR on the projector
    qr_read_p: float = 0.97           # student can see and scan the code [assumed]
    qr_share_p: float = 0.30          # a photo of the code reaches an absent friend in time [assumed]
    qr_window_s: float = 20.0         # code rotates; everyone scans inside one window [assumed]


BP = BaselineParams()


def _scene(cfg: RoomConfig, seed: int):
    rng = random.Random(seed)
    nodes, seeds, wall = build_scene(cfg, rng)
    return rng, nodes, seeds, wall


def _result(cfg, nodes, seeds, absent: set, present_out: set, proxy_ok: int, proxy_n: int, time_s: float) -> dict:
    seat = seat_of(nodes, cfg)
    ins = [k for k, v in nodes.items() if v["inside"] and k not in seeds]
    outs = [k for k, v in nodes.items() if not v["inside"]]
    return {"inside": len(ins), "false_absent": sum(1 for k in ins if k in absent),
            "outside": len(outs), "false_present": sum(1 for k in outs if k in present_out),
            "proxy_attempts": proxy_n, "proxy_success": proxy_ok, "time_s": time_s,
            "seats": [(seat[k][0], seat[k][1], k in absent) for k in ins if k in seat]}


def b0_manual(cfg: RoomConfig, seed: int, bp: BaselineParams = BP) -> dict:
    """Teacher calls every name. Always correct for the people in the room, slow, and a friend can answer for you."""
    rng, nodes, seeds, wall = _scene(cfg, seed)
    n = sum(1 for v in nodes.values() if v["inside"])
    t = sum(rng.uniform(*bp.call_s) * (2 if rng.random() < bp.repeat_p else 1) for _ in range(n + PROXY_FRIENDS))
    ok = sum(1 for _ in range(PROXY_FRIENDS) if rng.random() < bp.proxy_answer_p)
    return _result(cfg, nodes, seeds, set(), set(), ok, PROXY_FRIENDS, t)


def _teacher_links(cfg: RoomConfig, nodes: dict, wall: tuple, bp: BaselineParams, rng: random.Random):
    """Geometry from the teacher's desk to every student: distance, bodies in the path, wall flag."""
    width = cfg.bench_cols * cfg.seats_per_bench * cfg.seat_pitch + (cfg.bench_cols - 1) * cfg.aisle
    tnodes = {"T": {"pos": (width / 2, bp.beacon_y), "inside": True, "model": "ref"}, **nodes}
    ids = list(tnodes)
    P, iu, ju, d, bodies, walled = pair_geometry(cfg, tnodes, wall)
    sel = np.flatnonzero(iu == 0)                         # pairs (T, x), x = ju
    return tnodes, ids, ju[sel], d[sel], bodies[sel], walled[sel]


def b1_beacon(cfg: RoomConfig, seed: int, threshold_dbm: float | None = None, bp: BaselineParams = BP) -> dict:
    """One BLE beacon on the teacher's desk: present iff the beacon is heard above a threshold. The threshold is the best
    single value for this head-count, chosen on held-out classrooms (fit_beacon_threshold) unless given."""
    if threshold_dbm is None:
        threshold_dbm = fit_beacon_threshold(cfg)
    rng, nodes, seeds, wall = _scene(cfg, seed)
    g = np.random.default_rng(rng.getrandbits(63))
    tnodes, ids, tgt, d, bodies, walled = _teacher_links(cfg, nodes, wall, bp, rng)
    mean = (cfg.A - 10 * cfg.n * np.log10(d) - cfg.body_db * np.minimum(bodies, cfg.body_cap) - np.where(walled, cfg.wall_db, 0.0)
            + g.normal(0, cfg.shadow_sigma, d.shape))
    prof = np.array([cfg.models[tnodes[ids[j]]["model"]]["rx"] for j in tgt])
    r = mean + prof + g.normal(0, cfg.fast_sigma / math.sqrt(30), d.shape)      # median of ~30 beacon samples
    heard = {ids[j] for j, v in zip(tgt, r) if v >= threshold_dbm}
    absent = {k for k in nodes if k not in heard}
    ok = sum(1 for _ in range(PROXY_FRIENDS) if rng.random() < bp.qr_share_p)    # the beacon's code can be forwarded like a QR photo
    return _result(cfg, nodes, seeds, absent, {k for k in heard if not nodes[k]["inside"]}, ok, PROXY_FRIENDS, cfg.window_s)


_beacon_cache: dict = {}


def fit_beacon_threshold(cfg: RoomConfig, held_out: range = range(1000, 1012), bp: BaselineParams = BP) -> float:
    """Threshold minimising (false-absent + corridor false-present) over held-out classrooms. Cached per configuration."""
    key = (cfg.students, cfg.door_open, cfg.layout, cfg.n, cfg.A, cfg.shadow_sigma, cfg.n_outside)
    if key in _beacon_cache:
        return _beacon_cache[key]
    best, best_t = 1e9, -80.0
    for t in range(-95, -55, 2):
        err = 0.0
        for s in held_out:
            r = b1_beacon(cfg, s, float(t), bp)
            err += r["false_absent"] / max(r["inside"], 1) + r["false_present"] / max(r["outside"], 1)
        if err < best:
            best, best_t = err, float(t)
    _beacon_cache[key] = best_t
    return best_t


def b2_acoustic(cfg: RoomConfig, seed: int, bp: BaselineParams = BP) -> dict:
    """v1: the teacher's phone plays a tone; a phone counts if it detects it. Sound falls 6 dB per doubling, bodies and walls
    absorb it, fans mask it, and iPhone microphones need ~13 dB more signal-to-noise."""
    rng, nodes, seeds, wall = _scene(cfg, seed)
    g = np.random.default_rng(rng.getrandbits(63))
    tnodes, ids, tgt, d, bodies, walled = _teacher_links(cfg, nodes, wall, bp, rng)
    spl = (bp.spl_1m_db - 20 * np.log10(np.maximum(d, 1.0)) - bp.body_db * np.minimum(bodies, 3)
           - np.where(walled, bp.acoustic_wall_db, 0.0) + g.normal(0, bp.fade_sigma_db, d.shape))
    noise = bp.ambient_db + g.normal(0, bp.ambient_sigma_db, d.shape)
    need = np.array([bp.snr_android_db + (bp.snr_ios_extra_db if cfg.models[tnodes[ids[j]]["model"]]["platform"] == "ios" else 0.0)
                     for j in tgt])
    heard = {ids[j] for j, s, nz, nd in zip(tgt, spl, noise, need) if s - nz >= nd}
    absent = {k for k in nodes if k not in heard}
    ok = sum(1 for _ in range(PROXY_FRIENDS) if rng.random() < bp.qr_share_p)    # a recording of the tone can be forwarded
    return _result(cfg, nodes, seeds, absent, {k for k in heard if not nodes[k]["inside"]}, ok, PROXY_FRIENDS, cfg.window_s)


def b5_qr(cfg: RoomConfig, seed: int, bp: BaselineParams = BP) -> dict:
    """A rotating QR code on the projector: anyone who can see the screen scans it. A photo of the code can be forwarded."""
    rng, nodes, seeds, wall = _scene(cfg, seed)
    absent = {k for k, v in nodes.items() if v["inside"] and rng.random() > bp.qr_read_p}
    ok = sum(1 for _ in range(PROXY_FRIENDS) if rng.random() < bp.qr_share_p)
    return _result(cfg, nodes, seeds, absent, set(), ok, PROXY_FRIENDS, bp.qr_window_s)


def netpresence(cfg: RoomConfig, seed: int, p: Params | None = None, relay_friends: int = PROXY_FRIENDS) -> dict:
    """The real system: honest accuracy from one classroom, proxy attempts as relay attacks (A4) in another with the same seed."""
    p = p or Params(max_edge_m=adaptive_edge_m(cfg.students or cfg.capacity))
    t = trial_detail(cfg, p, seed)
    a = attacks.relay_trial(cfg, p, seed, relay_friends)
    return {"inside": t["inside"], "false_absent": t["false_absent"], "outside": t["outside"], "false_present": t["false_present"],
            "proxy_attempts": a["relays"], "proxy_success": a["relay_admitted"],
            "time_s": cfg.window_s + cfg.tail_s + 1.0, "seats": t["seats"]}


def b3_no_disjoint(cfg: RoomConfig, seed: int) -> dict:
    """k-witness only, without vertex-disjoint paths (ablation)."""
    return netpresence(cfg, seed, Params(max_edge_m=adaptive_edge_m(cfg.students or cfg.capacity), independent=False))


def b4_no_selfcal(cfg: RoomConfig, seed: int) -> dict:
    """No platform self-calibration (ablation); meaningful with a mixed Android/iOS class and TX asymmetry."""
    return netpresence(cfg, seed, Params(max_edge_m=adaptive_edge_m(cfg.students or cfg.capacity), autocal=False))


def np_no_colocation(cfg: RoomConfig, seed: int) -> dict:
    """NetPresence without the relay defence (ablation for E03/E09)."""
    return netpresence(cfg, seed, Params(max_edge_m=adaptive_edge_m(cfg.students or cfg.capacity), colocation_db=0.0))


BASELINES = {
    "B0 manual roll call": b0_manual, "B1 teacher beacon": b1_beacon, "B2 acoustic (v1)": b2_acoustic,
    "B3 no disjoint paths": b3_no_disjoint, "B4 no self-calibration": b4_no_selfcal, "B5 rotating QR": b5_qr,
    "NetPresence": netpresence, "NetPresence, no co-location": np_no_colocation,
}


def summarise(rs: list[dict]) -> dict:
    ins = sum(r["inside"] for r in rs) or 1
    outs = sum(r["outside"] for r in rs) or 1
    pa = sum(r["proxy_attempts"] for r in rs) or 1
    return {"false_absent_pct": 100 * sum(r["false_absent"] for r in rs) / ins,
            "corridor_present_pct": 100 * sum(r["false_present"] for r in rs) / outs,
            "proxy_success_pct": 100 * sum(r["proxy_success"] for r in rs) / pa,
            "time_s": float(np.mean([r["time_s"] for r in rs]))}
