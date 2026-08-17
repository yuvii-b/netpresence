from fastapi import APIRouter
from app.models.schemas import StartSessionRequest, SessionResponse
from app.services.token_service import token_service
from app.db.mongo import db_instance

router = APIRouter(prefix="/api/sessions", tags=["Sessions"])

@router.post("/start", response_model=SessionResponse)
async def start_session(payload: StartSessionRequest):
    session = token_service.register_session(payload.session_id, payload.token)

    if db_instance.db is not None:
        await db_instance.db.sessions.update_one(
            {"session_id": payload.session_id},
            {"$set": {
                "session_id": payload.session_id,
                "token": payload.token,
                "status": "active",
                "created_at": session["created_at"],
                "expires_at": session["expires_at"],
            }},
            upsert=True
        )

    return {
        "status": "active",
        "session_id": payload.session_id,
        "token": payload.token
    }


@router.post("/stop/{session_id}")
async def stop_session(session_id: str):
    token_service.end_session(session_id)

    if db_instance.db is not None:
        await db_instance.db.sessions.update_one(
            {"session_id": session_id},
            {"$set": {"status": "stopped"}}
        )

    return {"status": "stopped", "session_id": session_id}


@router.get("/list")
async def list_sessions():
    """List all sessions, most recently created first."""
    if db_instance.db is None:
        return []
    cursor = db_instance.db.sessions.find({}, {"_id": 0}).sort("created_at", -1).limit(50)
    return await cursor.to_list(length=50)


@router.get("/active/{session_id}")
async def get_active_session(session_id: str):
    """Return the active session token if the session is active and not expired."""
    session = token_service.active_sessions.get(session_id)
    if not session:
        return {"status": "inactive", "session_id": session_id}
    return {"status": "active", "session_id": session_id, "token": session["token"]}
