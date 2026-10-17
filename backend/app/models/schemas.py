from typing import Literal, Optional

from pydantic import BaseModel, Field

SESSION_ID_PATTERN = r"^[A-Za-z0-9\-]{1,64}$"
STUDENT_ID_PATTERN = r"^[A-Za-z0-9 _.\-@]{1,64}$"
PEER_ID_PATTERN = r"^[0-9a-f]{8}$"
MODEL_PATTERN = r"^[A-Za-z0-9 _.\-]{1,64}$"
B64 = r"^[A-Za-z0-9+/=]{1,512}$"

# ---------------- v1 acoustic (tone alphabet in frontend/src/audio/toneEncoder.js) ----------------
TOKEN_PATTERN = r"^[0-9A-Z]{1,8}$"


class AcousticStartRequest(BaseModel):
    session_id: str = Field(..., pattern=SESSION_ID_PATTERN)
    token: str = Field(..., pattern=TOKEN_PATTERN)


class AcousticSubmitRequest(BaseModel):
    session_id: str = Field(..., pattern=SESSION_ID_PATTERN)
    student_id: str = Field(..., pattern=STUDENT_ID_PATTERN)
    decoded_token: str = Field(..., pattern=TOKEN_PATTERN)


class AcousticTrial(BaseModel):
    """One v1 listening attempt, logged for the dead-end characterisation (plan phase 4)."""
    session_id: str = Field(..., pattern=SESSION_ID_PATTERN)
    success: bool
    distance_m: Optional[float] = Field(None, ge=0, le=100)
    device_model: Optional[str] = Field(None, pattern=MODEL_PATTERN)
    os: Optional[str] = Field(None, max_length=16)
    fan_on: Optional[bool] = None
    seat_position: Optional[Literal["front", "middle", "back"]] = None
    time_to_detect_ms: Optional[int] = Field(None, ge=0)
    best_snr: Optional[float] = None
    snr_threshold: Optional[float] = None


# ---------------- v2 proximity graph ----------------

class DeviceRegister(BaseModel):
    student_id: str = Field(..., pattern=STUDENT_ID_PATTERN)
    name: str = Field(..., min_length=1, max_length=100)
    model: str = Field(..., pattern=MODEL_PATTERN)
    public_key: str = Field(..., pattern=B64)
    signature: str = Field(..., pattern=B64)   # over register:{student_id}:{model}
    enrol_code: Optional[str] = Field(None, max_length=64)   # required when the server sets ENROL_CODE


class StartSession(BaseModel):
    room: str = Field("", max_length=64)
    window_seconds: Optional[int] = Field(None, ge=10, le=300)
    max_edge_m: Optional[float] = Field(None, gt=0, le=20)
    ttl: Optional[int] = Field(None, ge=1, le=30)
    max_path_m: Optional[float] = Field(None, gt=0, le=100)
    k: Optional[int] = Field(None, ge=1, le=10)
    delta_db: Optional[float] = Field(None, gt=0, le=40)
    independent: Optional[bool] = None
    near_m: Optional[float] = Field(None, ge=0, le=10)
    near_k: Optional[int] = Field(None, ge=1, le=10)
    autocal: Optional[bool] = None
    colocation_db: Optional[float] = Field(default=None, ge=0, le=20)
    ref_dbm: Optional[float] = Field(None, ge=-100, le=0)
    n: Optional[float] = Field(None, ge=1, le=6)


class CheckIn(BaseModel):
    student_id: str = Field(..., pattern=STUDENT_ID_PATTERN)
    signature: str = Field(..., pattern=B64)   # over checkin:{session_id}:{nonce}


class Neighbour(BaseModel):
    peer_id: str = Field(..., pattern=PEER_ID_PATTERN)     # ephemeral id seen in the advertisement
    rssi_median: int = Field(..., ge=-127, le=20)
    sample_count: int = Field(..., ge=1, le=100000)


class Report(BaseModel):
    student_id: str = Field(..., pattern=STUDENT_ID_PATTERN)
    neighbours: list[Neighbour] = Field(..., max_length=200)
    signature: str = Field(..., pattern=B64)   # over report:{session_id}:{student_id}:{canonical rows}


class VerifySeeds(BaseModel):
    student_ids: list[str] = Field(..., min_length=1, max_length=20)


class CloseRequest(BaseModel):
    """Optional teacher headcount. If the server marks more students present than she counted in the room,
    the surplus is resolved by flagging the least-corroborated PRESENT students for review."""
    headcount: Optional[int] = Field(None, ge=0, le=500)


class Adjudicate(BaseModel):
    student_id: str = Field(..., pattern=STUDENT_ID_PATTERN)
    status: Literal["PRESENT", "ABSENT"]


class Calibration(BaseModel):
    model: str = Field(..., pattern=MODEL_PATTERN)
    rssi_offset_db: float = Field(..., ge=-30, le=30)
