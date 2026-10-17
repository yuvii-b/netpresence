"""The protocol as the REAL code implements it - read from the sources, never copied by hand.

The simulator must always model the system that is actually in the repo. Every protocol constant the simulator depends on
is read here from the file that defines it (server settings, phone TypeScript core, Android Kotlin, iOS Objective-C). If
a source changes shape so a value can no longer be found, importing this module fails loudly instead of letting the
simulator silently drift. tests/test_parity.py checks that the simulator's defaults and assumptions match these values.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.config import settings
from app.models.schemas import Report

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "mobile" / "core" / "src"
ANDROID = ROOT / "mobile" / "app" / "android" / "app" / "src" / "main" / "java" / "com" / "netpresence" / "NetPresenceModule.kt"
IOS = ROOT / "mobile" / "app" / "ios" / "NetPresence" / "NetPresenceNative.m"

# AOSP constants (android.bluetooth.le) - documented values, used to translate the mode names found in the Kotlin code
AOSP_ADV_INTERVAL_MS = {"ADVERTISE_MODE_LOW_LATENCY": 100, "ADVERTISE_MODE_BALANCED": 250, "ADVERTISE_MODE_LOW_POWER": 1000}
AOSP_SCAN_WINDOW_INTERVAL_MS = {"SCAN_MODE_LOW_LATENCY": (4096, 4096), "SCAN_MODE_BALANCED": (1024, 4096),
                                "SCAN_MODE_LOW_POWER": (512, 5120)}


def _find(path: Path, pattern: str, what: str) -> str:
    text = path.read_text(encoding="utf-8")
    m = re.search(pattern, text)
    if not m:
        raise ImportError(f"protocol drift: cannot find {what} in {path.relative_to(ROOT)} (pattern {pattern!r})")
    return m.group(1)


def _contains(path: Path, needle: str) -> bool:
    return needle in path.read_text(encoding="utf-8")


# --- timing (server is the authority) ---------------------------------------------------------------------------------
WINDOW_S = float(settings.WINDOW_SECONDS)
TAIL_S = float(settings.DISCOVERY_TAIL_SECONDS)
GRACE_S = float(settings.REPORT_GRACE_SECONDS)

# --- phone core (TypeScript) ---------------------------------------------------------------------------------------------
MIN_SAMPLES = int(_find(CORE / "aggregate.ts", r"neighbours\(minSamples = (\d+)", "NeighbourCollector minSamples default"))
MAX_NEIGHBOURS = int(_find(CORE / "aggregate.ts", r"MAX_NEIGHBOURS = (\d+)", "MAX_NEIGHBOURS"))
PER_PEER_SAMPLE_CAP = None   # aggregate.ts keeps every sample per peer; test_parity fails if a cap appears there
RETRY_START_MS = int(_find(CORE / "session.ts", r"let delay = (\d+);", "submitReport first retry delay"))
RETRY_MAX_MS = int(_find(CORE / "session.ts", r"delay = Math\.min\(delay \* 2, (\d+)\)", "submitReport max retry delay"))
SERVICE_PREFIX = _find(CORE / "ble.ts", r"SERVICE_PREFIX = '([0-9a-f-]+)'", "on-air UUID prefix")
SERVER_MAX_NEIGHBOURS = Report.model_fields["neighbours"].metadata[0].max_length

# --- Android radio (Kotlin) ------------------------------------------------------------------------------------------------
ANDROID_ADV_MODE = _find(ANDROID, r"setAdvertiseMode\(AdvertiseSettings\.(\w+)\)", "Android advertise mode")
ANDROID_TX_POWER = _find(ANDROID, r"setTxPowerLevel\(AdvertiseSettings\.(\w+)\)", "Android TX power level")
ANDROID_SCAN_MODE = _find(ANDROID, r"setScanMode\(ScanSettings\.(\w+)\)", "Android scan mode")
ANDROID_ADV_MS = AOSP_ADV_INTERVAL_MS[ANDROID_ADV_MODE]
ANDROID_SCAN_CONTINUOUS = AOSP_SCAN_WINDOW_INTERVAL_MS[ANDROID_SCAN_MODE][0] == AOSP_SCAN_WINDOW_INTERVAL_MS[ANDROID_SCAN_MODE][1]
# single-packet identity: the advert carries only the service UUID (no scan response, no name, no manufacturer data)
ANDROID_SINGLE_PACKET = (_contains(ANDROID, "addServiceUuid(ParcelUuid(uuid))")
                         and not _contains(ANDROID, "addManufacturerData")
                         and _contains(ANDROID, "setIncludeDeviceName(false)"))

# --- iOS radio (Objective-C) -----------------------------------------------------------------------------------------------
IOS_SINGLE_PACKET = (_contains(IOS, "startAdvertising:@{CBAdvertisementDataServiceUUIDsKey")
                     and not _contains(IOS, "CBAdvertisementDataLocalNameKey :"))
IOS_ALLOW_DUPLICATES = _contains(IOS, "CBCentralManagerScanOptionAllowDuplicatesKey : @YES")
IOS_MODEL_PREFIX = _find(IOS, r'stringWithFormat:@"(\w+) %s", u\.machine', "iOS deviceModel prefix")

# --- on-air size -> airtime (BLE Core spec, LE 1M PHY) -------------------------------------------------------------------
ADV_PAYLOAD_BYTES = 6 + 3 + 18      # AdvA + flags AD + 128-bit service UUID AD
ADV_AIRTIME_MS = (1 + 4 + 2 + ADV_PAYLOAD_BYTES + 3) * 8 / 1000.0
