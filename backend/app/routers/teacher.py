"""Teacher side of protocol v3: subjects, live roll call (start / long-poll / finish), adjudication; plus admin seeding."""
import secrets
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.config import settings
from app.db.mongo import get_db
from app.deps import require_teacher, require_teacher_user
from app.models.schemas import Adjudicate, AdminSubject, AdminTeacher, CloseRequest, StartSubject, VerifySeeds
from app.services import crypto, rollcall, seed
from app.services.live import hub

router = APIRouter(prefix="/api", tags=["Teacher (v3)"])


def advertise_uuid(eph: str) -> str:
    from app.routers.sessions import advertise_uuid as f
    return f(eph)


async def subject_list(db, user: dict) -> list[dict]:
    q = {} if user["teacher_id"] is None else {"teacher_id": user["teacher_id"]}
    out = []
    async for sub in db.subjects.find(q, {"_id": 0}).sort("code", 1):
        last = await db.sessions.find_one({"subject_id": sub["subject_id"], "status": "closed"}, {"_id": 0}, sort=[("closed_at", -1)])
        pct = None
        if last and sub["roster"]:
            pct = round(100 * await db.attendance.count_documents({"session_id": last["session_id"], "status": "PRESENT"}) / len(sub["roster"]))
        out.append({"subject_id": sub["subject_id"], "code": sub["code"], "name": sub["name"],
                    "roster_size": len(sub["roster"]), "last_pct": pct})
    return out


async def _own_subject(db, user, subject_id):
    sub = await db.subjects.find_one({"subject_id": subject_id}, {"_id": 0})
    if not sub or (user["teacher_id"] is not None and sub["teacher_id"] != user["teacher_id"]):
        raise HTTPException(status_code=404, detail="Unknown subject.")
    return sub


async def _own_session(db, user, session_id):
    s = await db.sessions.find_one({"session_id": session_id}, {"_id": 0})
    if not s or not s.get("live") or (user["teacher_id"] is not None and s["teacher_id"] != user["teacher_id"]):
        raise HTTPException(status_code=404, detail="Unknown roll call.")
    if s["status"] == "open" and time.time() > s["report_deadline"]:   # auto-finish (watchdog lost, e.g. server restart)
        await rollcall.finish(db, s)
        s = await db.sessions.find_one({"session_id": session_id}, {"_id": 0})
    return s


@router.get("/teacher/subjects")
async def list_subjects(user=Depends(require_teacher_user), db=Depends(get_db)):
    return await subject_list(db, user)


def _start_view(s: dict, subj: dict) -> dict:
    tp = s["teacher_phone"]
    return {"session_id": s["session_id"], "nonce": s["nonce"], "tag": s["tag"], "teacher_student_id": tp["student_id"],
            "teacher_eph": tp["eph_id"], "advertise_name": f"NP-{tp['eph_id']}", "advertise_uuid": advertise_uuid(tp["eph_id"]),
            "server_time": time.time(), "live_ends_at": s["report_deadline"] - 5,
            "subject": {"subject_id": subj["subject_id"], "code": subj["code"], "name": subj["name"], "roster_size": len(subj["roster"])}}


@router.post("/teacher/subjects/{subject_id}/start")
async def start_subject(subject_id: str, payload: StartSubject, user=Depends(require_teacher_user), db=Depends(get_db)):
    subj = await _own_subject(db, user, subject_id)
    try:
        crypto.load_public_key(payload.device.public_key)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid phone key.")
    now = time.time()
    s = await db.sessions.find_one({"subject_id": subject_id, "status": "open", "report_deadline": {"$gt": now}}, {"_id": 0})
    if s:   # already running: hand it back (the teacher reopened the app); the phone's key may have changed
        tp = {**s["teacher_phone"], "public_key": payload.device.public_key, "model": payload.device.model}
        await db.sessions.update_one({"session_id": s["session_id"]}, {"$set": {"teacher_phone": tp}})
        await db.checkins.update_one({"session_id": s["session_id"], "student_id": tp["student_id"]}, {"$set": {"model": tp["model"]}})
        s["teacher_phone"] = tp
        return _start_view(s, subj)
    open_tags = {x["tag"] async for x in db.sessions.find({"status": "open", "live": True}, {"tag": 1})}
    tag = secrets.token_hex(2)
    while tag in open_tags:
        tag = secrets.token_hex(2)
    end = now + settings.LIVE_MAX_SECONDS
    tstu = f"TEACHER.{subj['teacher_id']}"
    s = {"session_id": f"S-{uuid.uuid4().hex[:10]}", "nonce": secrets.token_hex(16), "room": subj["name"], "status": "open",
         "created_at": now, "window_ends_at": end, "discovery_ends_at": end, "report_deadline": end + 5,
         "params": rollcall.default_params().as_dict(), "seeds": [], "adaptive": True, "live": True, "overrides": {},
         "subject_id": subject_id, "teacher_id": subj["teacher_id"], "tag": tag,
         "teacher_phone": {"student_id": tstu, "public_key": payload.device.public_key, "model": payload.device.model,
                           "eph_id": tag + "0000"}}
    await db.sessions.insert_one(dict(s))
    await db.checkins.insert_one({"session_id": s["session_id"], "student_id": tstu, "eph_id": tag + "0000",
                                  "model": payload.device.model, "at": now})
    await hub.created(db, s)
    return _start_view(s, subj)


@router.get("/teacher/sessions/{session_id}/live")
async def live_view(session_id: str, since: int = -1, wait: int = 0, user=Depends(require_teacher_user), db=Depends(get_db)):
    s = await _own_session(db, user, session_id)
    st = hub.state(session_id)
    if s["status"] == "open":
        await hub.prepare(db, s)
        if wait and st.rev <= since:
            await hub.wait(session_id, lambda: st.rev > since or st.closed, min(wait, settings.LONGPOLL_WAIT_S))
    if st.snap is None:   # closed long ago: serve the stored attendance
        rows = await db.attendance.find({"session_id": session_id}, {"_id": 0}).sort("student_id", 1).to_list(length=5000)
        return {"rev": 1, "status": "closed", "counts": rollcall.summary(rows)["counts"], "rows": rows, "stable_for_s": 0,
                "elapsed_s": round(s.get("closed_at", time.time()) - s["created_at"], 1), "roster_size": len(rows)}
    now = time.time()
    rows = [{k: r[k] for k in ("student_id", "name", "status", "reason", "partner_name", "decided_by") if k in r} for r in st.snap["rows"]]
    return {"rev": st.rev, "status": "closed" if st.closed or s["status"] != "open" else "open", "counts": st.snap["counts"], "rows": rows,
            "stable_for_s": round(now - st.last_change, 1), "elapsed_s": round(now - s["created_at"], 1),
            "roster_size": len(rows), "ends_in_s": round(max(0.0, s["report_deadline"] - 5 - now), 1)}


@router.get("/teacher/subjects/{subject_id}/sheet")
async def attendance_sheet(subject_id: str, limit: int = 30, user=Depends(require_teacher_user), db=Depends(get_db)):
    """The register: every roster student against the last `limit` finished roll calls of this subject (oldest first).
    marks: P present, A absent, F flagged (teacher never settled it), - not on that day's record."""
    sub = await _own_subject(db, user, subject_id)
    limit = max(1, min(limit, 120))
    sess = await db.sessions.find({"subject_id": subject_id, "status": "closed", "live": True}, {"_id": 0}).sort("closed_at", -1).to_list(length=limit)
    sess.reverse()
    sids = [x["session_id"] for x in sess]
    by: dict[tuple, str] = {}
    async for a in db.attendance.find({"session_id": {"$in": sids}}, {"_id": 0, "session_id": 1, "student_id": 1, "status": 1}):
        by[(a["session_id"], a["student_id"])] = a["status"]
    names = {st["student_id"]: st["name"] async for st in db.students.find({"student_id": {"$in": sub["roster"]}}, {"_id": 0, "student_id": 1, "name": 1})}
    code = {"PRESENT": "P", "ABSENT": "A", "FLAGGED": "F"}
    students = []
    for sid_ in sorted(sub["roster"]):
        marks = [code.get(by.get((sess_id, sid_)), "-") for sess_id in sids]
        held = sum(1 for m in marks if m != "-")
        pres = marks.count("P")
        students.append({"student_id": sid_, "name": names.get(sid_, sid_), "marks": marks, "present": pres,
                         "pct": round(100 * pres / held) if held else None})
    return {"subject": {"subject_id": subject_id, "code": sub["code"], "name": sub["name"]},
            "sessions": [{"session_id": x["session_id"], "at": x.get("created_at") or x.get("closed_at"),
                          "present": sum(1 for sid_ in sub["roster"] if by.get((x["session_id"], sid_)) == "PRESENT"),
                          "total": len(sub["roster"])} for x in sess],
            "students": students}


@router.post("/teacher/sessions/{session_id}/finish")
async def finish_session(session_id: str, payload: CloseRequest | None = None, user=Depends(require_teacher_user), db=Depends(get_db)):
    s = await _own_session(db, user, session_id)
    if s["status"] != "open":
        rows = await db.attendance.find({"session_id": session_id}, {"_id": 0}).sort("student_id", 1).to_list(length=5000)
        out = rollcall.summary(rows, None, s.get("headcount"), s.get("gap", 0))
        out["params"] = s.get("params_used")
        return out
    return await rollcall.finish(db, s, payload.headcount if payload else None)


@router.post("/teacher/sessions/{session_id}/seeds")
async def set_seeds(session_id: str, payload: VerifySeeds, user=Depends(require_teacher_user), db=Depends(get_db)):
    s = await _own_session(db, user, session_id)
    if s["status"] != "open":
        raise HTTPException(status_code=400, detail="This roll call has ended.")
    checked = {c["student_id"] async for c in db.checkins.find({"session_id": session_id}, {"student_id": 1})}
    missing = [x for x in payload.student_ids if x not in checked]
    if missing:
        raise HTTPException(status_code=400, detail=f"Not checked in: {', '.join(missing)}")
    await db.sessions.update_one({"session_id": session_id}, {"$set": {"seeds": list(dict.fromkeys(payload.student_ids))}})
    await hub.touched(db, session_id)
    return {"status": "ok"}


@router.post("/teacher/sessions/{session_id}/adjudicate")
async def adjudicate(session_id: str, payload: Adjudicate, user=Depends(require_teacher_user), db=Depends(get_db)):
    s = await _own_session(db, user, session_id)
    roster = await rollcall.load_roster(db, s)
    if payload.student_id not in roster:
        raise HTTPException(status_code=404, detail="That student is not in this class.")
    if s["status"] == "open":
        await db.sessions.update_one({"session_id": session_id}, {"$set": {f"overrides.{payload.student_id}": payload.status}})
        await hub.touched(db, session_id)
    else:
        await db.attendance.update_one({"session_id": session_id, "student_id": payload.student_id},
                                       {"$set": {"status": payload.status, "decided_by": "teacher", "review": False}})
    return {"status": "ok"}


@router.post("/teacher/students/{student_id}/reset-device")
async def reset_student_device(student_id: str, user=Depends(require_teacher_user), db=Depends(get_db)):
    """Let a student bind a new phone (lost / replaced phone). Teachers may reset anyone on one of their rosters."""
    if user["teacher_id"] is not None and not await db.subjects.find_one({"teacher_id": user["teacher_id"], "roster": student_id}):
        raise HTTPException(status_code=404, detail="That student is not in any of your classes.")
    res = await db.students.delete_one({"student_id": student_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Unknown student.")
    return {"status": "reset", "student_id": student_id}


# ---- admin (shared TEACHER_TOKEN): seeding for tests, tools and the web console ----
@router.post("/admin/teachers", status_code=201, dependencies=[Depends(require_teacher)])
async def admin_add_teacher(payload: AdminTeacher, db=Depends(get_db)):
    return await seed.add_teacher(db, payload.name, payload.code)


@router.post("/admin/subjects", status_code=201, dependencies=[Depends(require_teacher)])
async def admin_add_subject(payload: AdminSubject, db=Depends(get_db)):
    try:
        return await seed.add_subject(db, payload.teacher_code, payload.code, payload.name, payload.roster)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
