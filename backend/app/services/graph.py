"""Proximity-graph engine: admit edges, flood from verified seeds, enforce k witnesses.

Pure functions, no I/O, so the same code runs in the API, the simulator and tests.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable

import numpy as np

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
    independent: bool = True   # require k VERTEX-DISJOINT paths from the seeds (stops clusters vouching for each other)
    near_m: float = 0.0        # bench-mate rule: a non-seed needs >= near_k admitted links <= near_m (0 = off)
    near_k: int = 1
    autocal: bool = True       # self-calibrate each phone's TX/RX asymmetry from the session's own mutual readings
    colocation_db: float = 2.5     # relay/Sybil defence: two ids whose readings at the common observers differ by less than this
                                   # (robust sd, dB) are one radio, not two people (0 = off). Honest pairs differ by 3-12 dB.
    colocation_min_obs: int = 10   # common observers needed before a pair is judged
    colocation_overlap: float = 0.6     # a relay is heard by (nearly) the same observers as its source; a phone behind a wall is not
    colocation_min_dbm: float = -100.0  # observers' readings below this (near the radio's noise floor, where values saturate) are ignored

    def as_dict(self) -> dict:
        return asdict(self)


def adaptive_edge_m(n_checkins: int) -> float:
    """Edge-distance threshold by crowd density. A sparse room has few neighbours within 2 m, so the fixed default
    strands real students; a larger threshold restores coverage at a leakage cost, which is only worth paying when
    the room is empty enough to need it. Boundaries from sim.orientation (3 bench columns x 8 x 4, <=93 students);
    the < 30 check-ins step from the sparse-room sweep (20 seated + corridor phones: 3.0 m loses 20% of the class,
    3.5 m 6% at 8% corridor leak)."""
    if n_checkins >= 70:
        return 2.0
    if n_checkins >= 50:
        return 2.5
    if n_checkins >= 30:
        return 3.0
    return 3.5


def rssi_to_distance(rssi_dbm: float, p: Params) -> float:
    """Invert RSSI = A - 10 n log10(d)."""
    return 10 ** ((p.ref_dbm - rssi_dbm) / (10 * p.n))


# reports: reporter -> {peer -> rssi_dbm (already corrected by the per-model offset)}
Reports = dict[str, dict[str, float]]
Edges = dict[tuple[str, str], float]   # sorted (a, b) -> estimated metres


AUTOCAL_CAP_DB = 12.0      # never shift a platform by more than this: a bigger imbalance is a fault, not hardware
AUTOCAL_MIN_DBM = -80.0    # use links whose two-way MEAN is at least this (independent of the asymmetry itself)
AUTOCAL_MIN_GROUP = 3      # a platform needs this many phones in the session before it is corrected


def platform_of(model: str) -> str:
    """Platform from the enrolled model string ('Apple iPhone14,5' from the iOS app, anything else is Android)."""
    m = model.lower()
    return "ios" if m.startswith(("apple", "iphone", "ipad")) else "android"


def self_calibrate(reports: Reports, groups: dict[str, str] | None) -> tuple[Reports, dict[str, float]]:
    """Remove the TX/RX asymmetry between PLATFORMS using nothing but the session's own two-way readings.

    a hears b:  r_ab = PL_ab + rx_a + tx_b + noise,   b hears a:  r_ba = PL_ab + rx_b + tx_a + noise
    Shadowing is the same physical path both ways, so it cancels in the difference:
        r_ab - r_ba = w_A - w_B,   w = rx - tx of the phone's platform A, B   (iOS cannot set its TX power)
    One unknown per platform, solved by least squares over every mutual pair (re-solved once without outlier pairs),
    then readings are shifted by c = w/2 so pairs become symmetric while their mean - which sets the distance - is
    unchanged. Android and iPhone therefore agree without any lab calibration.

    Security: the correction is pooled per platform, never per phone. A phone that inflates its own readings barely
    moves its platform's estimate (hundreds of pairs), keeps its inflated asymmetry, and still fails the agreement
    test. A platform with fewer than AUTOCAL_MIN_GROUP phones is not corrected at all (no worse than no self-cal).
    """
    if not groups:
        return reports, {}
    sizes: dict[str, int] = {}
    for v in reports:
        g = groups.get(v)
        if g:
            sizes[g] = sizes.get(g, 0) + 1
    labels = sorted(g for g, n in sizes.items() if n >= AUTOCAL_MIN_GROUP)
    if len(labels) < 2:
        return reports, {}
    gi = {g: i for i, g in enumerate(labels)}
    pa, pb, dd = [], [], []
    for a, seen in reports.items():
        ga = gi.get(groups.get(a, ""))
        if ga is None:
            continue
        for b, r_ab in seen.items():
            if a >= b:
                continue
            gb = gi.get(groups.get(b, ""))
            r_ba = reports.get(b, {}).get(a)
            if gb is None or ga == gb or r_ba is None or (r_ab + r_ba) / 2 < AUTOCAL_MIN_DBM:
                continue                                  # only cross-platform pairs carry information
            pa.append(ga); pb.append(gb); dd.append(r_ab - r_ba)
    if len(dd) < AUTOCAL_MIN_GROUP:
        return reports, {}
    pa, pb, dd = np.array(pa), np.array(pb), np.array(dd, dtype=float)
    keep = np.ones(len(dd), dtype=bool)
    G = len(labels)
    w = np.zeros(G)
    for _ in range(2):                                    # solve, drop outlier pairs (|res| > max(6 dB, 3 sigma)), solve
        M = np.zeros((G, G)); rhs = np.zeros(G)
        np.add.at(M, (pa[keep], pa[keep]), 1.0); np.add.at(M, (pb[keep], pb[keep]), 1.0)
        np.add.at(M, (pa[keep], pb[keep]), -1.0); np.add.at(M, (pb[keep], pa[keep]), -1.0)
        np.add.at(rhs, pa[keep], dd[keep]); np.add.at(rhs, pb[keep], -dd[keep])
        M[0, :] = 0.0; M[0, 0] = 1.0; rhs[0] = 0.0        # gauge: first platform is the reference
        w = np.linalg.lstsq(M, rhs, rcond=None)[0]
        res = dd - (w[pa] - w[pb])
        mad = float(np.median(np.abs(res[keep]))) * 1.4826 if keep.any() else 0.0
        keep = np.abs(res) <= max(6.0, 3 * mad)
    w -= w.mean()
    cg = {g: float(np.clip(w[i] / 2, -AUTOCAL_CAP_DB, AUTOCAL_CAP_DB)) for g, i in gi.items()}
    c = {v: cg[groups[v]] for v in reports if groups.get(v) in cg}
    fixed = {a: {b: r - c.get(a, 0.0) + c.get(b, 0.0) for b, r in seen.items()} for a, seen in reports.items()}
    return fixed, c


def colocated_pairs(reports: Reports, p: Params) -> list[tuple[str, str, float, int]]:
    """Pairs of ids that look like ONE radio. Returns (u, v, spread_db, observers) with spread_db < p.colocation_db.

    Every honest observer o reports what it heard from u and from v. One transmitter advertising both ids (a relay: an
    in-room accomplice carrying an absent friend's id) gives every observer the same channel, so r_ou - r_ov is the same
    constant for all observers up to measurement noise (~2 dB). Two different people, even on one bench, differ by their own
    shadowing and geometry (~4-7 dB). The spread is the robust sd (1.4826 x MAD) of the differences, so a constant TX-power
    offset does not hide a relay and a few wild readings from lying observers cannot create or hide one.
    Observers' readings are used, never the pair's own reports about each other."""
    if p.colocation_db <= 0 or len(reports) < p.colocation_min_obs:
        return []
    obs = sorted(reports)
    ids = sorted({b for seen in reports.values() for b in seen})
    if len(ids) < 2:
        return []
    col = {v: i for i, v in enumerate(ids)}
    R = np.full((len(obs), len(ids)), np.nan)
    for i, o in enumerate(obs):
        for b, r in reports[o].items():
            if r >= p.colocation_min_dbm:
                R[i, col[b]] = r
    heard = np.isfinite(R).sum(0)                                  # observers that heard each id
    iu, ju = np.triu_indices(len(ids), 1)
    out = []
    BLOCK = max(1, 3_000_000 // max(len(obs), 1))
    for lo in range(0, len(iu), BLOCK):
        a, b = iu[lo:lo + BLOCK], ju[lo:lo + BLOCK]
        d = (R[:, a] - R[:, b]).T                                  # (pairs, observers), NaN where an observer missed one id
        n = np.isfinite(d).sum(1)
        ok = np.flatnonzero((n >= p.colocation_min_obs) & (n >= p.colocation_overlap * np.maximum(heard[a], heard[b])))
        if not ok.size:
            continue
        d = d[ok]
        with np.errstate(all="ignore"):
            med = np.nanmedian(d, axis=1)
            spread = 1.4826 * np.nanmedian(np.abs(d - med[:, None]), axis=1)
        for k in np.flatnonzero(spread < p.colocation_db):
            out.append((ids[a[ok[k]]], ids[b[ok[k]]], float(spread[k]), int(n[ok[k]])))
    return out


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


def disjoint_paths_many(seeds: Iterable[str], adj: dict[str, list[tuple[str, float]]], targets: Iterable[str],
                        limit: int) -> dict[str, int]:
    """For each target: max number (capped at `limit`) of internally vertex-disjoint paths from the seed set.

    Unit-capacity vertex splitting + augmenting paths (Edmonds-Karp). Seeds are teacher-verified, so several paths
    may start at the same seed; every non-seed vertex can carry at most one path (Menger's theorem).
    Integer-indexed residual network (arc i and its reverse i^1), built once; each target works on a flat copy of the
    capacity list, which is a single C-level copy - far cheaper than hashing tuple keys in the BFS."""
    seeds = set(seeds)
    INFC = limit + 1
    nodes = list(adj)
    idx = {v: i for i, v in enumerate(nodes)}
    S = 2 * len(nodes)                                   # in(v) = 2i, out(v) = 2i+1, super-source = 2N
    head: list[int] = []
    cap0: list[int] = []
    out_arcs: list[list[int]] = [[] for _ in range(S + 1)]

    def add(u: int, v: int, c: int):
        out_arcs[u].append(len(head)); head.append(v); cap0.append(c)
        out_arcs[v].append(len(head)); head.append(u); cap0.append(0)

    for u, lst in adj.items():
        i = idx[u]
        add(2 * i, 2 * i + 1, INFC if u in seeds else 1)
        for w, _ in lst:
            if w in idx:
                add(2 * i + 1, 2 * idx[w], 1)
    for sd in seeds:
        if sd in idx:
            add(S, 2 * idx[sd], INFC)

    out: dict[str, int] = {}
    for target in targets:
        if target in seeds:
            out[target] = limit
            continue
        if target not in idx or not out_arcs[S]:
            out[target] = 0
            continue
        sink = 2 * idx[target]
        cap = cap0[:]
        flow = 0
        while flow < limit:
            via = [-1] * (S + 1)                         # arc used to reach each vertex in this BFS
            via[S] = -2
            queue = [S]
            found = False
            for u in queue:
                for a in out_arcs[u]:
                    v = head[a]
                    if via[v] == -1 and cap[a] > 0:
                        via[v] = a
                        if v == sink:
                            found = True
                            break
                        queue.append(v)
                if found:
                    break
            if not found:
                break
            v = sink
            while v != S:
                a = via[v]
                cap[a] -= 1
                cap[a ^ 1] += 1
                v = head[a ^ 1]
            flow += 1
        out[target] = flow
    return out


def disjoint_paths(seeds: Iterable[str], adj: dict[str, list[tuple[str, float]]], target: str, limit: int) -> int:
    return disjoint_paths_many(seeds, adj, [target], limit)[target]


def _supported(nbrs: list[tuple[str, float]], p: Params) -> bool:
    """k independent witnesses, and (if enabled) at least near_k of them very close - a real student on a
    shared bench has a bench-mate within ~1 m; a phone on the far side of a wall or aisle does not."""
    if len(nbrs) < p.k:
        return False
    return p.near_m <= 0 or sum(1 for _, d in nbrs if d <= p.near_m) >= p.near_k


def evaluate(seeds: Iterable[str], reports: Reports, p: Params, groups: dict[str, str] | None = None) -> dict:
    """Run edge admission, flood, and iterative k-witness pruning.

    A non-seed node survives only if it is flood-reachable AND has >= k admitted
    edges to nodes that also survive. Pruning repeats to a fixed point.
    """
    seeds = list(dict.fromkeys(seeds))
    if p.autocal:
        reports, _ = self_calibrate(reports, groups)
    seed_set = set(seeds)
    colocated: dict[str, dict] = {}
    for u, v, spread, m in colocated_pairs(reports, p):
        for x, y in ((u, v), (v, u)):
            if x not in seed_set and (x not in colocated or spread < colocated[x]["spread_db"]):
                colocated[x] = {"partner": y, "spread_db": round(spread, 2), "observers": m}
    if colocated:                       # one radio cannot vouch for, or be vouched as, two different people
        reports = {a: {b: r for b, r in seen.items() if b not in colocated}
                   for a, seen in reports.items() if a not in colocated}
    edges = build_edges(reports, p)
    alive = set(flood(seeds, edges, p)) | set(seeds)
    while True:
        adj = _adjacency(edges, alive)
        drop = {v for v in alive if v not in seeds and not _supported(adj.get(v, []), p)}
        if p.independent:
            sub = {v: adj.get(v, []) for v in alive}
            flows = disjoint_paths_many(seeds, sub, [v for v in alive if v not in seeds and v not in drop], p.k)
            drop |= {v for v, f in flows.items() if f < p.k}
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
    return {"present": present, "edges": len(edges), "edge_list": edges, "colocated": colocated}
