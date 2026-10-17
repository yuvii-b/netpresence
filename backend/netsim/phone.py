"""Phone / app / OS layer.

* tap_times: when each student taps (lognormal reaction time).
* NeighbourCollector: an exact Python port of mobile/core/src/aggregate.ts (checked against vectors produced by the real
  TypeScript, mobile/core/test/fixtures/collector-vectors.json). Each RSSI sample is rounded half-up (JavaScript Math.round),
  the median of an even count averages the middle pair and rounds half-up, peers with fewer than min_samples are dropped,
  the list is sorted by (-count, -median, peer) and capped at MAX_NEIGHBOURS.
* reports_from_samples: the same reduction, vectorised, for the packet-level link layer.
"""
from __future__ import annotations

import math
import re

import numpy as np

from netsim.config import RoomConfig
from sim import protocol

_NAME = re.compile(r"^NP-([0-9a-f]{8})$", re.IGNORECASE)


def tap_times(cfg: RoomConfig, g_tap: np.random.Generator, n: int) -> np.ndarray:
    """Each phone taps after a lognormal delay; a tap after check-in closes means the student never joins."""
    return g_tap.lognormal(math.log(cfg.tap_median_s), cfg.tap_sigma, n) if cfg.tap_median_s > 0 else np.zeros(n)


def js_round(x: float) -> int:
    """JavaScript Math.round: halves round toward +infinity."""
    return math.floor(x + 0.5)


def _median(xs: list[int]) -> int:
    s = sorted(xs)
    m = len(s) >> 1
    return s[m] if len(s) % 2 else js_round((s[m - 1] + s[m]) / 2)


class NeighbourCollector:
    """Port of aggregate.ts NeighbourCollector (names must look like NP-xxxxxxxx)."""

    def __init__(self, self_eph: str):
        self.self_eph = self_eph.lower()
        self.samples: dict[str, list[int]] = {}

    def add(self, name: str, rssi: float) -> None:
        m = _NAME.match(name or "")
        if not m:
            return
        peer = m.group(1).lower()
        if peer == self.self_eph:
            return
        if not math.isfinite(rssi) or rssi >= 0 or rssi < -127:
            return
        self.samples.setdefault(peer, []).append(js_round(rssi))

    def neighbours(self, min_samples: int = protocol.MIN_SAMPLES, max_n: int = protocol.MAX_NEIGHBOURS) -> list[dict]:
        out = [{"peer_id": p, "rssi_median": _median(xs), "sample_count": len(xs)}
               for p, xs in self.samples.items() if len(xs) >= min_samples]
        out.sort(key=lambda n: (-n["sample_count"], -n["rssi_median"], n["peer_id"]))
        return out[:max_n]

    @property
    def peers_heard(self) -> int:
        return len(self.samples)


def reports_from_samples(r: np.ndarray, s: np.ndarray, v: np.ndarray, ids: list[str], min_samples: int | None = None,
                         max_n: int | None = None, drop_pairs: np.ndarray | None = None):
    """Vectorised NeighbourCollector for many phones at once.

    r, s, v: receiver index, sender index, RSSI of every delivered advert. `drop_pairs[r * N + s]` True removes a pair
    entirely. Returns ({receiver: {peer: median}}, {receiver: {peer: count}}) keyed by ids, already capped to max_n peers
    per receiver in collector order (most heard first)."""
    min_samples = protocol.MIN_SAMPLES if min_samples is None else min_samples
    max_n = protocol.MAX_NEIGHBOURS if max_n is None else max_n
    out = {k: {} for k in ids}
    counts = {k: {} for k in ids}
    if not len(r):
        return out, counts
    N = len(ids)
    ok = (v < 0) & (v >= -127)
    r, s, v = r[ok], s[ok], np.floor(v[ok] + 0.5).astype(np.int64)
    key = r.astype(np.int64) * N + s
    o = np.lexsort((v, key))
    key, v = key[o], v[o]
    uk, start, cnt = np.unique(key, return_index=True, return_counts=True)
    keep = cnt >= min_samples
    if drop_pairs is not None:
        keep &= ~drop_pairs[uk]
    uk, start, cnt = uk[keep], start[keep], cnt[keep]
    lo = v[start + (cnt - 1) // 2]
    hi = v[start + cnt // 2]
    med = np.where(cnt % 2 == 1, lo, np.floor((lo + hi) / 2.0 + 0.5).astype(np.int64))
    rec = uk // N
    for rr in np.unique(rec):
        sel = np.flatnonzero(rec == rr)
        peers = uk[sel] % N
        order = sorted(range(len(sel)), key=lambda i: (-int(cnt[sel[i]]), -int(med[sel[i]]), ids[peers[i]]))[:max_n]
        for i in order:
            out[ids[rr]][ids[peers[i]]] = int(med[sel[i]])
            counts[ids[rr]][ids[peers[i]]] = int(cnt[sel[i]])
    return out, counts
