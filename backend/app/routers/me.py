"""Student side of protocol v3: who am I, which roll call is open for me, and what is my status (all long-poll)."""
import time

from fastapi import APIRouter, Depends, HTTPException

from app.config import settings
from app.db.mongo import get_db
from app.deps import require_student
from app.services import rollcall
from app.services.live import hub

router = APIRouter(prefix="/api", tags=["Student (v3)"])


async def _subjects(db, student_id):
    return await db.subjects.find({"roster": student_id}, {"_id": 0, "roster": 0}).sort("code", 1).to_list(length=100)


@router.get("/me")
async def me(st=Depends(require_student), db=Depends(get_db)):
    subs = await _subjects(db, st["student_id"])
    return {"student_id": st["student_id"], "name": st["name"],
            "subjects": [{"subject_id": s["subject_id"], "code": s["code"], "name": s["name"]} for s in subs]}


@router.get("/me/session")
async def my_session(wait: int = 0, st=Depends(require_student), db=Depends(get_db)):
    """Long-poll: returns as soon as a roll call opens for a subject I am enrolled in."""
    subs = {s["subject_id"]: s for s in await _subjects(db, st["student_id"])}
    deadline = time.monotonic() + min(max(wait, 0), settings.LONGPOLL_WAIT_S)
    while True:
        last = hub.current_open_rev()
        s = await db.sessions.find_one({"subject_id": {"$in": list(subs)}, "status": "open", "live": True,
                                        "report_deadline": {"$gt": time.time()}}, {"_id": 0}, sort=[("created_at", -1)]) if subs else None
        if s:
            sub = subs[s["subject_id"]]
            return {"status": "open", "session_id": s["session_id"], "nonce": s["nonce"], "tag": s["tag"],
                    "subject": {"subject_id": sub["subject_id"], "code": sub["code"], "name": sub["name"]},
                    "server_time": time.time(), "live_ends_at": s["report_deadline"] - 5}
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {"status": "none", "server_time": time.time()}
        await hub.wait_open(last, remaining)


@router.get("/sessions/{session_id}/me")
async def my_status(session_id: str, since: int = 0, wait: int = 0, st=Depends(require_student), db=Depends(get_db)):
    s = await db.sessions.find_one({"session_id": session_id, "live": True}, {"_id": 0})
    if not s:
        raise HTTPException(status_code=404, detail="Unknown roll call.")
    stu = st["student_id"]
    if not await db.subjects.find_one({"subject_id": s["subject_id"], "roster": stu}):
        raise HTTPException(status_code=403, detail="You are not in this class.")
    if s["status"] == "open" and time.time() > s["report_deadline"]:
        await rollcall.finish(db, s)
        s = await db.sessions.find_one({"session_id": session_id}, {"_id": 0})
    state = hub.state(session_id)
    if s["status"] == "open":
        await hub.prepare(db, s)
        if wait and state.stat.get(stu, [0])[0] <= since:
            await hub.wait(session_id, lambda: state.stat.get(stu, [0])[0] > since or state.closed, min(wait, settings.LONGPOLL_WAIT_S))
    rec = state.stat.get(stu)
    if rec is None and s["status"] != "open":   # closed long ago (state dropped): read the stored result
        row = await db.attendance.find_one({"session_id": session_id, "student_id": stu}, {"_id": 0})
        return {"rev": 1, "status": "CLOSED", "result": row["status"] if row else "ABSENT", "at": s.get("closed_at")}
    if rec is None:
        return {"rev": 0, "status": "NONE", "at": None}
    return {"rev": rec[0], "status": rec[1], "at": rec[2], "result": state.result.get(stu)}
