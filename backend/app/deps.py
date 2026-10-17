import hmac

from fastapi import Header, HTTPException

from app.config import settings


async def require_teacher(x_teacher_token: str = Header(default="")):
    if not hmac.compare_digest(x_teacher_token.encode(), settings.TEACHER_TOKEN.encode()):
        raise HTTPException(status_code=401, detail="Teacher token required.")
