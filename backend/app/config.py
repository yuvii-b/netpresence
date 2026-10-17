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

    # --- v1 acoustic ---
    TOKEN_VALIDITY_SECONDS: int = int(os.getenv("TOKEN_VALIDITY_SECONDS", "60"))

    # --- v2 proximity graph (defaults; overridable per session) ---
    WINDOW_SECONDS: int = int(os.getenv("WINDOW_SECONDS", "45"))      # check-in + discovery
    REPORT_GRACE_SECONDS: int = int(os.getenv("REPORT_GRACE_SECONDS", "15"))
    RSSI_REF_DBM: float = _f("RSSI_REF_DBM", -59.0)    # A: RSSI at 1 m
    PATH_LOSS_N: float = _f("PATH_LOSS_N", 3.0)        # n: path-loss exponent
    MAX_EDGE_M: float = _f("MAX_EDGE_M", 3.0)          # ~10 ft hop
    TTL_HOPS: int = int(os.getenv("TTL_HOPS", "8"))
    MAX_PATH_M: float = _f("MAX_PATH_M", 15.0)         # cumulative metres bound
    K_WITNESS: int = int(os.getenv("K_WITNESS", "2"))
    AGREE_DELTA_DB: float = _f("AGREE_DELTA_DB", 8.0)  # |rssi_ab - rssi_ba| bound


settings = Settings()

if settings.TEACHER_TOKEN == "dev-teacher-token":
    _log.warning("TEACHER_TOKEN is the insecure default; set it in .env for any real deployment.")
