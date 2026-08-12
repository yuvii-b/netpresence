from fastapi import APIRouter
from app.models.schemas import StartSessionRequest, SessionResponse
from app.services.token_service import token_service

router = APIRouter(prefix="/api/sessions", tags=["Sessions"])

@router.post("/start", response_model=SessionResponse)
async def start_session(payload: StartSessionRequest):
    token_service.register_session(payload.session_id, payload.token)
    return {
        "status": "active",
        "session_id": payload.session_id,
        "token": payload.token
    }


@router.get("/active/{session_id}")
async def get_active_session(session_id: str):
    """Return the active session token if the session is active and not expired."""
    session = token_service.active_sessions.get(session_id)
    if not session:
        return {"status": "inactive", "session_id": session_id}
    return {"status": "active", "session_id": session_id, "token": session["token"]}