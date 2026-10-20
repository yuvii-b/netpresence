"""Configuration for every layer, named presets and CLI/TOML overrides.

Every field of RoomConfig has a provenance tag in TAGS: "measured" (fitted from real phones), "spec" (from a standard,
AOSP or the repo's own code), or "assumed" (a documented guess that experiment E08 sweeps). tests/netsim/test_config.py
fails if a field has no tag, so the paper can always say which numbers are real.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields, replace
from pathlib import Path

from sim import protocol   # every protocol constant comes from the real code (see sim/protocol.py)

PRESET_DIR = Path(__file__).resolve().parent / "presets"


@dataclass
class RoomConfig:
    # layout="bench": Indian-classroom style - bench COLUMNS facing the front, several students per bench,
    # aisles between bench columns. layout="grid": uniform seat grid (rows x cols), kept for comparison.
    layout: str = "bench"
    bench_cols: int = 3           # columns of benches (left / middle / right)
    bench_rows: int = 8           # benches front -> back in each column: 3 x 8 x 4 = 96 seats
    seats_per_bench: int = 4
    capacity: int = 93            # the room never holds more than this many students
    students: int | None = None   # exact head-count to seat (<= capacity); None = use `occupancy`
    seat_pitch: float = 0.5       # m between students sharing a bench (shoulder to shoulder)
    aisle: float = 0.8            # m gap between bench columns
    bench_pitch_y: float = 1.1    # m between consecutive benches (bench + legroom)
    seed_col: int | None = None   # which bench column's FRONT bench the teacher verifies (None = middle)
    fill: str = "random"          # "random": each seat taken with prob=occupancy; "column": column by column, front first
    door_open: bool = True        # the door is an opening in the side wall: no wall loss along it
    door_width: float = 1.0
    rows: int = 6                 # grid layout only
    cols: int = 10
    pitch_x: float = 0.9
    pitch_y: float = 1.2
    occupancy: float = 0.9
    A: float = -59.0
    n: float = 3.0
    shadow_sigma: float = 5.0     # dB, symmetric per pair
    dir_sigma: float = 1.0        # dB, per-direction residue that more samples cannot average away
    fast_sigma: float = 4.0       # dB, per-sample fast fading; the median of m samples has ~1.25*fast_sigma/sqrt(m)
    body_db: float = 3.0
    body_cap: int = 3
    body_radius: float = 0.35
    body_max_m: float = 8.0       # body blocking only computed for pairs closer than this (speed)
    wall_db: float = 12.0
    sensitivity: float = -95.0
    p_detect: float = 0.97        # extra chance a pair is heard at all (OS hiccups not modelled below)
    window_s: float = protocol.WINDOW_S          # check-in window: a student tapping later is absent
    tail_s: float = protocol.TAIL_S              # phones keep discovering this long after check-in closes
    tap_median_s: float = 4.0     # students tap "Mark me present" after a lognormal delay (median, s); 0 = all at t=0
    tap_sigma: float = 0.6        #   log-sd of that delay (90th percentile ~ 2.2 x median)
    startup_s: float = 1.0        # tap -> radio on (check-in round trip, permissions already granted)
    min_samples: int = protocol.MIN_SAMPLES      # NeighbourCollector default (mobile/core/src/aggregate.ts)
    sample_cap: int | None = protocol.PER_PEER_SAMPLE_CAP   # None: the phone keeps every sample per peer
    airtime_ms: float = protocol.ADV_AIRTIME_MS  # one advert: AdvA + flags + 128-bit UUID (identity inside the UUID)
    n_outside: int = 8            # phones just past the wall (corridor / next class)
    # Phone models: platform, receiver gain rx, transmit power tx (dB, relative), advertising interval, scan efficiency.
    # Android: LOW_LATENCY advertising (100 ms) + LOW_LATENCY scanning. iOS: interval not settable (assumed 150 ms),
    # duplicate reports possibly coalesced (scan_eff 0.6), fixed TX power assumed +3 dB over Android HIGH.
    models: dict = field(default_factory=lambda: {
        "ref":    {"platform": "android", "rx": 0.0, "tx": 0.0, "adv_ms": float(protocol.ANDROID_ADV_MS), "scan_eff": 0.95},
        "lowend": {"platform": "android", "rx": -4.0, "tx": -2.0, "adv_ms": float(protocol.ANDROID_ADV_MS), "scan_eff": 0.75},
        "iphone": {"platform": "ios", "rx": -9.0, "tx": 3.0, "adv_ms": 150.0, "scan_eff": 0.6},
    })
    model_mix: tuple = (0.55, 0.30, 0.15)
    ios_share: float | None = None  # override: fraction of iPhones (Android models keep their relative mix)
    n_seeds: int = 4              # grid layout; the bench layout verifies the whole front bench
    # --- channel realism (M2). Defaults reproduce the original independent-shadowing model exactly.
    shadow_model: str = "iid"     # "iid": independent per pair (original) | "gudmundson": spatially correlated, reciprocal
    d_corr: float = 1.0           # m, shadowing correlation distance (gudmundson)
    orient_mix: tuple = (1.0, 0.0, 0.0, 0.0)   # share of phones held in hand / on desk / in pocket / in bag
    orient_db: tuple = (0.0, 2.0, 6.0, 10.0)   # extra loss of each way of holding a phone, per end of the link
    channel: str = "parametric"   # "parametric" | "trace" (empirical RSSI tables from the BLE lab, netsim/traces.py)
    trace_file: str | None = None  # BLE-lab CSV v2 (file or directory of them) used when channel = "trace"
    trace_orientation: str = "desk"  # which orientation's rows of the trace file to draw from
    # --- BLE link layer (M3). ble_mode "fast" = analytical Poisson model; "des" = packet-level discrete-event model.
    ble_mode: str = "fast"
    capture: bool = False         # des: the stronger of two overlapping PDUs survives if it is capture_db above the rest
    capture_db: float = 6.0
    adv_delay_max_ms: float = 10.0   # BLE Core Vol 6 B 4.4.2.2: advDelay ~ U(0, 10 ms) added to every advertising interval
    t_ifs_adv_ms: float = 0.4     # gap between the 37 / 38 / 39 PDUs of one advertising event
    p_bg: tuple = (0.05, 0.10, 0.05)   # chance a PDU on channel 37 / 38 / 39 hits 2.4 GHz background traffic (Wi-Fi ch. 6 ~ 38)
    ios_scan_dwell_ms: float = 30.0    # iOS scans continuously, hopping channel every dwell
    ios_min_report_ms: float = 0.0     # iOS may coalesce duplicate reports of one peer: at most one per this many ms (0 = all)
    rician_k_db: float = 3.0      # per-PDU fast fading
    # --- uplink (M4). "ideal" = every report arrives; otherwise a profile or mix, e.g. "wifi_congested" or "wifi_good:0.7,cell_4g:0.3"
    uplink: str = "ideal"
    upload_jitter_s: float = 0.0  # each phone waits U(0, J) before its first upload attempt (J = 0 is what the app does today)


TAGS: dict[str, str] = {
    # geometry: the author's classroom description (3 columns x 8 benches x 4 seats, 93 students)
    "layout": "spec", "bench_cols": "spec", "bench_rows": "spec", "seats_per_bench": "spec", "capacity": "spec",
    "students": "spec", "seat_pitch": "assumed", "aisle": "assumed", "bench_pitch_y": "assumed", "seed_col": "spec",
    "fill": "spec", "door_open": "spec", "door_width": "assumed", "rows": "spec", "cols": "spec", "pitch_x": "assumed",
    "pitch_y": "assumed", "occupancy": "spec", "n_outside": "assumed",
    # radio: every one of these is replaced by a fit from the BLE lab (tools/fit_pathloss.py) once measured
    "A": "assumed", "n": "assumed", "shadow_sigma": "assumed", "dir_sigma": "assumed", "fast_sigma": "assumed",
    "body_db": "assumed", "body_cap": "assumed", "body_radius": "assumed", "body_max_m": "assumed", "wall_db": "assumed",
    "sensitivity": "spec", "p_detect": "assumed",
    # timing and protocol: read from the code by sim.protocol
    "window_s": "spec", "tail_s": "spec", "min_samples": "spec", "sample_cap": "spec", "airtime_ms": "spec",
    # humans and phones
    "tap_median_s": "assumed", "tap_sigma": "assumed", "startup_s": "assumed",
    "models": "assumed", "model_mix": "assumed", "ios_share": "assumed", "n_seeds": "spec",
    "shadow_model": "assumed", "d_corr": "assumed", "orient_mix": "assumed", "orient_db": "assumed",
    "channel": "spec", "trace_file": "spec", "trace_orientation": "spec",
    "ble_mode": "spec", "capture": "assumed", "capture_db": "assumed", "adv_delay_max_ms": "spec", "t_ifs_adv_ms": "assumed",
    "uplink": "assumed", "upload_jitter_s": "spec",
    "p_bg": "assumed", "ios_scan_dwell_ms": "assumed", "ios_min_report_ms": "assumed", "rician_k_db": "assumed",
}


def assumed_fields() -> list[str]:
    return sorted(k for k, v in TAGS.items() if v == "assumed")


# --- presets (section 3.1) ---------------------------------------------------------------------------------------------
PRESETS: dict[str, dict] = {
    "class93": {"students": 93},
    "class60": {"students": 60},
    "class35": {"students": 35},
    "class20": {"students": 20},
    "lab6": {"layout": "bench", "bench_cols": 1, "bench_rows": 2, "seats_per_bench": 4, "capacity": 8, "students": 6,
             "n_outside": 2},
    "exam": {"students": 46},      # every second seat of the 93-seat room
}


def _coerce(cfg: RoomConfig, key: str, value):
    names = {f.name for f in fields(cfg)}
    if key not in names:
        raise KeyError(f"unknown RoomConfig field {key!r}")
    cur = getattr(cfg, key)
    if isinstance(value, str) and not isinstance(cur, str):
        low = value.lower()
        if low in ("none", "null"):
            return None
        if low in ("true", "false"):
            return low == "true"
        if isinstance(cur, bool):
            raise ValueError(f"{key}: expected true/false, got {value!r}")
        try:
            return int(value) if isinstance(cur, int) and not isinstance(cur, bool) else float(value)
        except ValueError:
            raise ValueError(f"{key}: cannot read {value!r}") from None
    return value


def apply(cfg: RoomConfig, overrides: dict) -> RoomConfig:
    """Return cfg with `overrides` applied (values may be strings from the CLI). Dotted `models.iphone.tx` edits a model."""
    cfg = replace(cfg)
    for k, v in overrides.items():
        if k.startswith("models."):
            _, name, attr = k.split(".", 2)
            models = {m: dict(d) for m, d in cfg.models.items()}
            models[name][attr] = float(v) if attr != "platform" else str(v)
            cfg = replace(cfg, models=models)
        else:
            cfg = replace(cfg, **{k: _coerce(cfg, k, v)})
    return cfg


def load(preset: str = "class93", toml: str | Path | None = None, overrides: dict | None = None) -> RoomConfig:
    """Preset (code table or presets/<name>.toml), optional TOML file, then overrides."""
    base: dict = {}
    if preset in PRESETS:
        base = dict(PRESETS[preset])
    elif (PRESET_DIR / f"{preset}.toml").is_file():
        base = tomllib.loads((PRESET_DIR / f"{preset}.toml").read_text(encoding="utf-8"))
    else:
        raise KeyError(f"unknown preset {preset!r}; known: {', '.join(sorted(PRESETS))}")
    if toml is not None:
        base.update(tomllib.loads(Path(toml).read_text(encoding="utf-8")))
    base.update(overrides or {})
    return apply(RoomConfig(), base)
