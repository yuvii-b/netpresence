"""E14 Energy per roll call: arithmetic on ASSUMED currents (no measurement yet); replace with a USB power-meter reading on a real phone."""
from __future__ import annotations

from netsim import config, plots
from netsim.experiments import common as C

# mA at ~3.85 V battery rail [assumed, typical datasheet/App-note orders of magnitude; to be measured]
CURRENT_MA = {"ble_scan_low_latency": 12.0, "ble_advertise_low_latency": 2.5, "radio_upload": 200.0, "mic_on": 25.0, "speaker_tone": 90.0, "screen_on": 120.0}
BATTERY_MAH = 4000.0
LECTURES_PER_DAY = 6


def mah(ma, s):
    return ma * s / 3600.0


def run(ctx):
    cfg = config.load("class93")
    on_s = cfg.window_s + cfg.tail_s
    up_s = 2.0
    np_ = mah(CURRENT_MA["ble_scan_low_latency"] + CURRENT_MA["ble_advertise_low_latency"] + CURRENT_MA["screen_on"], on_s) + mah(CURRENT_MA["radio_upload"], up_s)
    ac = mah(CURRENT_MA["mic_on"] + CURRENT_MA["screen_on"], cfg.window_s) + mah(CURRENT_MA["radio_upload"], up_s)
    qr = mah(CURRENT_MA["screen_on"], 10.0) + mah(CURRENT_MA["radio_upload"], up_s)
    rows = [{"method": n, "mAh": round(v, 4), "pct_day": round(100 * v * LECTURES_PER_DAY / BATTERY_MAH, 3)}
            for n, v in (("NetPresence", np_), ("acoustic v1 (student phone)", ac), ("rotating QR (student phone)", qr))]
    return {"assumed_ma": CURRENT_MA, "window_s": cfg.window_s, "radio_on_s": on_s, "battery_mah": BATTERY_MAH, "lectures_per_day": LECTURES_PER_DAY,
            "rows": rows, "check": rows}


def plot(res, figdir):
    return []


def table(res):
    h = ["method", "mAh per roll call", f"% of {int(res['battery_mah'])} mAh per day ({res['lectures_per_day']} lectures)"]
    rows = [[r["method"], r["mAh"], r["pct_day"]] for r in res["rows"]]
    return "All currents are ASSUMED (no power measurement yet).\n\n" + C.md_table(h, rows), C.latex_table(h, rows, "Energy per roll call (assumed currents).", "tab:e14")


EXPERIMENT = {"id": "E14", "title": "Energy", "question": "What does one roll call cost a student's battery?",
              "trials_quick": 1, "trials_full": 1, "run": run, "plot": plot, "table": table}
