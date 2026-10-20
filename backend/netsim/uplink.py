"""Uplink network: the classroom Wi-Fi / 4G that every phone's signed report crosses at (nearly) the same moment.

All phones in a class upload when discovery ends, a classic synchronised burst. Model, per request:
    client send -> [shared medium FIFO: size / effective capacity] -> one-way delay -> [server FIFO: verify_ms] -> one-way delay
    (+ connection set-up round trips on every attempt)
* Shared medium (Wi-Fi): one FIFO server; effective capacity C / (1 + alpha * stations in flight) (802.11 DCF efficiency drops
  with the number of contending stations). 4G is per phone (no shared queue) with rare stalls.
* An attempt fails with probability `loss` (half the time the request never reaches the server, half the time the response is
  lost; profile key `blackout` = nothing ever gets through, for tests). The client then sees nothing until the per-request timeout
  (protocol.REQUEST_TIMEOUT_MS, read from api.ts) and retries. A lost RESPONSE means the server already has the report.
* The client policy is EXACTLY submitReport in mobile/core/src/session.ts: first retry after 500 ms, doubling up to 4 s, and it
  gives up when now + delay would pass the report deadline (retry-vectors.json from the real TypeScript pins the schedule).
* Optional upload jitter: each phone waits U(0, J) before its first attempt.
Every profile number is an assumption (tag "assumed") until measured with loadtest.py on the real classroom network.
"""
from __future__ import annotations

import heapq
import json
import math
from dataclasses import dataclass

import numpy as np

from sim import protocol

RETRY_START_MS = float(protocol.RETRY_START_MS)
RETRY_MAX_MS = float(protocol.RETRY_MAX_MS)
VERIFY_MS = 1.5                 # ECDSA verify + checks per report [measured on the dev machine; see docs/NETSIM.md]
HTTP_OVERHEAD_BYTES = 700       # request line + headers + TLS record overhead [assumed]
CONN_RTTS = 2.0                 # TCP + TLS set-up round trips paid by every attempt (no connection reuse in a burst) [assumed]

PROFILES: dict[str, dict] = {
    "ideal":          {"shared": False, "rtt_ms": 0.0, "rtt_sigma": 0.0, "loss": 0.0, "cap_mbps": 1e6, "alpha": 0.0, "stall_p": 0.0},
    "wifi_good":      {"shared": True, "rtt_ms": 15.0, "rtt_sigma": 0.5, "loss": 0.005, "cap_mbps": 30.0, "alpha": 0.0, "stall_p": 0.0},
    "wifi_congested": {"shared": True, "rtt_ms": 80.0, "rtt_sigma": 1.0, "loss": 0.03, "cap_mbps": 5.0, "alpha": 0.02, "stall_p": 0.0},
    "cell_4g":        {"shared": False, "rtt_ms": 60.0, "rtt_sigma": 0.5, "loss": 0.01, "cap_mbps": 10.0, "alpha": 0.0, "stall_p": 0.01},
}


def report_bytes(n_neighbours: int) -> int:
    """JSON body of POST /report exactly as api.ts sends it (checked against the TypeScript in retry-vectors.json)."""
    nb = [{"peer_id": f"{0x1000 + i * 7919:08x}", "rssi_median": -60 - (i % 30), "sample_count": 3 + (i % 40)}
          for i in range(n_neighbours)]
    return len(json.dumps({"student_id": "S0123456", "neighbours": nb, "signature": "A" * 96}, separators=(",", ":")))


def retry_attempt_times_ms(start_ms: float, deadline_ms: float, fail_after_ms: float = 0.0) -> list[float]:
    """When submitReport tries if every attempt fails `fail_after_ms` after it was sent (retry-vectors.json uses 0)."""
    times, delay, t = [], RETRY_START_MS, start_ms
    while True:
        times.append(t)
        t_fail = t + fail_after_ms
        if t_fail + delay > deadline_ms:
            return times
        t = t_fail + delay
        delay = min(delay * 2, RETRY_MAX_MS)


def parse_mix(spec: str) -> list[tuple[str, float]]:
    """"wifi_good" or "wifi_good:0.7,cell_4g:0.3" -> [(name, share)] with shares summing to 1."""
    parts = []
    for item in spec.split(","):
        name, _, frac = item.strip().partition(":")
        if name not in PROFILES:
            raise ValueError(f"unknown uplink profile {name!r}; known: {', '.join(PROFILES)}")
        parts.append((name, float(frac) if frac else 1.0))
    tot = sum(f for _, f in parts)
    return [(n, f / tot) for n, f in parts]


@dataclass
class Outcome:
    delivered_at_s: float | None     # when the server processed the report (None = never, before the deadline)
    attempts: int
    gave_up: bool


def simulate(ready_s: np.ndarray, n_neighbours: np.ndarray, deadline_s: float, spec: str, g: np.random.Generator,
             jitter_s: float = 0.0, timeout_ms: float | None = None) -> list[Outcome]:
    """Send one report per phone (ready at ready_s[i]) over the uplink; returns one Outcome per phone."""
    timeout_s = (protocol.REQUEST_TIMEOUT_MS if timeout_ms is None else timeout_ms) / 1000.0
    n = len(ready_s)
    mix = parse_mix(spec)
    prof_of = [PROFILES[mix[k][0]] for k in g.choice(len(mix), size=n, p=[f for _, f in mix])]
    start = ready_s + (g.uniform(0.0, jitter_s, n) if jitter_s > 0 else 0.0)
    out = [Outcome(None, 0, False) for _ in range(n)]
    ev = [(float(start[i]), i, RETRY_START_MS / 1000.0) for i in range(n)]
    heapq.heapify(ev)
    medium_free, inflight = 0.0, []            # shared Wi-Fi medium: next free time, completion times of requests in flight
    server_free = 0.0
    while ev:
        t, i, delay = heapq.heappop(ev)
        out[i].attempts += 1
        p = prof_of[i]
        size_bits = (report_bytes(int(n_neighbours[i])) + HTTP_OVERHEAD_BYTES) * 8.0
        rtt = (p["rtt_ms"] / 1000.0) * math.exp(g.normal(0, p["rtt_sigma"])) if p["rtt_ms"] > 0 else 0.0
        stall = g.uniform(1.0, 3.0) if g.random() < p["stall_p"] else 0.0
        t_ready = t + CONN_RTTS * rtt + stall
        if p["shared"]:
            while inflight and inflight[0] <= t_ready:
                heapq.heappop(inflight)
            cap = p["cap_mbps"] * 1e6 / (1.0 + p["alpha"] * len(inflight))
            begin = max(t_ready, medium_free)
            medium_free = begin + size_bits / cap
            heapq.heappush(inflight, medium_free)
            t_arrive = medium_free + rtt / 2
        else:
            t_arrive = t_ready + size_bits / (p["cap_mbps"] * 1e6) + rtt / 2
        lost_req = p.get("blackout", False) or g.random() < p["loss"] / 2
        lost_resp = g.random() < p["loss"] / 2
        success = False
        if not lost_req:
            begin = max(t_arrive, server_free)
            server_free = begin + VERIFY_MS / 1000.0
            if server_free > deadline_s:                       # refused: the roll call is over (4xx, not retried)
                out[i].gave_up = out[i].delivered_at_s is None
                continue
            if out[i].delivered_at_s is None:
                out[i].delivered_at_s = server_free
            success = (not lost_resp) and (server_free + rtt / 2 - t) <= timeout_s
        if success:
            continue
        t_fail = t + timeout_s                                 # nothing usable came back: the request times out
        if t_fail + delay > deadline_s:
            out[i].gave_up = out[i].delivered_at_s is None
            continue
        heapq.heappush(ev, (t_fail + delay, i, min(delay * 2, RETRY_MAX_MS / 1000.0)))
    return out


def summarise(outcomes: list[Outcome], ready_s: float) -> dict:
    done = [o.delivered_at_s for o in outcomes if o.delivered_at_s is not None]
    n = max(len(outcomes), 1)
    lat = np.array(done) - ready_s if done else np.array([math.nan])
    return {"phones": len(outcomes), "delivered_pct": 100.0 * len(done) / n,
            "attempts_mean": float(np.mean([o.attempts for o in outcomes])) if outcomes else 0.0,
            "t_all_in_s": float(np.max(lat)) if done else math.nan,
            "latency_p50_s": float(np.percentile(lat, 50)), "latency_p95_s": float(np.percentile(lat, 95))}
