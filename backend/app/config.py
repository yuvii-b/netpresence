import logging
import os

from dotenv import load_dotenv

load_dotenv()
_log = logging.getLogger("netpresence.config")


def _f(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


class Settings:
    MONGO_URL: str = os.getenv("MONGO_URL", "mongodb://localhost:27017")
    DB_NAME: str = os.getenv("DB_NAME", "netpresence")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # Shared secret the teacher app/dashboard sends as `X-Teacher-Token`.
    TEACHER_TOKEN: str = os.getenv("TEACHER_TOKEN", "dev-teacher-token")
    # Optional class enrolment code the teacher tells the class in person. When set, a phone can only enrol a roll
    # number if it also knows the code - stops someone outside the class squatting on roll numbers before their owners.
    ENROL_CODE: str = os.getenv("ENROL_CODE", "")

    # --- v1 acoustic ---
    TOKEN_VALIDITY_SECONDS: int = int(os.getenv("TOKEN_VALIDITY_SECONDS", "60"))

    # --- v2 proximity graph (defaults; overridable per session) ---
    # Roll-call timing, chosen with sim.platforms (students tap over several seconds, median ~4 s):
    #   check-in open WINDOW_SECONDS; every phone keeps discovering DISCOVERY_TAIL_SECONDS after check-in closes, so a
    #   student who taps at the last second still overlaps everyone for that long; then REPORT_GRACE_SECONDS to upload.
    WINDOW_SECONDS: int = int(os.getenv("WINDOW_SECONDS", "20"))
    DISCOVERY_TAIL_SECONDS: int = int(os.getenv("DISCOVERY_TAIL_SECONDS", "5"))
    REPORT_GRACE_SECONDS: int = int(os.getenv("REPORT_GRACE_SECONDS", "10"))
    RSSI_REF_DBM: float = _f("RSSI_REF_DBM", -59.0)    # A: RSSI at 1 m
    PATH_LOSS_N: float = _f("PATH_LOSS_N", 3.0)        # n: path-loss exponent
    MAX_EDGE_M: float = _f("MAX_EDGE_M", 2.0)          # chosen from sim.run: best leak vs coverage trade-off
    TTL_HOPS: int = int(os.getenv("TTL_HOPS", "8"))
    MAX_PATH_M: float = _f("MAX_PATH_M", 15.0)         # cumulative metres bound
    K_WITNESS: int = int(os.getenv("K_WITNESS", "2"))
    AGREE_DELTA_DB: float = _f("AGREE_DELTA_DB", 8.0)  # |rssi_ab - rssi_ba| bound
    # k vertex-disjoint paths from the seeds (default ON: corridor leakage with an open door 46% -> 4% in simulation)
    INDEPENDENT: bool = os.getenv("INDEPENDENT", "1") not in ("0", "false", "False")
    # Bench-mate rule (off by default: it cut corridor leakage only 42%->29% in simulation and cost coverage in sparse rooms)
    NEAR_M: float = _f("NEAR_M", 0.0)
    NEAR_K: int = int(os.getenv("NEAR_K", "1"))
    # per-phone TX/RX asymmetry solved from the session's own two-way readings (sim.platforms: 12 dB Android/iOS
    # imbalance 35% -> 0% false-absent). Default ON.
    COLOCATION_DB: float = float(os.getenv("COLOCATION_DB", "2.5"))   # relay/Sybil defence threshold (0 = off)
    AUTOCAL: bool = os.getenv("AUTOCAL", "1") not in ("0", "false", "False")

    # --- protocol v3: live roll call per subject (docs/PIVOT_PLAN.md) ---
    LIVE_REPORT_INTERVAL_MS: int = 1000   # phone uploads its current neighbour list this often (only if changed)
    LIVE_EVAL_DEBOUNCE_MS: int = 300      # server re-evaluates at most this often per session
    LIVE_MAX_SECONDS: int = int(os.getenv("LIVE_MAX_SECONDS", "120"))   # auto-finish
    LONGPOLL_WAIT_S: int = 25
    TOKEN_TTL_S: int = 12 * 3600          # bearer tokens (teacher code login, student signed login)
    LOGIN_MAX_FAILS: int = 5              # wrong teacher codes per LOGIN_WINDOW_S per IP
    LOGIN_WINDOW_S: int = 600
    SEED_DEMO: bool = os.getenv("NP_SEED_DEMO", "0") == "1"


settings = Settings()

if settings.TEACHER_TOKEN == "dev-teacher-token":
    _log.warning("TEACHER_TOKEN is the insecure default; set it in .env for any real deployment.")
