import time

from fastapi import APIRouter, Depends, HTTPException, Request

from app.config import settings
from app.db.mongo import get_db
from app.models.schemas import StudentLogin, TeacherLogin
from app.routers.teacher import subject_list
from app.services import crypto
from app.services.auth import find_teacher_by_code, issue_token, limiter

router = APIRouter(prefix="/api/auth", tags=["Auth (v3)"])


@router.post("/teacher")
async def teacher_login(payload: TeacherLogin, request: Request, db=Depends(get_db)):
    ip = request.client.host if request.client else "?"
    limiter.check(ip)
    t = await find_teacher_by_code(db, payload.code)
    if not t:
        limiter.fail(ip)
        raise HTTPException(status_code=401, detail="That code is not recognised. Check it and try again.")
    token = await issue_token(db, "teacher", t["teacher_id"])
    user = {"teacher_id": t["teacher_id"], "name": t["name"]}
    return {"token": token, "expires_in": settings.TOKEN_TTL_S, "teacher": {"name": t["name"]}, "subjects": await subject_list(db, user)}


@router.post("/student")
async def student_login(payload: StudentLogin, db=Depends(get_db)):
    """Signed with the bound hardware key: no passwords. ts must be within 60 s of server time."""
    if abs(time.time() - payload.ts) > 60:
        raise HTTPException(status_code=400, detail="Your phone's clock is off. Set the time to automatic and try again.")
    st = await db.students.find_one({"student_id": payload.student_id}, {"_id": 0})
    if not st:
        raise HTTPException(status_code=404, detail="This phone is not registered yet.")
    if not crypto.verify(st["public_key"], crypto.login_message(payload.student_id, payload.ts), payload.signature):
        raise HTTPException(status_code=401, detail="This is not the phone registered for this student.")
    return {"token": await issue_token(db, "student", payload.student_id), "expires_in": settings.TOKEN_TTL_S, "name": st["name"]}
