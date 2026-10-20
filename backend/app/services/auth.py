"""Bearer tokens (stored hashed), teacher login codes (salted hash) and the wrong-code rate limiter."""
import hashlib
import hmac
import secrets
import time
from datetime import datetime, timezone

from fastapi import HTTPException

from app.config import settings


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def normalise_code(code: str) -> str:
    return code.strip().upper()


def hash_code(code: str, salt: str) -> str:
    return _h(salt + normalise_code(code))


async def issue_token(db, kind: str, ref: str) -> str:
    tok = secrets.token_urlsafe(32)
    exp = time.time() + settings.TOKEN_TTL_S
    await db.tokens.insert_one({"token_hash": _h(tok), "kind": kind, "ref": ref, "expires_at": exp,
                                "exp_dt": datetime.fromtimestamp(exp, timezone.utc)})
    return tok


async def lookup_token(db, tok: str, kind: str):
    """The ref the token was issued for, or None if unknown / expired / of another kind."""
    doc = await db.tokens.find_one({"token_hash": _h(tok), "kind": kind}, {"_id": 0})
    if not doc or doc["expires_at"] < time.time():
        return None
    return doc["ref"]


async def find_teacher_by_code(db, code: str):
    """Constant-time over all teachers: never short-circuits on the first match."""
    found = None
    async for t in db.teachers.find({}, {"_id": 0}):
        if hmac.compare_digest(hash_code(code, t["salt"]), t["code_hash"]):
            found = t
    return found


class LoginLimiter:
    """5 wrong teacher codes / 10 min / IP (in memory, single process)."""

    def __init__(self):
        self.fails: dict[str, list[float]] = {}

    def _recent(self, ip: str) -> list[float]:
        cut = time.time() - settings.LOGIN_WINDOW_S
        xs = [t for t in self.fails.get(ip, []) if t > cut]
        self.fails[ip] = xs
        return xs

    def check(self, ip: str) -> None:
        if len(self._recent(ip)) >= settings.LOGIN_MAX_FAILS:
            raise HTTPException(status_code=429, detail="Too many wrong codes. Wait 10 minutes and try again.")

    def fail(self, ip: str) -> None:
        self._recent(ip).append(time.time())

    def reset(self) -> None:
        self.fails.clear()


limiter = LoginLimiter()
