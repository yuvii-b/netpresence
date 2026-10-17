"""PHY: mean received power between every pair of phones (path loss, bodies, wall/door, symmetric shadowing)."""
from __future__ import annotations

import numpy as np

from netsim.config import RoomConfig


def positions(nodes: dict):
    ids = list(nodes)
    P = np.array([nodes[k]["pos"] for k in ids], dtype=float)
    return ids, P


def pair_mean_rssi(cfg: RoomConfig, nodes: dict, wall: tuple, g_shadow: np.random.Generator):
    """Mean RSSI (before phone gains) for every unordered pair (iu < ju).

    Returns (iu, ju, d, mean): pair indices into list(nodes), distance in m, and
    mean = A - 10 n log10(d) - body loss - wall loss + shadow_ij, with shadow_ij the same for both directions."""
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
    loss = cfg.body_db * np.minimum(bodies, cfg.body_cap)
    crosses = (A[:, 0] < wall_x) != (B[:, 0] < wall_x)
    with np.errstate(divide="ignore", invalid="ignore"):
        tt = (wall_x - A[:, 0]) / (B[:, 0] - A[:, 0])
    y_cross = A[:, 1] + tt * (B[:, 1] - A[:, 1])
    through_door = (door is not None) & (y_cross >= (door[0] if door else 0)) & (y_cross <= (door[1] if door else 0))
    loss = loss + np.where(crosses & ~through_door, cfg.wall_db, 0.0)
    mean = cfg.A - 10 * cfg.n * np.log10(d) - loss + g_shadow.normal(0, cfg.shadow_sigma, d.shape)
    return iu, ju, d, mean
