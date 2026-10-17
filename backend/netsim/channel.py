"""PHY: mean received power between every pair of phones (path loss, bodies, wall/door, shadowing, orientation).

Mean RSSI of i hearing j (before the phones' own rx/tx gains):
    A - 10 n log10(d) - L_body - L_wall - L_orient(i) - L_orient(j) + S_ij
Two shadowing models:
  * "iid"       - S_ij independent per pair, N(0, sigma) (the original model; keeps the old acceptance results exact).
  * "gudmundson" - S_ij = sigma (z_i + z_j + w_ij) / sqrt(3 + 2 rho_ij), z a spatial Gaussian field sampled at the phones
                  (correlation rho = exp(-dist / d_corr)), w iid N(0,1). Var(S_ij) = sigma^2 for every pair, S_ij = S_ji, and
                  two phones near each other see correlated links, which matters for co-location tests.
Or, with channel="trace", the pair's mean is drawn from empirical tables built from real measurements (netsim/traces.py).
"""
from __future__ import annotations

import numpy as np

from netsim.config import RoomConfig


def positions(nodes: dict):
    ids = list(nodes)
    P = np.array([nodes[k]["pos"] for k in ids], dtype=float)
    return ids, P


def correlated_shadowing(cfg: RoomConfig, P: np.ndarray, iu: np.ndarray, ju: np.ndarray, d: np.ndarray,
                         g: np.random.Generator) -> np.ndarray:
    """Gudmundson pair shadowing in dB for the pairs (iu, ju). Reciprocal by construction."""
    N = len(P)
    D = np.linalg.norm(P[:, None, :] - P[None, :, :], axis=2)
    C = np.exp(-D / cfg.d_corr) + 1e-9 * np.eye(N)
    z = np.linalg.cholesky(C) @ g.normal(0, 1, N)
    w = g.normal(0, 1, d.shape)
    rho = np.exp(-d / cfg.d_corr)
    return cfg.shadow_sigma * (z[iu] + z[ju] + w) / np.sqrt(3.0 + 2.0 * rho)


def orientation_loss(cfg: RoomConfig, N: int, g: np.random.Generator) -> np.ndarray:
    """Per-phone extra loss in dB from how the phone is carried."""
    p = np.array(cfg.orient_mix, dtype=float)
    return np.array(cfg.orient_db, dtype=float)[g.choice(len(p), size=N, p=p / p.sum())]


def pair_geometry(cfg: RoomConfig, nodes: dict, wall: tuple):
    """Pair indices, distance, body count and wall flag for every unordered pair (iu < ju)."""
    wall_x, door = wall
    ids, P = positions(nodes)
    N = len(ids)
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
    crosses = (A[:, 0] < wall_x) != (B[:, 0] < wall_x)
    with np.errstate(divide="ignore", invalid="ignore"):
        tt = (wall_x - A[:, 0]) / (B[:, 0] - A[:, 0])
    y_cross = A[:, 1] + tt * (B[:, 1] - A[:, 1])
    through_door = (door is not None) & (y_cross >= (door[0] if door else 0)) & (y_cross <= (door[1] if door else 0))
    walled = crosses & ~through_door
    return P, iu, ju, d, bodies, walled


def pair_mean_rssi(cfg: RoomConfig, nodes: dict, wall: tuple, g_shadow: np.random.Generator,
                   g_orient: np.random.Generator | None = None, stats: dict | None = None):
    """Mean RSSI (before phone gains) for every unordered pair. Returns (iu, ju, d, mean).

    `stats`, if given, receives {"trace_fallbacks": number of pairs that fell back to the parametric model}."""
    P, iu, ju, d, bodies, walled = pair_geometry(cfg, nodes, wall)
    if cfg.channel == "trace":
        from netsim import traces
        mean, fallbacks = traces.draw_pair_means(cfg, d, bodies, walled, g_shadow)
        if stats is not None:
            stats["trace_fallbacks"] = int(fallbacks)
        return iu, ju, d, mean
    loss = cfg.body_db * np.minimum(bodies, cfg.body_cap) + np.where(walled, cfg.wall_db, 0.0)
    if g_orient is not None and cfg.orient_mix != (1.0, 0.0, 0.0, 0.0):
        lo = orientation_loss(cfg, len(P), g_orient)
        loss = loss + lo[iu] + lo[ju]
    if cfg.shadow_model == "gudmundson":
        shadow = correlated_shadowing(cfg, P, iu, ju, d, g_shadow)
    elif cfg.shadow_model == "iid":
        shadow = g_shadow.normal(0, cfg.shadow_sigma, d.shape)
    else:
        raise ValueError(f"unknown shadow_model {cfg.shadow_model!r}")
    mean = cfg.A - 10 * cfg.n * np.log10(d) - loss + shadow
    return iu, ju, d, mean
