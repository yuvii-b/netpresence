"""BLE advertising-channel simulation (plan item 0.2): how many peers does a phone actually discover in the window?

Model (stylised, documented so the assumptions can be checked on real phones):
  * Every phone advertises on channels 37/38/39 once per advertising event (interval + 0..10 ms random advDelay),
    ~`airtime_ms` per packet, packets of one event spaced `ch_gap_ms` apart.
  * Every phone scans continuously, tuned to ONE channel per scan window, rotating 37->38->39 (random phase).
  * A packet is received iff the scanner is tuned to its channel at that time AND no other packet overlaps it
    on that channel (no capture effect - pessimistic) .
  * Half-duplex while transmitting and RF range are ignored (everyone in the room hears everyone).

Usage: python -m sim.ble [--trials 3]
"""
from __future__ import annotations

import argparse
import random
from bisect import bisect_left


def discovery_completeness(n: int, seconds: float = 15.0, adv_interval_ms: float = 150.0, adv_jitter_ms: float = 10.0,
                           airtime_ms: float = 0.4, ch_gap_ms: float = 0.5, scan_window_ms: float = 100.0,
                           scan_interval_ms: float = 100.0, seed: int = 0) -> float:
    rng = random.Random(seed)
    horizon = seconds * 1000
    pkts = {37: [], 38: [], 39: []}                # channel -> [(t, adv)]
    for a in range(n):
        t = rng.uniform(0, adv_interval_ms)
        while t < horizon:
            for i, ch in enumerate((37, 38, 39)):
                pkts[ch].append((t + i * ch_gap_ms, a))
            t += adv_interval_ms + rng.uniform(0, adv_jitter_ms)
    clean = {}                                       # channel -> sorted list of non-colliding (t, adv)
    for ch, lst in pkts.items():
        lst.sort()
        ok = []
        for i, (t, a) in enumerate(lst):
            hit = (i > 0 and t - lst[i - 1][0] < airtime_ms) or (i + 1 < len(lst) and lst[i + 1][0] - t < airtime_ms)
            if not hit:
                ok.append((t, a))
        clean[ch] = ok
    heard = [set() for _ in range(n)]
    phases = [rng.uniform(0, 3 * scan_interval_ms) for _ in range(n)]
    for ch_idx, ch in enumerate((37, 38, 39)):
        for t, a in clean[ch]:
            for s in range(n):
                if s == a or a in heard[s]:
                    continue
                x = t + phases[s]
                if int(x // scan_interval_ms) % 3 == ch_idx and (x % scan_interval_ms) < scan_window_ms:
                    heard[s].add(a)
    return sum(len(h) for h in heard) / (n * (n - 1)) if n > 1 else 1.0


# AOSP timings (ms). Advertise: LOW_POWER=1000, BALANCED=250, LOW_LATENCY=100 interval.
# Scan (window, interval): LOW_POWER=(512, 5120), BALANCED=(1024, 4096), LOW_LATENCY=(4096, 4096) i.e. continuous.
ADV_MODES = {"LOW_POWER(1000ms)": 1000, "BALANCED(250ms)": 250, "LOW_LATENCY(100ms)": 100}
SCAN_MODES = {"LOW_POWER": (512, 5120), "BALANCED": (1024, 4096), "LOW_LATENCY": (4096, 4096)}
# Active scanning: the id lives in the SCAN_RSP, so one discovery is ADV + SCAN_REQ + SCAN_RSP ~ 1 ms of vulnerable airtime.
ACTIVE_AIRTIME_MS = 1.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=3)
    a = ap.parse_args()
    T = a.trials

    def avg(n, secs, interval, airtime, win=100.0, per=100.0):
        return sum(discovery_completeness(n, secs, interval, airtime_ms=airtime, scan_window_ms=win,
                                          scan_interval_ms=per, seed=s) for s in range(T)) / T

    print(f"A) Advertise mode x crowd, continuous scan, ACTIVE scanning ({ACTIVE_AIRTIME_MS} ms exchange); mean of {T} runs")
    print(f"{'phones':>6} {'advertise mode':<20}| " + " ".join(f"{s:>6}s" for s in (5, 10, 15, 30)))
    for n in (30, 60, 80):
        for name, iv in ADV_MODES.items():
            print(f"{n:>6} {name:<20}| " + " ".join(f"{avg(n, sec, iv, ACTIVE_AIRTIME_MS):>7.1%}" for sec in (5, 10, 15, 30)))

    print("\nB) Scan mode (Android) at 60 phones, ADV BALANCED(250ms), active scanning")
    print(f"{'scan mode':<14}| " + " ".join(f"{s:>6}s" for s in (5, 10, 15, 30)))
    for name, (win, per) in SCAN_MODES.items():
        print(f"{name:<14}| " + " ".join(f"{avg(60, sec, 250, ACTIVE_AIRTIME_MS, win, per):>7.1%}" for sec in (5, 10, 15, 30)))
    print("\nNot modelled (measure on real phones, plan 0.2): OS scan throttling/duplicate filtering, "
          "capture effect, half-duplex, RF range, 2.4 GHz WiFi interference. iOS must scan with AllowDuplicates=true "
          "or it reports one RSSI per peer.")


if __name__ == "__main__":
    main()
