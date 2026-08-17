from pydantic import BaseModel, Field

# Matches the tone alphabet in frontend/src/audio/toneEncoder.js
TOKEN_PATTERN = r"^[0-9A-Z]{1,8}$"
SESSION_ID_PATTERN = r"^[A-Za-z0-9\-]{1,64}$"
STUDENT_ID_PATTERN = r"^[A-Za-z0-9 _.\-@]{1,64}$"


class StartSessionRequest(BaseModel):
    session_id: str = Field(..., pattern=SESSION_ID_PATTERN)
    token: str = Field(..., pattern=TOKEN_PATTERN)


class SubmitAttendanceRequest(BaseModel):
    session_id: str = Field(..., pattern=SESSION_ID_PATTERN)
    student_id: str = Field(..., pattern=STUDENT_ID_PATTERN)
    decoded_token: str = Field(..., pattern=TOKEN_PATTERN)


class SessionResponse(BaseModel):
    status: str
    session_id: str
    token: str
