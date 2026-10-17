"""Fast analytical BLE link layer: Poisson sample counts per ordered pair, median noise shrinking with sqrt(samples).

A phone i collects m_ij ~ Poisson(overlap * 1000/adv_j * scan_eff_i * p_ok) adverts from j, where p_ok is the chance an
advert survives collisions with every other advertiser. A pair is detected iff m_ij >= min_samples. This is the default
for large sweeps; the packet-level model (ble_des.py, M3) is used to show the two agree (experiment E07).
"""
from __future__ import annotations

import math
import random

import numpy as np

from netsim.channel import pair_mean_rssi
from netsim.config import RoomConfig
from netsim.phone import tap_times
from sim import protocol


def synth_reports(cfg: RoomConfig, nodes: dict, wall: tuple, rng: random.Random, calibrate: bool = True,
                  with_counts: bool = False, stats: dict | None = None):
    """Every phone's report: {reporter: {peer: median RSSI}} (and optionally the sample counts). Vectorised (numpy)."""
    # separate streams per noise source (common random numbers): changing the window only changes sample counts,
    # so comparisons between configurations are like-for-like
    g_shadow, g_count, g_noise, g_det, g_tap, g_orient, g_up = (np.random.default_rng(x) for x in np.random.SeedSequence(rng.getrandbits(63)).spawn(7))
    ids = list(nodes)
    N = len(ids)
    prof = [cfg.models[nodes[k]["model"]] for k in ids]
    rx = np.array([q["rx"] for q in prof]); tx = np.array([q["tx"] for q in prof])
    adv = np.array([q["adv_ms"] for q in prof]); eff = np.array([q["scan_eff"] for q in prof])

    iu, ju, d, mean = pair_mean_rssi(cfg, nodes, wall, g_shadow, g_orient, stats)

    tap = tap_times(cfg, g_tap, N)
    for i, k in enumerate(ids):                          # attackers choose their own timing (e.g. a relay taps at once)
        if "tap_s" in nodes[k]:
            tap[i] = nodes[k]["tap_s"]
    joined = tap <= cfg.window_s
    on = tap + cfg.startup_s                              # radio on
    overlap = np.maximum(0.0, cfg.window_s + cfg.tail_s - np.maximum(on[iu], on[ju])) * (joined[iu] & joined[ju])
    if cfg.ble_mode == "des":
        out, counts = _des_reports(cfg, ids, prof, iu, ju, mean, on, joined, rx, tx, g_count, g_noise, g_det, calibrate, stats)
        return _finish(cfg, ids, out, counts, joined, g_up, with_counts, stats)
    if cfg.ble_mode != "fast":
        raise ValueError(f"unknown ble_mode {cfg.ble_mode!r}")
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
    return _finish(cfg, ids, out, counts, joined, g_up, with_counts, stats)


def _des_reports(cfg, ids, prof, iu, ju, mean, on, joined, rx, tx, g_sched, g_noise, g_det, calibrate, stats):
    """Same report format as the fast model, produced by the packet-level advertising-channel simulation."""
    from netsim import ble_des
    from netsim.phone import reports_from_samples
    N = len(ids)
    M = np.full((N, N), -200.0)
    M[iu, ju] = mean; M[ju, iu] = mean
    g_rx = np.random.default_rng(g_sched.integers(1 << 62))
    r, s, v, st = ble_des.simulate(cfg, M, prof, on, joined, g_sched, g_rx)
    if stats is not None:
        stats["des"] = st
    drop = ~(g_det.random(N * N) < cfg.p_detect)                          # pair never reported (OS hiccup)
    dn = g_noise.normal(0, cfg.dir_sigma, N * N)                         # per-direction offset more samples cannot average away
    out, counts = reports_from_samples(r, s, v + dn[r.astype(np.int64) * N + s], ids, cfg.min_samples, drop_pairs=drop)
    for i, a in enumerate(ids):
        off = (rx[i] + tx[i]) if calibrate else 0.0
        out[a] = {b: int(np.rint(val - off)) for b, val in out[a].items()}
    return out, counts


def _finish(cfg, ids, out, counts, joined, g_up, with_counts, stats):
    """Uplink stage: reports that do not reach the server before the deadline are missing (that student is absent)."""
    if cfg.uplink != "ideal":
        from netsim import uplink
        who = [i for i in range(len(ids)) if joined[i]]
        # discovery ends, then radio stop + signing + send: 50-250 ms [assumed]
        ready = cfg.window_s + cfg.tail_s + 0.05 + g_up.uniform(0.0, 0.2, len(who))
        deadline = cfg.window_s + cfg.tail_s + protocol.GRACE_S
        outcomes = uplink.simulate(ready, np.array([len(out[ids[i]]) for i in who]), deadline, cfg.uplink, g_up,
                                   cfg.upload_jitter_s)
        for i, o in zip(who, outcomes):
            if o.delivered_at_s is None:
                out.pop(ids[i], None); counts.pop(ids[i], None)
        if stats is not None:
            stats["uplink"] = uplink.summarise(outcomes, cfg.window_s + cfg.tail_s)
    return (out, counts) if with_counts else out
