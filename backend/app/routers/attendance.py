from fastapi import APIRouter
from app.models.schemas import SubmitAttendanceRequest
from app.services.token_service import token_service
from app.services.ws_manager import ws_manager
from app.db.mongo import db_instance

router = APIRouter(prefix="/api/attendance", tags=["Attendance"])

@router.post("/submit")
async def submit_attendance(payload: SubmitAttendanceRequest):
    # Validate token and single-use nonce
    token_service.validate_submission(
        payload.session_id, payload.student_id, payload.decoded_token
    )

    # Persist attendance record into MongoDB
    if db_instance.db is not None:
        await db_instance.db.attendance.update_one(
            {"session_id": payload.session_id, "student_id": payload.student_id},
            {"$set": {"status": "PRESENT", "timestamp": payload.decoded_token}},
            upsert=True
        )

    # Broadcast real-time event to Teacher Dashboard via WebSockets
    await ws_manager.broadcast({
        "type": "ATTENDANCE_RECORDED",
        "student_id": payload.student_id,
        "session_id": payload.session_id
    })

    return {"status": "success", "message": "Attendance marked successfully!"}