"""v1 acoustic baseline (kept as the documented comparison arm).

Fixes vs the original: state lives in MongoDB (survives restarts), the session
token is never returned to students, timestamps are real, session start/stop
needs the teacher token, and every listening attempt can be logged as a trial.
"""
import time

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pymongo.errors import DuplicateKeyError
import hmac

from app.config import settings
from app.db.mongo import get_db
from app.deps import require_teacher
from app.models.schemas import AcousticStartRequest, AcousticSubmitRequest, AcousticTrial
from app.services.ws_manager import ACOUSTIC_ROOM, ws_manager

router = APIRouter(prefix="/api/acoustic", tags=["Acoustic v1"])


@router.post("/sessions/start", dependencies=[Depends(require_teacher)])
async def start_session(payload: AcousticStartRequest, db=Depends(get_db)):
    now = time.time()
    await db.acoustic_sessions.update_one(
        {"session_id": payload.session_id},
        {"$set": {"session_id": payload.session_id, "token": payload.token, "status": "active",
                  "created_at": now, "expires_at": now + settings.TOKEN_VALIDITY_SECONDS}},
        upsert=True)
    return {"status": "active", "session_id": payload.session_id}


@router.post("/sessions/stop/{session_id}", dependencies=[Depends(require_teacher)])
async def stop_session(session_id: str, db=Depends(get_db)):
    await db.acoustic_sessions.update_one({"session_id": session_id}, {"$set": {"status": "stopped"}})
    return {"status": "stopped", "session_id": session_id}


@router.get("/sessions/list")
async def list_sessions(db=Depends(get_db)):
    """Session ids + status only. The token is deliberately NOT returned."""
    now = time.time()
    docs = await db.acoustic_sessions.find({}, {"_id": 0, "token": 0}).sort("created_at", -1).limit(50).to_list(length=50)
    for d in docs:   # an "active" session past its window is reported as expired
        if d["status"] == "active" and now > d["expires_at"]:
            d["status"] = "expired"
    return docs


@router.post("/attendance/submit")
async def submit(payload: AcousticSubmitRequest, db=Depends(get_db)):
    s = await db.acoustic_sessions.find_one({"session_id": payload.session_id})
    if not s or s["status"] != "active":
        raise HTTPException(status_code=400, detail="Invalid or inactive session.")
    if time.time() > s["expires_at"]:
        raise HTTPException(status_code=400, detail="Audio token expired.")
    if payload.decoded_token != s["token"]:
        raise HTTPException(status_code=400, detail="Audio token mismatch.")
    try:   # unique (session, student) index is the single-use check, and survives restarts
        await db.acoustic_attendance.insert_one({
            "session_id": payload.session_id, "student_id": payload.student_id,
            "status": "PRESENT", "timestamp": time.time()})
    except DuplicateKeyError:
        raise HTTPException(status_code=400, detail="Attendance already submitted.")
    await ws_manager.broadcast(ACOUSTIC_ROOM, {
        "type": "ATTENDANCE_RECORDED", "student_id": payload.student_id, "session_id": payload.session_id})
    return {"status": "success", "message": "Attendance marked successfully!"}


@router.post("/trials", status_code=201)
async def log_trial(trial: AcousticTrial, db=Depends(get_db)):
    await db.acoustic_trials.insert_one({**trial.model_dump(), "at": time.time()})
    return {"status": "logged"}


@router.get("/trials/summary", dependencies=[Depends(require_teacher)])
async def trial_summary(db=Depends(get_db)):
    """Detection rate grouped by seat position, fan state and device model (the v1 dead-end evidence)."""
    out = {}
    for field in ("seat_position", "fan_on", "device_model", "os"):
        pipeline = [
            {"$match": {field: {"$ne": None}}},
            {"$group": {"_id": f"${field}", "trials": {"$sum": 1},
                        "successes": {"$sum": {"$cond": ["$success", 1, 0]}},
                        "avg_ms": {"$avg": "$time_to_detect_ms"}}},
        ]
        rows = await db.acoustic_trials.aggregate(pipeline).to_list(length=200)
        out[field] = sorted(
            [{"key": r["_id"], "trials": r["trials"], "detection_rate": round(r["successes"] / r["trials"], 3),
              "avg_time_to_detect_ms": None if r["avg_ms"] is None else round(r["avg_ms"])} for r in rows],
            key=lambda r: str(r["key"]))
    return out


@router.websocket("/ws")
async def acoustic_ws(websocket: WebSocket, token: str = ""):
    if not hmac.compare_digest(token.encode(), settings.TEACHER_TOKEN.encode()):
        await websocket.close(code=4401)
        return
    await ws_manager.connect(ACOUSTIC_ROOM, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(ACOUSTIC_ROOM, websocket)
