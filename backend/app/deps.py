import hmac
from typing import Optional

from fastapi import Depends, Header, HTTPException

from app.config import settings
from app.db.mongo import get_db
from app.services.auth import lookup_token


def _is_admin(tok: str) -> bool:
    return bool(tok) and hmac.compare_digest(tok.encode(), settings.TEACHER_TOKEN.encode())


async def require_teacher(x_teacher_token: str = Header(default="")):
    """Admin: the shared TEACHER_TOKEN (web console, tools, tests)."""
    if not _is_admin(x_teacher_token):
        raise HTTPException(status_code=401, detail="Teacher token required.")


def _bearer(authorization: str) -> str:
    return authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""


async def require_teacher_user(x_teacher_token: str = Header(default=""), authorization: str = Header(default=""),
                               db=Depends(get_db)) -> dict:
    """A teacher logged in with a code (bearer token) -> {"teacher_id", "name"}; the admin token -> {"teacher_id": None}
    (may act on every subject)."""
    if _is_admin(x_teacher_token):
        return {"teacher_id": None, "name": "Admin"}
    tok = _bearer(authorization)
    tid = await lookup_token(db, tok, "teacher") if tok else None
    t = await db.teachers.find_one({"teacher_id": tid}, {"_id": 0}) if tid else None
    if not t:
        raise HTTPException(status_code=401, detail="Please log in again.")
    return {"teacher_id": t["teacher_id"], "name": t["name"]}


async def require_student(authorization: str = Header(default=""), db=Depends(get_db)) -> dict:
    tok = _bearer(authorization)
    sid = await lookup_token(db, tok, "student") if tok else None
    st = await db.students.find_one({"student_id": sid}, {"_id": 0, "public_key": 0}) if sid else None
    if not st:
        raise HTTPException(status_code=401, detail="Please open the app again to sign in.")
    return st
