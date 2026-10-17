"""Monte-Carlo classroom for tuning the proximity-graph parameters (plan phase 3).

Radio model per ordered pair (i hears j), with Android and iOS nodes modelled separately:
    rssi = A - 10 n log10(d) - body loss - wall loss + shadow_ij + rx_i + tx_j + noise_ij
  * shadow_ij is symmetric (same physical path); noise_ij is independent per direction.
  * rx_i / tx_j are the receiver gain and transmit power of each phone model (iOS cannot set TX power; Android
    advertises at ADVERTISE_TX_POWER_HIGH). The server's self-calibration has to cope with tx != rx asymmetry.
  * Samples: i collects m_ij ~ Poisson(window * scan_eff_i * (1000/adv_ms_j) * p_ok) adverts from j, where p_ok is
    the chance an advert survives collisions with every other advertiser in the room. A pair is detected iff
    m_ij >= min_samples; the median's error shrinks with sqrt(m_ij). So the WINDOW LENGTH drives both detection and
    accuracy - this is what tunes the roll-call duration.
Replace A, n, sigmas, body_db and the platform profiles with values measured on real phones (tools/fit_pathloss.py,
BLE lab screen). All numbers here are documented assumptions.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

import numpy as np

from sim import protocol   # every protocol constant comes from the real code (see sim/protocol.py)

from app.services.graph import Params, evaluate


@dataclass
class RoomConfig:
    # layout="bench": Indian-classroom style - bench COLUMNS facing the front, several students per bench,
    # aisles between bench columns. layout="grid": uniform seat grid (rows x cols), kept for comparison.
    layout: str = "bench"
    bench_cols: int = 3           # columns of benches (left / middle / right)
    bench_rows: int = 8           # benches front -> back in each column: 3 x 8 x 4 = 96 seats
    seats_per_bench: int = 4
    capacity: int = 93            # the room never holds more than this many students
    students: int | None = None   # exact head-count to seat (<= capacity); None = use `occupancy`
    seat_pitch: float = 0.5       # m between students sharing a bench (shoulder to shoulder)
    aisle: float = 0.8            # m gap between bench columns
    bench_pitch_y: float = 1.1    # m between consecutive benches (bench + legroom)
    seed_col: int | None = None   # which bench column's FRONT bench the teacher verifies (None = middle)
    fill: str = "random"          # "random": each seat taken with prob=occupancy; "column": fill column by column, front first
    door_open: bool = True        # the door is an opening in the side wall: no wall loss along it
    door_width: float = 1.0
    rows: int = 6                 # grid layout only
    cols: int = 10
    pitch_x: float = 0.9
    pitch_y: float = 1.2
    occupancy: float = 0.9
    A: float = -59.0
    n: float = 3.0
    shadow_sigma: float = 5.0     # dB, symmetric per pair
    dir_sigma: float = 1.0        # dB, per-direction residue that more samples cannot average away
    fast_sigma: float = 4.0       # dB, per-sample fast fading; the median of m samples has ~1.25*fast_sigma/sqrt(m)
    body_db: float = 3.0
    body_cap: int = 3
    body_radius: float = 0.35
    body_max_m: float = 8.0       # body blocking only computed for pairs closer than this (speed)
    wall_db: float = 12.0
    sensitivity: float = -95.0
    p_detect: float = 0.97        # extra chance a pair is heard at all (OS hiccups not modelled below)
    window_s: float = protocol.WINDOW_S          # check-in window: a student tapping later is absent
    tail_s: float = protocol.TAIL_S              # phones keep discovering this long after check-in closes
    tap_median_s: float = 4.0     # students tap "Mark me present" after a lognormal delay (median, s); 0 = all at t=0
    tap_sigma: float = 0.6        #   log-sd of that delay (90th percentile ~ 2.2 x median)
    startup_s: float = 1.0        # tap -> radio on (check-in round trip, permissions already granted)
    min_samples: int = protocol.MIN_SAMPLES      # NeighbourCollector default (mobile/core/src/aggregate.ts)
    sample_cap: int | None = protocol.PER_PEER_SAMPLE_CAP   # None: the phone keeps every sample per peer
    airtime_ms: float = protocol.ADV_AIRTIME_MS  # one advert: AdvA + flags + 128-bit UUID (identity inside the UUID)
    n_outside: int = 8            # phones just past the wall (corridor / next class)
    # Phone models: platform, receiver gain rx, transmit power tx (dB, relative), advertising interval, scan efficiency.
    # Android: LOW_LATENCY advertising (100 ms) + LOW_LATENCY scanning. iOS: interval not settable (assumed 150 ms),
    # duplicate reports possibly coalesced (scan_eff 0.6), fixed TX power assumed +3 dB over Android HIGH.
    models: dict = field(default_factory=lambda: {
        "ref":    {"platform": "android", "rx": 0.0, "tx": 0.0, "adv_ms": float(protocol.ANDROID_ADV_MS), "scan_eff": 0.95},
        "lowend": {"platform": "android", "rx": -4.0, "tx": -2.0, "adv_ms": float(protocol.ANDROID_ADV_MS), "scan_eff": 0.75},
        "iphone": {"platform": "ios", "rx": -9.0, "tx": 3.0, "adv_ms": 150.0, "scan_eff": 0.6},
    })
    model_mix: tuple = (0.55, 0.30, 0.15)
    ios_share: float | None = None  # override: fraction of iPhones (Android models keep their relative mix)
    n_seeds: int = 4              # grid layout; the bench layout verifies the whole front bench


def _seg_point_dist(p, a, b):
    ax, ay = a; bx, by = b; px, py = p
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _bench_seats(cfg: RoomConfig):
    """Seat coordinates as (x, y, bench_col, bench_row). y grows toward the back wall (teacher at y=0)."""
    bench_w = cfg.seats_per_bench * cfg.seat_pitch
    seats = []
    for bc in range(cfg.bench_cols):
        x0 = bc * (bench_w + cfg.aisle)
        for br in range(cfg.bench_rows):
            for k in range(cfg.seats_per_bench):
                seats.append((x0 + (k + 0.5) * cfg.seat_pitch, br * cfg.bench_pitch_y, bc, br))
    return seats


def build_scene(cfg: RoomConfig, rng: random.Random):
    if cfg.layout == "bench":
        full = _bench_seats(cfg)
        seats = [(x, y) for x, y, _, _ in full]
        meta = {(x, y): (bc, br) for x, y, bc, br in full}
        if cfg.students is not None and cfg.students > cfg.capacity:
            raise ValueError(f"room capacity is {cfg.capacity}, asked to seat {cfg.students}")
        n_seat = cfg.students if cfg.students is not None else round(cfg.occupancy * len(seats))
        n_seat = min(n_seat, cfg.capacity, len(seats))
        if cfg.fill == "column":      # column-major, front first, until the head-count is seated
            order = sorted(full, key=lambda t: (t[2], t[3], t[0]))
            occupied = [(x, y) for x, y, _, _ in order[:n_seat]]
        elif cfg.students is not None:
            occupied = rng.sample(seats, n_seat)
        else:
            occupied = [s for s in seats if rng.random() < cfg.occupancy]
            if len(occupied) > cfg.capacity:
                occupied = rng.sample(occupied, cfg.capacity)
        width = cfg.bench_cols * cfg.seats_per_bench * cfg.seat_pitch + (cfg.bench_cols - 1) * cfg.aisle
        depth = (cfg.bench_rows - 1) * cfg.bench_pitch_y
    else:
        seats = [(c * cfg.pitch_x, r * cfg.pitch_y) for r in range(cfg.rows) for c in range(cfg.cols)]
        occupied = [s for s in seats if rng.random() < cfg.occupancy]
        meta = {}
        width = (cfg.cols - 1) * cfg.pitch_x
        depth = (cfg.rows - 1) * cfg.pitch_y
    wall_x = width + 0.6                      # side wall with the door near the back
    outside = [(wall_x + rng.uniform(0.8, 3.0), rng.uniform(-0.5, depth + 0.5)) for _ in range(cfg.n_outside)]
    nodes = {}
    names = list(cfg.models)
    weights = list(cfg.model_mix)
    if cfg.ios_share is not None:
        ios = [m for m in names if cfg.models[m]["platform"] == "ios"]
        andr = [m for m in names if m not in ios]
        aw = sum(w for m, w in zip(names, weights) if m in andr) or 1.0
        weights = [(cfg.ios_share / len(ios)) if m in ios else (1 - cfg.ios_share) * w / aw
                   for m, w in zip(names, weights)]
    for i, pos in enumerate(occupied):
        nodes[f"in{i}"] = {"pos": pos, "inside": True, "model": rng.choices(names, weights)[0]}
    for i, pos in enumerate(outside):
        nodes[f"out{i}"] = {"pos": pos, "inside": False, "model": rng.choices(names, weights)[0]}
    if cfg.layout == "bench":
        col = cfg.bench_cols // 2 if cfg.seed_col is None else cfg.seed_col
        seeds = [k for k, v in nodes.items() if v["inside"] and meta[v["pos"]] == (col, 0)]
        if not seeds:                          # empty front bench: fall back to the nearest-to-teacher students
            seeds = sorted((k for k, v in nodes.items() if v["inside"]), key=lambda k: nodes[k]["pos"][1])[: cfg.seats_per_bench]
    else:
        seeds = sorted((k for k, v in nodes.items() if v["inside"]),
                       key=lambda k: (nodes[k]["pos"][1], nodes[k]["pos"][0]))[: cfg.n_seeds]
    door = (depth - cfg.door_width + 0.5, depth + 0.5) if cfg.door_open else None   # opening at the back corner
    return nodes, seeds, (wall_x, door)


def platforms(cfg: RoomConfig, nodes: dict) -> dict[str, str]:
    """phone -> platform, what the server derives from each enrolled model string."""
    return {k: cfg.models[v["model"]]["platform"] for k, v in nodes.items()}


def link_budget(cfg: RoomConfig, model: str) -> float:
    """rx + tx of a phone model: what the server's per-model calibration offset removes (offset = -link_budget)."""
    m = cfg.models[model]
    return m["rx"] + m["tx"]


def synth_reports(cfg: RoomConfig, nodes: dict, wall: tuple, rng: random.Random, calibrate: bool = True,
                  with_counts: bool = False):
    """Every phone's report: {reporter: {peer: median RSSI}} (and optionally the sample counts). Vectorised (numpy)."""
    # separate streams per noise source (common random numbers): changing the window only changes sample counts,
    # so comparisons between configurations are like-for-like
    g_shadow, g_count, g_noise, g_det, g_tap = (np.random.default_rng(x) for x in np.random.SeedSequence(rng.getrandbits(63)).spawn(5))
    wall_x, door = wall
    ids = list(nodes)
    N = len(ids)
    P = np.array([nodes[k]["pos"] for k in ids], dtype=float)
    prof = [cfg.models[nodes[k]["model"]] for k in ids]
    rx = np.array([q["rx"] for q in prof]); tx = np.array([q["tx"] for q in prof])
    adv = np.array([q["adv_ms"] for q in prof]); eff = np.array([q["scan_eff"] for q in prof])

    iu, ju = np.triu_indices(N, 1)
    A, B = P[iu], P[ju]
    d = np.maximum(0.3, np.linalg.norm(A - B, axis=1))
    # bodies (other occupied seats) within body_radius of the a-b segment. Only pairs closer than body_max_m are
    # computed: beyond that the link is far too weak to matter (no edge, below the self-calibration floor).
    q_idx = np.flatnonzero(np.array([nodes[k]["inside"] for k in ids]))
    Q = P[q_idx]
    bodies = np.zeros(d.shape, dtype=int)
    sel = np.flatnonzero(d < cfg.body_max_m)
    if sel.size and Q.size:
        a, b = A[sel], B[sel]
        ab = b - a
        L2 = np.maximum((ab ** 2).sum(1), 1e-12)
        rel = Q[None, :, :] - a[:, None, :]
        t = np.clip((rel * ab[:, None, :]).sum(2) / L2[:, None], 0.0, 1.0)
        diff = rel - t[..., None] * ab[:, None, :]
        near = (diff ** 2).sum(2) < cfg.body_radius ** 2
        near &= (q_idx[None, :] != iu[sel][:, None]) & (q_idx[None, :] != ju[sel][:, None])   # endpoints excluded
        bodies[sel] = near.sum(1)
    loss = cfg.body_db * np.minimum(bodies, cfg.body_cap)
    crosses = (A[:, 0] < wall_x) != (B[:, 0] < wall_x)
    with np.errstate(divide="ignore", invalid="ignore"):
        tt = (wall_x - A[:, 0]) / (B[:, 0] - A[:, 0])
    y_cross = A[:, 1] + tt * (B[:, 1] - A[:, 1])
    through_door = (door is not None) & (y_cross >= (door[0] if door else 0)) & (y_cross <= (door[1] if door else 0))
    loss = loss + np.where(crosses & ~through_door, cfg.wall_db, 0.0)
    mean = cfg.A - 10 * cfg.n * np.log10(d) - loss + g_shadow.normal(0, cfg.shadow_sigma, d.shape)

    # human timing: each phone taps after a lognormal delay; a tap after check-in closes = never joins (absent)
    tap = g_tap.lognormal(math.log(cfg.tap_median_s), cfg.tap_sigma, N) if cfg.tap_median_s > 0 else np.zeros(N)
    joined = tap <= cfg.window_s
    on = tap + cfg.startup_s                              # radio on
    overlap = np.maximum(0.0, cfg.window_s + cfg.tail_s - np.maximum(on[iu], on[ju])) * (joined[iu] & joined[ju])
    # collisions: per channel the room carries sum(1/adv) adverts per ms; an advert survives if nothing overlaps it
    p_ok = math.exp(-2 * cfg.airtime_ms * float((1.0 / adv[joined]).sum()))
    out = {k: {} for k in ids}
    counts = {k: {} for k in ids}
    for hear, src in ((iu, ju), (ju, iu)):            # both directions of every pair
        lam = overlap * 1000.0 / adv[src] * eff[hear] * p_ok
        m = g_count.poisson(lam)
        if cfg.sample_cap is not None:
            m = np.minimum(m, cfg.sample_cap)
        sig = np.sqrt(cfg.dir_sigma ** 2 + (1.2533 * cfg.fast_sigma) ** 2 / np.maximum(m, 1))
        r = mean + rx[hear] + tx[src] + g_noise.normal(0, 1, d.shape) * sig
        ok = (m >= cfg.min_samples) & (r > cfg.sensitivity) & (g_det.random(d.shape) < cfg.p_detect)
        if calibrate:
            r = r - (rx[hear] + tx[hear])           # server-side per-model offset = -(rx + tx) of the reporter's model
        for h, sr, val, cnt in zip(hear[ok], src[ok], np.rint(r[ok]), m[ok]):
            out[ids[h]][ids[sr]] = int(val)
            counts[ids[h]][ids[sr]] = int(cnt)
    return (out, counts) if with_counts else out


def trial(cfg: RoomConfig, p: Params, seed: int, calibrate: bool = True) -> dict:
    rng = random.Random(seed)
    nodes, seeds, wall = build_scene(cfg, rng)
    reports = synth_reports(cfg, nodes, wall, rng, calibrate)
    present = evaluate(seeds, reports, p, platforms(cfg, nodes))["present"]
    ins = [k for k, v in nodes.items() if v["inside"] and k not in seeds]
    outs = [k for k, v in nodes.items() if not v["inside"]]
    in_present = [present[k] for k in ins if k in present]
    return {
        "inside": len(ins),
        "max_hops": max((v["hops"] for v in in_present), default=0),
        "max_path_m": max((v["path_m"] for v in in_present), default=0.0),
        "false_absent": sum(1 for k in ins if k not in present),
        "outside": len(outs),
        "false_present": sum(1 for k in outs if k in present),
    }


def collusion_trial(cfg: RoomConfig, p: Params, seed: int, colluders: int) -> bool:
    """Remote friend 'R' with `colluders` in-room accomplices who fabricate mutual strong edges. True if R is marked present."""
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
