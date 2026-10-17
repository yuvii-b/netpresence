"""Phone / app / OS layer: when each student taps, when the radio is on, who makes it into the check-in window."""
from __future__ import annotations

import math

import numpy as np

from netsim.config import RoomConfig


def tap_times(cfg: RoomConfig, g_tap: np.random.Generator, n: int) -> np.ndarray:
    """Each phone taps after a lognormal delay; a tap after check-in closes means the student never joins."""
    return g_tap.lognormal(math.log(cfg.tap_median_s), cfg.tap_sigma, n) if cfg.tap_median_s > 0 else np.zeros(n)
