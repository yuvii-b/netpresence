"""Packet-level BLE advertising-channel simulation for the whole room (discrete events, vectorised).

What is simulated, for every phone that joined the roll call:
  * Advertiser: an advertising event every `adv_ms + U(0, adv_delay_max_ms)` (BLE Core Vol 6 B 4.4.2.2). An event sends the
    same PDU on channels 37, 38, 39 in order, `t_ifs_adv_ms` apart. PDU airtime at LE 1M = (1+4+2+payload+3) * 8 us
    (protocol.ADV_AIRTIME_MS).
  * Scanner: listens `window` of every `interval` ms on one channel, advancing 37 -> 38 -> 39 every interval, random phase per
    phone. Android window/interval come from the Kotlin code (SCAN_MODE_LOW_LATENCY = continuous); iOS is continuous with a
    channel dwell of `ios_scan_dwell_ms` (assumed).
  * A phone cannot receive while it transmits (half duplex).
  * Collisions: two PDUs overlapping in time on the same channel interfere at a receiver. Without capture the PDU is lost if
    any interferer is above sensitivity there; with capture it survives iff its power exceeds the summed interferers by
    `capture_db`. Interferer power at each receiver comes from the same channel model (hidden terminals arise naturally).
  * 2.4 GHz background: a PDU on channel c is lost with probability p_bg[c].
  * Per-PDU Rician fast fading (K = rician_k_db) on top of the pair's mean power.
  * OS layer: a received PDU reaches the app with probability scan_eff of the phone model (callback loss); iOS may also
    coalesce duplicates (`ios_min_report_ms`).
Output: for each ordered pair (receiver, sender) the list of RSSI samples, as flat arrays.
"""
from __future__ import annotations

import numpy as np

from netsim.config import RoomConfig

CHUNK = 6000   # PDUs processed at once (memory ~ CHUNK x phones x 8 bytes per array)


def _lin(db):
    return 10.0 ** (np.asarray(db) / 10.0)


def schedule(cfg: RoomConfig, on: np.ndarray, joined: np.ndarray, adv: np.ndarray, g: np.random.Generator):
    """All PDUs: arrays (start_ms, channel 0..2, sender), sorted by start. Phones that did not join send nothing."""
    end_ms = (cfg.window_s + cfg.tail_s) * 1000.0
    starts, chans, senders = [], [], []
    ifs = cfg.airtime_ms + cfg.t_ifs_adv_ms
    for j in np.flatnonzero(joined):
        t0 = on[j] * 1000.0
        span = end_ms - t0
        if span <= 0:
            continue
        n = int(span / adv[j]) + 2
        gaps = adv[j] + g.uniform(0.0, cfg.adv_delay_max_ms, n)
        ev = t0 + g.uniform(0.0, adv[j]) + np.concatenate([[0.0], np.cumsum(gaps[:-1])])
        for c in range(3):
            t = ev + c * ifs
            keep = t + cfg.airtime_ms <= end_ms
            starts.append(t[keep]); chans.append(np.full(keep.sum(), c)); senders.append(np.full(keep.sum(), j))
    if not starts:
        z = np.zeros(0)
        return z, z.astype(int), z.astype(int)
    t = np.concatenate(starts); c = np.concatenate(chans); s = np.concatenate(senders)
    o = np.lexsort((s, c, t))      # total order, deterministic ties
    return t[o], c[o], s[o]


def overlaps(t: np.ndarray, tau: float):
    """Index pairs (p, q), p != q, whose PDUs overlap in time (all PDUs have the same airtime tau)."""
    hi = np.searchsorted(t, t + tau, side="left")       # PDUs i+1 .. hi-1 start before PDU i ends
    cnt = np.maximum(hi - np.arange(len(t)) - 1, 0)
    i = np.repeat(np.arange(len(t)), cnt)
    off = np.arange(cnt.sum()) - np.repeat(np.cumsum(cnt) - cnt, cnt)
    j = i + 1 + off
    return np.concatenate([i, j]), np.concatenate([j, i])


def simulate(cfg: RoomConfig, M: np.ndarray, models: list[dict], on: np.ndarray, joined: np.ndarray,
             g_sched: np.random.Generator, g_rx: np.random.Generator, pdus=None, phase=None):
    """Run the advertising channel. M[i, j] = mean RSSI between phones i and j (symmetric, before phone gains).

    Returns (receiver, sender, rssi, stats): arrays with one row per PDU delivered to a phone's app, plus a stats dict."""
    N = len(models)
    rx = np.array([m["rx"] for m in models]); tx = np.array([m["tx"] for m in models])
    adv = np.array([m["adv_ms"] for m in models]); eff = np.array([m["scan_eff"] for m in models])
    ios = np.array([m["platform"] == "ios" for m in models])
    from sim import protocol
    win = np.where(ios, cfg.ios_scan_dwell_ms, float(protocol.ANDROID_SCAN_WINDOW_MS))
    itv = np.where(ios, cfg.ios_scan_dwell_ms, float(protocol.ANDROID_SCAN_INTERVAL_MS))
    ph = g_sched.uniform(0.0, 1.0, N) * itv
    phase = ph if phase is None else np.asarray(phase, dtype=float)      # `pdus`/`phase`: tests inject a fixed schedule
    t, ch, snd = pdus if pdus is not None else schedule(cfg, on, joined, adv, g_sched)
    P = len(t)
    stats = {"pdus": int(P), "collided": 0, "half_duplex": 0, "background": 0, "below_sensitivity": 0, "not_listening": 0,
             "os_dropped": 0, "delivered": 0}
    if P == 0:
        z = np.zeros(0)
        return z.astype(int), z.astype(int), z, stats
    tau = cfg.airtime_ms
    pa, pb = overlaps(t, tau)                                    # pairs sorted by pa within each half; sort by pa
    o = np.argsort(pa, kind="stable"); pa, pb = pa[o], pb[o]
    bounds = np.searchsorted(pa, np.arange(0, P + CHUNK, CHUNK))
    K = 10.0 ** (cfg.rician_k_db / 10.0)
    pbg = np.array(cfg.p_bg)
    got_r, got_s, got_v, got_t = [], [], [], []
    ar = np.arange(N)
    for ci, lo in enumerate(range(0, P, CHUNK)):
        hi = min(lo + CHUNK, P)
        sl = slice(lo, hi)
        n = hi - lo
        s_c, c_c, t_c = snd[sl], ch[sl], t[sl]
        mean = M[s_c] + tx[s_c][:, None] + rx[None, :]                       # (n, N) dBm at each receiver
        fad = np.sqrt(K / (K + 1)) + np.sqrt(0.5 / (K + 1)) * (g_rx.normal(size=(n, N)) + 1j * g_rx.normal(size=(n, N)))
        rssi = mean + 20.0 * np.log10(np.abs(fad) + 1e-12)
        live = np.ones((n, N), dtype=bool)
        live[np.arange(n), s_c] = False                                       # nobody hears itself
        # scanner listening on this PDU's channel
        x = t_c[:, None] - phase[None, :]
        chan_now = np.floor(x / itv[None, :]).astype(np.int64) % 3
        listening = (chan_now == c_c[:, None]) & (np.mod(x, itv[None, :]) < win[None, :])
        stats["not_listening"] += int((live & ~listening).sum()); live &= listening
        # receiver must have its radio on and have joined
        on_ok = joined[None, :] & (t_c[:, None] >= (on * 1000.0)[None, :])
        live &= on_ok
        # collisions / half duplex from overlapping PDUs
        a, b = bounds[ci], bounds[min(ci + 1, len(bounds) - 1)]
        qa, qb = pa[a:b] - lo, pb[a:b]
        same = ch[qb] == c_c[qa]
        interf = np.zeros((n, N)); nint = np.zeros((n, N), dtype=np.int32)
        blocked = np.zeros((n, N), dtype=bool)
        blocked[qa, snd[qb]] = True                                           # transmitting receivers cannot listen
        if same.any():
            ia, ib = qa[same], qb[same]
            pw = M[snd[ib]] + tx[snd[ib]][:, None] + rx[None, :]              # interferer power at every receiver
            np.add.at(interf, ia, _lin(pw))
            np.add.at(nint, ia, (pw > cfg.sensitivity).astype(np.int32))
        stats["half_duplex"] += int((live & blocked).sum()); live &= ~blocked
        if cfg.capture:
            with np.errstate(divide="ignore"):
                sir = rssi - 10.0 * np.log10(np.maximum(interf, 1e-30))
            lost = (interf > 0) & (sir < cfg.capture_db)
        else:
            lost = nint > 0
        stats["collided"] += int((live & lost).sum()); live &= ~lost
        bg = g_rx.random((n, N)) < pbg[c_c][:, None]
        stats["background"] += int((live & bg).sum()); live &= ~bg
        weak = rssi <= cfg.sensitivity
        stats["below_sensitivity"] += int((live & weak).sum()); live &= ~weak
        osdrop = g_rx.random((n, N)) >= eff[None, :]
        stats["os_dropped"] += int((live & osdrop).sum()); live &= ~osdrop
        r_i, p_i = np.nonzero(live.T)                                         # receiver, pdu-in-chunk
        got_r.append(r_i); got_s.append(s_c[p_i]); got_v.append(rssi[p_i, r_i]); got_t.append(t_c[p_i])
    r = np.concatenate(got_r); s_ = np.concatenate(got_s); v = np.concatenate(got_v); tt = np.concatenate(got_t)
    if cfg.ios_min_report_ms > 0:
        keep = _coalesce(r, s_, tt, cfg.ios_min_report_ms, ios)
        stats["os_dropped"] += int((~keep).sum()); r, s_, v = r[keep], s_[keep], v[keep]
    stats["delivered"] = int(len(r))
    return r, s_, v, stats


def _coalesce(r, s, t, min_ms, ios):
    """iOS: at most one report per (receiver, sender) per min_ms. Android receivers are untouched."""
    keep = np.ones(len(r), dtype=bool)
    idx = np.flatnonzero(ios[r])
    o = idx[np.lexsort((t[idx], s[idx], r[idx]))]
    last_key, last_t = None, -1e18
    for i in o:
        key = (r[i], s[i])
        if key != last_key or t[i] - last_t >= min_ms:
            last_key, last_t = key, t[i]
        else:
            keep[i] = False
    return keep


def median_reports(r: np.ndarray, s: np.ndarray, v: np.ndarray, ids: list[str], min_samples: int, ok_pair: np.ndarray,
                   dir_noise: np.ndarray):
    """Per ordered pair: median RSSI and sample count (>= min_samples). Median of an even count averages the middle two."""
    out = {k: {} for k in ids}; counts = {k: {} for k in ids}
    if not len(r):
        return out, counts
    N = len(ids)
    key = r.astype(np.int64) * N + s
    o = np.lexsort((v, key))
    key, v = key[o], v[o]
    uk, start, cnt = np.unique(key, return_index=True, return_counts=True)
    for k, a, c in zip(uk, start, cnt):
        if c < min_samples or not ok_pair[k]:
            continue
        mid = v[a + (c - 1) // 2: a + c // 2 + 1].mean() + dir_noise[k]
        out[ids[k // N]][ids[k % N]] = mid
        counts[ids[k // N]][ids[k % N]] = int(c)
    return out, counts
