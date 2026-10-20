"""The LIVE roll call (protocol v3): phones join by themselves, report every second, the server re-evaluates continuously.

This is the window-less counterpart of ble_fast.synth_reports + server.trial. Same room, same channel, same phone models,
same REAL engine (app.services.graph.evaluate) - what changes is time:

  t = 0           the teacher starts the subject; the teacher phone advertises and scans at once (seed).
  push            each student phone is woken by its long-poll (server wake within ~100 ms + one-way network delay), checks in
                  (TCP/TLS set-up + request/response round trips from the uplink profile), then turns its radio on.
  every 100 ms    adverts arrive (Poisson per directed pair, the same rate as ble_fast); a peer is reportable after
                  LIVE_MIN_SAMPLES adverts; the median RSSI uses the last LIVE_WINDOW samples (live.ts LiveCollector).
  report          first report as soon as LIVE_FIRST_NEIGHBOURS peers are reportable, then every LIVE_REPORT_INTERVAL_MS.
                  Delivery takes connection set-up + one-way delay; with probability `loss` it needs REQUEST_TIMEOUT_MS plus the
                  first retry delay (session.ts retry policy).
  server          at most one evaluation per LIVE_EVAL_DEBOUNCE_MS (config.py) on the LATEST report of every phone. Once a student is shown
                  Present they stay Present (Hub._latch); a co-location flag releases the latch.
  finish          the teacher taps Finish when the Present count has not changed for `stable_s` (the app shows "stable for N s"),
                  or at `horizon_s` / LIVE_MAX_S at the latest. Not-yet-present students are ABSENT at finish.

Outputs per classroom: false-absent / corridor false-present AT FINISH, per-student time-to-present (what the student sees:
from the moment their phone learned about the roll call to the server's PRESENT arriving back), flicker (students that were
Present and then not), relay results. Every timing that is not read from the code is tagged in LIVE_TAGS ("assumed").
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, fields

import numpy as np

from app.services.graph import Params, evaluate
from netsim import uplink
from netsim.channel import pair_mean_rssi
from netsim.config import RoomConfig
from netsim.scenario import build_scene, platforms
from sim import protocol

SEED_MODES = ("teacher_phone", "front_bench", "teacher_phone_plus_front")


@dataclass
class LiveConfig:
    seed_mode: str = "teacher_phone"        # who the server trusts as roots (the real server: teacher phone + seeds the teacher verified)
    push_ms_lo: float = 50.0                # long-poll wake -> response leaves the server [assumed; test_m6 pins it < 100 ms on the dev server]
    push_ms_hi: float = 150.0
    bio_s_lo: float = 0.0                   # student unlocks with fingerprint / face / lock before joining: 0 = not modelled in the pre-declared study [assumed]
    bio_s_hi: float = 0.0
    startup_s: float = 0.4                  # check-in answered -> radio advertising + scanning (prepareRadio already ran) [assumed]
    teacher_startup_s: float = 0.3          # start response -> teacher radio on [assumed]
    teacher_front_m: float = 1.0            # teacher phone stands this far in front of the middle bench column [assumed]
    report_phase_s: float = 0.0             # phones report at tick granularity, no extra phase [spec: LIVE_TICK_MS]
    eval_step_s: float = protocol.LIVE_EVAL_DEBOUNCE_MS / 1000.0   # [spec]
    stable_s: float = 5.0                   # teacher finishes after this many seconds without a change [assumed: a human rule]
    min_finish_s: float = protocol.LIVE_BEST_AFTER_S   # the app tells the teacher to wait this long [spec: live.ts]; earlier = weaker relay check
    horizon_s: float = 45.0                 # simulate at most this long (server auto-finishes at LIVE_MAX_S) [assumed]
    relays: int = 0                         # (accomplice, absent friend) pairs, A4

    def __post_init__(self):
        if self.seed_mode not in SEED_MODES:
            raise ValueError(f"seed_mode must be one of {SEED_MODES}")


LIVE_TAGS = {
    "seed_mode": "spec", "push_ms_lo": "assumed", "push_ms_hi": "assumed", "bio_s_lo": "assumed", "bio_s_hi": "assumed", "startup_s": "assumed", "teacher_startup_s": "assumed",
    "teacher_front_m": "assumed", "report_phase_s": "spec", "eval_step_s": "spec", "stable_s": "assumed", "min_finish_s": "spec",
    "horizon_s": "assumed", "relays": "spec",
}
assert {f.name for f in fields(LiveConfig)} == set(LIVE_TAGS), "every LiveConfig field needs a provenance tag"


def _room_width(cfg: RoomConfig) -> float:
    return cfg.bench_cols * cfg.seats_per_bench * cfg.seat_pitch + (cfg.bench_cols - 1) * cfg.aisle


def live_trial(cfg: RoomConfig, lc: LiveConfig, p: Params, seed: int, calibrate: bool = True) -> dict:
    rng = random.Random(seed)
    nodes, front_seeds, wall = build_scene(cfg, rng)
    cand = [k for k, v in nodes.items() if v["inside"] and k not in front_seeds]
    accomplices = rng.sample(cand, min(lc.relays, len(cand))) if lc.relays else []
    friends = []
    for i, a in enumerate(accomplices):
        f = f"F{i}"
        nodes[f] = dict(nodes[a], clone_of=a, inside=False, attack="relay")
        friends.append(f)
    ref_model = "ref" if "ref" in cfg.models else next(iter(cfg.models))
    nodes["teacher"] = {"pos": (_room_width(cfg) / 2.0, -lc.teacher_front_m), "inside": True, "model": ref_model}

    ids = list(nodes)
    N = len(ids)
    ix = {k: i for i, k in enumerate(ids)}
    g_shadow, g_count, g_noise, g_det, g_net, g_orient = (np.random.default_rng(x)
                                                          for x in np.random.SeedSequence(rng.getrandbits(63)).spawn(6))
    prof = [cfg.models[nodes[k]["model"]] for k in ids]
    rx = np.array([q["rx"] for q in prof]); tx = np.array([q["tx"] for q in prof])
    adv = np.array([q["adv_ms"] for q in prof]); eff = np.array([q["scan_eff"] for q in prof])
    iu, ju, d, mean = pair_mean_rssi(cfg, nodes, wall, g_shadow, g_orient)
    hear = np.concatenate([iu, ju]); src = np.concatenate([ju, iu]); mean2 = np.concatenate([mean, mean])
    P = len(hear)

    # ---- who learns about the roll call when, and when their radio is on -------------------------------------------------
    mix = uplink.parse_mix(cfg.uplink)
    pr = [uplink.PROFILES[mix[k][0]] for k in g_net.choice(len(mix), size=N, p=[f for _, f in mix])]
    rtt = np.array([(q["rtt_ms"] / 1000.0) * math.exp(g_net.normal(0, q["rtt_sigma"])) if q["rtt_ms"] > 0 else 0.0 for q in pr])
    loss = np.array([q["loss"] for q in pr])
    push = g_net.uniform(lc.push_ms_lo, lc.push_ms_hi, N) / 1000.0 + rtt / 2.0           # session start -> phone knows
    if lc.bio_s_hi > 0:                                                                  # the person's own unlock comes before the phone joins (live.ts 'confirming')
        push = push + g_net.uniform(lc.bio_s_lo, lc.bio_s_hi, N)                         # ttp below counts from the unlock, like the app
    joined_at = push + (uplink.CONN_RTTS + 1.0) * rtt + uplink.VERIFY_MS / 1000.0         # check-in answered
    on = joined_at + lc.startup_s
    ti = ix["teacher"]
    push[ti], joined_at[ti], on[ti] = 0.0, 0.0, lc.teacher_startup_s
    for f in friends:                                                                    # the absent friend taps at once
        on[ix[f]] = 1.0
        joined_at[ix[f]] = push[ix[f]] = 0.5
    deliver = (uplink.CONN_RTTS + 0.5) * rtt + uplink.VERIFY_MS / 1000.0                 # one report, no loss
    timeout_s = protocol.REQUEST_TIMEOUT_MS / 1000.0
    retry_s = protocol.RETRY_START_MS / 1000.0

    # ---- advert process on a 100 ms grid (= LIVE_TICK_MS, the phone reporter's tick and the native flush) -----------------
    dt = protocol.LIVE_TICK_MS / 1000.0
    steps = int(lc.horizon_s / dt)
    p_ok = math.exp(-2 * cfg.airtime_ms * float((1.0 / adv).sum()))
    lam = 1000.0 / adv[src] * eff[hear] * p_ok * dt                                      # adverts per tick per directed pair
    z = g_noise.normal(0, 1, P)
    ok_det = g_det.random(P) < cfg.p_detect
    base_ok = ok_det & (mean2 + rx[hear] + tx[src] > cfg.sensitivity - 6.0)              # cheap pre-filter, exact test below
    m = np.zeros(P, dtype=np.int32)
    m_hist = np.zeros((steps + 1, P), dtype=np.int16)
    for k in range(1, steps + 1):
        t = k * dt
        act = (t >= on[hear]) & (t >= on[src]) & base_ok
        m = m + g_count.poisson(np.where(act, lam, 0.0)).astype(np.int32)
        m_hist[k] = np.minimum(m, 30000)
    win = np.minimum(m_hist, protocol.LIVE_WINDOW)
    off = (rx + tx)[hear] if calibrate else np.zeros(P)

    def rssi_of(mk: np.ndarray, sel: np.ndarray) -> np.ndarray:
        sig = np.sqrt(cfg.dir_sigma ** 2 + (1.2533 * cfg.fast_sigma) ** 2 / np.maximum(mk, 1))
        return mean2[sel] + rx[hear[sel]] + tx[src[sel]] + z[sel] * sig - off[sel]

    # ---- report schedule per phone ----------------------------------------------------------------------------------------
    minq = protocol.LIVE_MIN_SAMPLES
    first = np.full(N, np.inf)
    qual = m_hist >= minq                                                                # (steps+1, P)
    cnt_q = np.zeros((steps + 1, N), dtype=np.int16)
    for h in range(N):
        sel = np.flatnonzero(hear == h)
        if sel.size:
            cnt_q[:, h] = qual[:, sel].sum(axis=1)
    for h in range(N):
        hit = np.flatnonzero(cnt_q[:, h] >= protocol.LIVE_FIRST_NEIGHBOURS)
        if hit.size:
            first[h] = hit[0] * dt
    # report times of phone h: first[h] + k * interval, snapped to ticks; the delivery delay (and a loss penalty) follow
    interval = protocol.LIVE_REPORT_INTERVAL_MS / 1000.0
    n_rep = int(lc.horizon_s / interval) + 1
    rep_send = first[:, None] + np.arange(n_rep)[None, :] * interval                     # (N, n_rep)
    lost = g_net.random((N, n_rep)) < loss[:, None]
    rep_arr = rep_send + deliver[:, None] + np.where(lost, timeout_s + retry_s, 0.0)
    rep_step = np.minimum(np.floor(rep_send / dt + 1e-9).astype(np.int64), steps)       # tick whose counts the report holds
    rep_step[~np.isfinite(rep_send)] = -1

    plat = platforms(cfg, nodes)
    plat["teacher"] = cfg.models[ref_model]["platform"]
    seeds = {"teacher_phone": ["teacher"], "front_bench": list(front_seeds),
             "teacher_phone_plus_front": ["teacher"] + list(front_seeds)}[lc.seed_mode]

    ins = [k for k, v in nodes.items() if v["inside"] and k not in set(seeds) and k != "teacher"]
    outs = [k for k, v in nodes.items() if not v["inside"] and k not in friends]
    evals, present_hist, t_first_present = [], [], {}
    last_res: dict = {"present": {}, "colocated": {}}
    latched: set = set()
    te = 0.0
    fin_t = None
    last_change_t = 0.0
    prev_set: frozenset = frozenset()
    while te <= lc.horizon_s and te <= protocol.LIVE_MAX_S:
        te = round(te + lc.eval_step_s, 6)
        if te > lc.horizon_s:
            break
        # latest DELIVERED report of every phone at server time te
        arrived = rep_arr <= te
        idx = np.where(arrived, np.arange(n_rep)[None, :], -1).max(axis=1)              # latest delivered report number
        have = idx >= 0
        step_of = np.where(have, rep_step[np.arange(N), np.maximum(idx, 0)], -1)
        use = have & (step_of >= 0)
        sel = np.flatnonzero(use[hear])
        mk = m_hist[step_of[hear[sel]], sel]
        good = mk >= minq
        sel, mk = sel[good], mk[good]
        r = rssi_of(np.minimum(mk, protocol.LIVE_WINDOW), sel)
        keep = (r + (off[sel] if calibrate else 0.0)) > cfg.sensitivity
        sel, r = sel[keep], r[keep]
        reports: dict = {ids[h]: {} for h in np.flatnonzero(use)}
        for pi, val in zip(sel, np.rint(r)):
            reports[ids[hear[pi]]][ids[src[pi]]] = int(val)
        last_res = evaluate(seeds, reports, p, plat) if reports else {"present": {}, "colocated": {}}
        # server rule (app/services/live.py Hub._latch): once shown Present a student stays Present; only a co-location flag releases it
        flagged = set(last_res.get("colocated", {}))
        latched -= flagged
        latched |= set(last_res["present"]) - flagged
        pres = frozenset((set(last_res["present"]) | latched) - flagged)
        evals.append(te); present_hist.append(pres)
        for k in pres:
            t_first_present.setdefault(k, te)
        if pres != prev_set:
            last_change_t = te
            prev_set = pres
        if fin_t is None and te >= lc.min_finish_s and te - last_change_t >= lc.stable_s and len(pres) > 0:
            fin_t = te
            break
    if fin_t is None:
        fin_t = evals[-1] if evals else 0.0
    final = present_hist[-1] if present_hist else frozenset()

    notify = g_net.uniform(0.02, 0.10, N) + rtt / 2.0                                    # status long-poll answers the phone
    ttp = np.array([t_first_present[k] + notify[ix[k]] - push[ix[k]] for k in ins if k in final and k in t_first_present])
    ever_out = sum(1 for k in outs if any(k in s for s in present_hist))
    flicker = sum(1 for k in ins if k in t_first_present and k not in final)
    res = {
        "inside": len(ins), "outside": len(outs),
        "false_absent": sum(1 for k in ins if k not in final),
        "false_present": sum(1 for k in outs if k in final),
        "ever_false_present": ever_out,
        "flicker": flicker,
        "finish_s": fin_t,
        "ttp": [float(x) for x in ttp],
        "ttp_p50": float(np.percentile(ttp, 50)) if ttp.size else math.nan,
        "ttp_p95": float(np.percentile(ttp, 95)) if ttp.size else math.nan,
        "ttp_max": float(ttp.max()) if ttp.size else math.nan,
        "n_evals": len(evals),
    }
    if friends:
        res.update({"relays": len(friends),
                    "relay_admitted": sum(1 for f in friends if f in final),
                    "relay_flagged": sum(1 for f in friends if f in last_res.get("colocated", {}))})
    return res

