from pydantic import BaseModel, Field
from typing import Optional

class StartSessionRequest(BaseModel):
    session_id: str
    token: str

class SubmitAttendanceRequest(BaseModel):
    session_id: str
    student_id: str
    decoded_token: str

class SessionResponse(BaseModel):
    status: str
    session_id: str
    token: str