"""The simulator must model the system that is actually in the repo.

sim/protocol.py reads every protocol constant from the real sources (server settings, TypeScript core, Kotlin, Obj-C).
These tests fail whenever the simulator's defaults or its modelling assumptions stop matching the code - change the
code and the simulator together, in the same commit.
"""
import re

from app.routers.sessions import advertise_uuid
from app.services.graph import platform_of
from sim import protocol as P
from sim.room import RoomConfig


def test_sim_timing_and_collector_come_from_the_code():
    c = RoomConfig()
    assert (c.window_s, c.tail_s) == (P.WINDOW_S, P.TAIL_S)
    assert c.min_samples == P.MIN_SAMPLES
    assert c.sample_cap == P.PER_PEER_SAMPLE_CAP
    assert abs(c.airtime_ms - P.ADV_AIRTIME_MS) < 1e-12


def test_phone_keeps_every_sample_per_peer():
    # the simulator assumes no per-peer cap; if aggregate.ts starts capping, set PER_PEER_SAMPLE_CAP to match
    src = (P.CORE / "aggregate.ts").read_text(encoding="utf-8")
    add_body = src[src.index("add(s: RadioSample)"):src.index("neighbours(")]
    assert ".length" not in add_body and "shift(" not in add_body and "splice(" not in add_body


def test_neighbour_limits_agree_between_phone_and_server():
    assert P.MAX_NEIGHBOURS == P.SERVER_MAX_NEIGHBOURS


def test_android_radio_matches_the_sim_profiles():
    c = RoomConfig()
    android = [m for m in c.models.values() if m["platform"] == "android"]
    assert android and all(m["adv_ms"] == P.ANDROID_ADV_MS for m in android)
    # the profiles' scan efficiency and TX values assume these exact settings
    assert P.ANDROID_SCAN_CONTINUOUS, "sim assumes continuous LOW_LATENCY scanning"
    assert P.ANDROID_TX_POWER == "ADVERTISE_TX_POWER_HIGH", "sim tx profiles assume Android advertises at HIGH"


def test_single_packet_identity_on_both_platforms():
    # the airtime / collision model assumes one advert with only the service UUID (no scan response, name or mfr data)
    assert P.ANDROID_SINGLE_PACKET and P.IOS_SINGLE_PACKET
    assert P.IOS_ALLOW_DUPLICATES, "sim assumes iOS reports an RSSI series, not one sample per peer"
    assert advertise_uuid("1a2b3c4d") == P.SERVICE_PREFIX + "1a2b3c4d"


def test_platform_detection_matches_what_the_apps_send():
    assert platform_of(f"{P.IOS_MODEL_PREFIX} iPhone14,5") == "ios"
    kt = P.ANDROID.read_text(encoding="utf-8")
    assert re.search(r'promise\.resolve\("\$\{Build\.MANUFACTURER\} \$\{Build\.MODEL\}"\)', kt)
    for maker in ("samsung Galaxy A14", "Xiaomi Redmi Note 12", "OPPO A78", "vivo Y27", "realme C55", "Google Pixel 6a"):
        assert platform_of(maker) == "android", maker
    # every sim model name maps to the platform its profile claims
    for name, prof in RoomConfig().models.items():
        assert platform_of(name) == prof["platform"], name


def test_native_scanners_report_every_uuid_match_not_just_the_first():
    # the co-location defence (graph.colocated_pairs) and netsim's relay model rely on a phone reporting BOTH ids when one
    # advert carries two NetPresence UUIDs
    kt = P.ANDROID.read_text(encoding="utf-8")
    line = next(l for l in kt.splitlines() if 'push("NP-" + u.substring(prefix.length)' in l)
    assert "return" not in line.split("//")[0]
    m = P.IOS.read_text(encoding="utf-8")
    block = m[m.index("didDiscoverPeripheral"):m.index("peripheralManagerDidUpdateState")]
    assert "return;" not in block


def test_live_flow_constants_come_from_the_code():
    assert P.LIVE_REPORT_INTERVAL_MS == P.SERVER_LIVE_REPORT_INTERVAL_MS == 1000   # phone and server agree
    assert P.LIVE_TICK_MS <= 100 and P.LIVE_MIN_SAMPLES >= 1
    assert P.ANDROID_FLUSH_MS == P.IOS_FLUSH_MS == 100          # a sample reaches the reporter within 100 ms
