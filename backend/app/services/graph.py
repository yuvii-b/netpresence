"""Proximity-graph engine: admit edges, flood from verified seeds, enforce k witnesses.

Pure functions, no I/O, so the same code runs in the API, the simulator and tests.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable

INF = float("inf")


@dataclass(frozen=True)
class Params:
    ref_dbm: float = -59.0     # A: RSSI at 1 m
    n: float = 3.0             # path-loss exponent
    max_edge_m: float = 2.0    # an edge is only admitted within this estimated distance
    ttl: int = 8               # max hops from a seed
    max_path_m: float = 15.0   # max cumulative estimated metres from a seed
    k: int = 2                 # independent mutual witnesses required per non-seed node
    delta_db: float = 8.0      # max |rssi_ab - rssi_ba|

    def as_dict(self) -> dict:
        return asdict(self)


def rssi_to_distance(rssi_dbm: float, p: Params) -> float:
    """Invert RSSI = A - 10 n log10(d)."""
    return 10 ** ((p.ref_dbm - rssi_dbm) / (10 * p.n))


# reports: reporter -> {peer -> rssi_dbm (already corrected by the per-model offset)}
Reports = dict[str, dict[str, float]]
Edges = dict[tuple[str, str], float]   # sorted (a, b) -> estimated metres


def build_edges(reports: Reports, p: Params) -> Edges:
    """Admit (a, b) only if BOTH directions were reported, both implied distances
    are within max_edge_m, and the two RSSI values agree within delta_db."""
    edges: Edges = {}
    for a, seen in reports.items():
        for b, r_ab in seen.items():
            if a >= b or a == b:
                continue
            r_ba = reports.get(b, {}).get(a)
            if r_ba is None:
                continue
            if abs(r_ab - r_ba) > p.delta_db:
                continue
            d_ab, d_ba = rssi_to_distance(r_ab, p), rssi_to_distance(r_ba, p)
            if d_ab > p.max_edge_m or d_ba > p.max_edge_m:
                continue
            edges[(a, b)] = (d_ab + d_ba) / 2
    return edges


def _adjacency(edges: Edges, alive: set[str] | None = None) -> dict[str, list[tuple[str, float]]]:
    adj: dict[str, list[tuple[str, float]]] = {}
    for (a, b), d in edges.items():
        if alive is not None and (a not in alive or b not in alive):
            continue
        adj.setdefault(a, []).append((b, d))
        adj.setdefault(b, []).append((a, d))
    return adj


def flood(seeds: Iterable[str], edges: Edges, p: Params, alive: set[str] | None = None) -> dict[str, tuple[int, float]]:
    """TTL- and metre-bounded flood. Returns node -> (min hops, min metres among
    paths that satisfy BOTH bounds). Layered DP: best[h][v] = shortest metres to v in exactly <=h hops."""
    adj = _adjacency(edges, alive)
    seeds = [s for s in seeds if alive is None or s in alive]
    best: dict[str, tuple[int, float]] = {s: (0, 0.0) for s in seeds}
    frontier: dict[str, float] = {s: 0.0 for s in seeds}   # nodes improved in the last layer -> metres
    shortest: dict[str, float] = {s: 0.0 for s in seeds}
    for hop in range(1, p.ttl + 1):
        nxt: dict[str, float] = {}
        for u, du in frontier.items():
            for v, w in adj.get(u, []):
                nd = du + w
                if nd > p.max_path_m or nd >= shortest.get(v, INF):
                    continue
                if nd < nxt.get(v, INF):
                    nxt[v] = nd
        for v, nd in nxt.items():
            shortest[v] = nd
            if v not in best:
                best[v] = (hop, nd)
        frontier = nxt
        if not frontier:
            break
    return best


def evaluate(seeds: Iterable[str], reports: Reports, p: Params) -> dict:
    """Run edge admission, flood, and iterative k-witness pruning.

    A non-seed node survives only if it is flood-reachable AND has >= k admitted
    edges to nodes that also survive. Pruning repeats to a fixed point.
    """
    seeds = list(dict.fromkeys(seeds))
    edges = build_edges(reports, p)
    alive = set(flood(seeds, edges, p)) | set(seeds)
    while True:
        adj = _adjacency(edges, alive)
        drop = {v for v in alive if v not in seeds and len(adj.get(v, [])) < p.k}
        if not drop:
            break
        alive -= drop
        alive = set(flood(seeds, edges, p, alive)) | {s for s in seeds if s in alive}
    reach = flood(seeds, edges, p, alive)
    adj = _adjacency(edges, alive)
    present = {
        v: {"hops": reach[v][0], "path_m": round(reach[v][1], 2), "witnesses": len(adj.get(v, []))}
        for v in alive if v in reach
    }
    return {"present": present, "edges": len(edges), "edge_list": edges}
