"""Statistics for the paper: the classroom is the unit, 95% bootstrap CIs, paired comparisons.

A classroom is one trial. A rate such as false-absent is the pooled ratio sum(false_absent) / sum(inside) over classrooms; its
confidence interval comes from resampling CLASSROOMS (not students: students in one room are not independent). Comparing two
variants uses the same resampled classrooms for both (paired bootstrap), which is valid because every variant sees the same
seeds (common random numbers).
"""
from __future__ import annotations

import numpy as np

N_BOOT = 2000
ALPHA = 0.05


def _rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(np.random.SeedSequence([20260101, seed]))


def ratio_ci(num, den, n_boot: int = N_BOOT, seed: int = 0) -> dict:
    """Pooled rate num/den with a bootstrap CI over classrooms. Returns {"est", "lo", "hi", "n"} (fractions, 0..1)."""
    num, den = np.asarray(num, float), np.asarray(den, float)
    n = len(num)
    if n == 0:
        return {"est": float("nan"), "lo": float("nan"), "hi": float("nan"), "n": 0}
    est = num.sum() / max(den.sum(), 1.0)
    idx = _rng(seed).integers(0, n, (n_boot, n))
    b = num[idx].sum(1) / np.maximum(den[idx].sum(1), 1.0)
    return {"est": float(est), "lo": float(np.quantile(b, ALPHA / 2)), "hi": float(np.quantile(b, 1 - ALPHA / 2)), "n": n}


def mean_ci(x, n_boot: int = N_BOOT, seed: int = 0) -> dict:
    """Mean of a per-classroom quantity (time, samples per pair, ...) with a bootstrap CI over classrooms."""
    x = np.asarray(x, float)
    n = len(x)
    if n == 0:
        return {"est": float("nan"), "lo": float("nan"), "hi": float("nan"), "n": 0}
    idx = _rng(seed).integers(0, n, (n_boot, n))
    b = x[idx].mean(1)
    return {"est": float(x.mean()), "lo": float(np.quantile(b, ALPHA / 2)), "hi": float(np.quantile(b, 1 - ALPHA / 2)), "n": n}


def paired_diff_ci(num_a, den_a, num_b, den_b, n_boot: int = N_BOOT, seed: int = 0) -> dict:
    """rate(A) - rate(B) over the SAME classrooms, with a paired bootstrap CI. "significant" = the CI excludes 0."""
    na, da, nb, db = (np.asarray(v, float) for v in (num_a, den_a, num_b, den_b))
    n = len(na)
    if n == 0 or n != len(nb):
        raise ValueError("paired comparison needs the same classrooms for both variants")
    est = na.sum() / max(da.sum(), 1.0) - nb.sum() / max(db.sum(), 1.0)
    idx = _rng(seed).integers(0, n, (n_boot, n))
    b = na[idx].sum(1) / np.maximum(da[idx].sum(1), 1.0) - nb[idx].sum(1) / np.maximum(db[idx].sum(1), 1.0)
    lo, hi = float(np.quantile(b, ALPHA / 2)), float(np.quantile(b, 1 - ALPHA / 2))
    return {"est": float(est), "lo": lo, "hi": hi, "significant": bool(lo > 0 or hi < 0), "n": n}


def pct(ci: dict, digits: int = 2) -> str:
    """'0.28% [0.00, 0.62]' for a ratio_ci result."""
    return f"{100 * ci['est']:.{digits}f}% [{100 * ci['lo']:.{digits}f}, {100 * ci['hi']:.{digits}f}]"


def quantiles(x, qs=(0.5, 0.95)) -> list[float]:
    x = np.asarray(x, float)
    return [float(np.quantile(x, q)) for q in qs] if len(x) else [float("nan")] * len(qs)
