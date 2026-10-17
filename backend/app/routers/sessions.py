"""v2 proximity-graph attendance: check-in -> BLE discovery -> signed neighbour reports -> server-side flood."""
import secrets
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pymongo.errors import DuplicateKeyError

from app.config import settings
from app.db.mongo import get_db
from app.deps import require_teacher
from typing import Optional

from app.models.schemas import Adjudicate, CheckIn, CloseRequest, Report, StartSession, VerifySeeds
from app.services import crypto
from dataclasses import replace

from app.services.graph import platform_of, Params, adaptive_edge_m, evaluate
from app.services.ws_manager import ws_manager

import hmac

router = APIRouter(prefix="/api/sessions", tags=["Sessions (v2)"])

# Fixed 128-bit service UUID every NetPresence phone advertises; the per-session
# ephemeral id travels in the (permitted-on-iOS) local name as "NP-<eph_id>".
SERVICE_UUID = "6e657470-7265-7365-6e63-650000000001"


def advertise_uuid(eph: str) -> str:
    """Per-phone service UUID: the fixed 96-bit NetPresence prefix + the 32-bit ephemeral id.
    Android filters on the prefix with a mask; iOS scans and matches the prefix in code."""
    return SERVICE_UUID[:-12] + "6500" + eph


def _discovery_end(s: dict) -> float:
    return s.get("discovery_ends_at", s["window_ends_at"])   # sessions created before the tail existed


def _params(doc: dict) -> Params:
    return Params(**doc["params"])


async def _get_session(db, session_id: str) -> dict:
    s = await db.sessions.find_one({"session_id": session_id}, {"_id": 0})
    if not s:
        raise HTTPException(status_code=404, detail="Unknown session.")
    return s


async def _get_student(db, student_id: str) -> dict:
    st = await db.students.find_one({"student_id": student_id}, {"_id": 0})
    if not st:
        raise HTTPException(status_code=404, detail="Device not enrolled.")
    return st


@router.post("/start", dependencies=[Depends(require_teacher)])
async def start_session(payload: StartSession, db=Depends(get_db)):
    now = time.time()
    window = payload.window_seconds or settings.WINDOW_SECONDS
    params = Params(
        ref_dbm=payload.ref_dbm if payload.ref_dbm is not None else settings.RSSI_REF_DBM,
        n=payload.n if payload.n is not None else settings.PATH_LOSS_N,
        max_edge_m=payload.max_edge_m or settings.MAX_EDGE_M,
        ttl=payload.ttl or settings.TTL_HOPS,
        max_path_m=payload.max_path_m or settings.MAX_PATH_M,
        k=payload.k or settings.K_WITNESS,
        delta_db=payload.delta_db or settings.AGREE_DELTA_DB,
        independent=settings.INDEPENDENT if payload.independent is None else payload.independent,
        near_m=payload.near_m if payload.near_m is not None else settings.NEAR_M,
        near_k=payload.near_k or settings.NEAR_K,
        autocal=settings.AUTOCAL if payload.autocal is None else payload.autocal,
        colocation_db=settings.COLOCATION_DB if payload.colocation_db is None else payload.colocation_db,
    )
    doc = {
        "session_id": f"S-{uuid.uuid4().hex[:10]}",
        "nonce": secrets.token_hex(16),
        "room": payload.room,
        "status": "open",
        "created_at": now,
        "window_ends_at": now + window,                                   # check-in closes
        "discovery_ends_at": now + window + settings.DISCOVERY_TAIL_SECONDS,  # phones stop scanning
        "report_deadline": now + window + settings.DISCOVERY_TAIL_SECONDS + settings.REPORT_GRACE_SECONDS,
        "params": params.as_dict(),
        "seeds": [],
        "adaptive": payload.max_edge_m is None,   # density-based edge threshold unless the teacher fixed one
    }
    # Only one open session at a time keeps "which session am I joining" unambiguous for students.
    await db.sessions.update_many({"status": "open"}, {"$set": {"status": "closed"}})
    await db.sessions.insert_one(dict(doc))
    return {k: doc[k] for k in ("session_id", "nonce", "window_ends_at", "discovery_ends_at", "report_deadline", "params")}


@router.get("/open")
async def open_session(db=Depends(get_db)):
    """What a student phone needs to join: the single open session, if any (no secrets beyond the nonce)."""
    s = await db.sessions.find_one({"status": "open"}, {"_id": 0}, sort=[("created_at", -1)])
    if not s or time.time() > s["report_deadline"]:
        return {"status": "none"}
    return {
        "status": "open", "session_id": s["session_id"], "nonce": s["nonce"],
        "window_ends_at": s["window_ends_at"], "discovery_ends_at": _discovery_end(s), "report_deadline": s["report_deadline"],
        "service_uuid": SERVICE_UUID, "server_time": time.time(),   # lets phones correct their clock skew
    }


@router.get("", dependencies=[Depends(require_teacher)])
async def list_sessions(db=Depends(get_db)):
    return await db.sessions.find({}, {"_id": 0, "nonce": 0}).sort("created_at", -1).limit(50).to_list(length=50)


@router.post("/{session_id}/checkin")
async def checkin(session_id: str, payload: CheckIn, db=Depends(get_db)):
    s = await _get_session(db, session_id)
    if s["status"] != "open" or time.time() > s["window_ends_at"]:
        raise HTTPException(status_code=400, detail="Check-in window closed.")
    st = await _get_student(db, payload.student_id)
    if not crypto.verify(st["public_key"], crypto.checkin_message(session_id, s["nonce"]), payload.signature):
        raise HTTPException(status_code=401, detail="Bad signature.")

    existing = await db.checkins.find_one({"session_id": session_id, "student_id": payload.student_id}, {"_id": 0})
    if existing:   # idempotent: a retry gets the same ephemeral id back
        eph = existing["eph_id"]
    else:
        for _ in range(5):
            eph = secrets.token_hex(4)
            try:
                await db.checkins.insert_one({
                    "session_id": session_id, "student_id": payload.student_id,
                    "eph_id": eph, "model": st["model"], "at": time.time()})
                break
            except DuplicateKeyError:
                existing = await db.checkins.find_one({"session_id": session_id, "student_id": payload.student_id})
                if existing:
                    eph = existing["eph_id"]
                    break
        else:
            raise HTTPException(status_code=503, detail="Could not allocate id; retry.")
        await ws_manager.broadcast(session_id, {"type": "CHECKIN", "student_id": payload.student_id, "name": st["name"]})
    return {
        "eph_id": eph, "advertise_name": f"NP-{eph}", "service_uuid": SERVICE_UUID,
        "advertise_uuid": advertise_uuid(eph),   # identity carried IN the service UUID: one 21-byte advert, both OSes
        "window_ends_at": s["window_ends_at"], "discovery_ends_at": _discovery_end(s), "report_deadline": s["report_deadline"],
        "server_time": time.time(),
    }


@router.post("/{session_id}/report")
async def report(session_id: str, payload: Report, db=Depends(get_db)):
    s = await _get_session(db, session_id)
    if s["status"] != "open" or time.time() > s["report_deadline"]:
        raise HTTPException(status_code=400, detail="Report window closed.")
    st = await _get_student(db, payload.student_id)
    if not await db.checkins.find_one({"session_id": session_id, "student_id": payload.student_id}):
        raise HTTPException(status_code=400, detail="Check in first.")
    rows = [n.model_dump() for n in payload.neighbours]
    if not crypto.verify(st["public_key"], crypto.report_message(session_id, payload.student_id, rows), payload.signature):
        raise HTTPException(status_code=401, detail="Bad signature.")
    await db.reports.update_one(
        {"session_id": session_id, "student_id": payload.student_id},
        {"$set": {"session_id": session_id, "student_id": payload.student_id, "neighbours": rows, "at": time.time()}},
        upsert=True)
    await ws_manager.broadcast(session_id, {"type": "REPORT", "student_id": payload.student_id, "neighbours": len(rows)})
    return {"status": "accepted", "neighbours": len(rows)}


@router.post("/{session_id}/verify-seeds", dependencies=[Depends(require_teacher)])
async def verify_seeds(session_id: str, payload: VerifySeeds, db=Depends(get_db)):
    s = await _get_session(db, session_id)
    if s["status"] != "open":
        raise HTTPException(status_code=400, detail="Session closed.")
    checked = {c["student_id"] async for c in db.checkins.find({"session_id": session_id}, {"student_id": 1})}
    missing = [sid for sid in payload.student_ids if sid not in checked]
    if missing:
        raise HTTPException(status_code=400, detail=f"Not checked in: {', '.join(missing)}")
    seeds = list(dict.fromkeys(payload.student_ids))
    await db.sessions.update_one({"session_id": session_id}, {"$set": {"seeds": seeds}})
    await ws_manager.broadcast(session_id, {"type": "SEEDS", "student_ids": seeds})
    return {"status": "ok", "seeds": seeds}


async def _compute(db, s: dict) -> dict:
    sid = s["session_id"]
    params = _params(s)
    checkins = await db.checkins.find({"session_id": sid}, {"_id": 0}).to_list(length=5000)
    if s.get("adaptive"):
        params = replace(params, max_edge_m=adaptive_edge_m(len(checkins)))
    by_eph = {c["eph_id"]: c["student_id"] for c in checkins}
    models = {c["student_id"]: c["model"] for c in checkins}
    offsets = {c["model"]: c["rssi_offset_db"] async for c in db.device_calibration.find({}, {"_id": 0})}
    reports: dict[str, dict[str, float]] = {}
    async for r in db.reports.find({"session_id": sid}, {"_id": 0}):
        off = offsets.get(models.get(r["student_id"]), 0.0)
        seen = {}
        for n in r["neighbours"]:
            peer = by_eph.get(n["peer_id"])
            if peer and peer != r["student_id"]:
                seen[peer] = n["rssi_median"] + off
        reports[r["student_id"]] = seen
    groups = {stu: platform_of(m) for stu, m in models.items()}
    result = evaluate(s.get("seeds", []), reports, params, groups)
    colocated = result.get("colocated", {})

    roster = {st["student_id"]: st["name"] async for st in db.students.find({}, {"_id": 0, "student_id": 1, "name": 1})}
    checked = set(by_eph.values())
    rows = []
    for stu, name in roster.items():
        if stu in result["present"]:
            info = result["present"][stu]
            rows.append({"student_id": stu, "name": name, "status": "PRESENT", "decided_by": "graph", **info})
        elif stu in checked:
            row = {"student_id": stu, "name": name, "status": "FLAGGED", "decided_by": "graph", "reported": stu in reports}
            if stu in colocated:           # looks like the same radio as another id: a relay or a copied id, never automatic
                partner = colocated[stu]["partner"]
                row.update(reason="co-located", partner=partner, partner_name=roster.get(partner, partner),
                           spread_db=colocated[stu]["spread_db"])
            rows.append(row)
        else:
            rows.append({"student_id": stu, "name": name, "status": "ABSENT", "decided_by": "graph"})
    return {"rows": rows, "edges": result["edges"], "params": params.as_dict()}


@router.post("/{session_id}/close", dependencies=[Depends(require_teacher)])
async def close_session(session_id: str, payload: Optional[CloseRequest] = None, db=Depends(get_db)):
    s = await _get_session(db, session_id)
    if not s.get("seeds"):
        raise HTTPException(status_code=400, detail="Verify at least one seed (front-bench student) first.")
    out = await _compute(db, s)
    headcount = payload.headcount if payload else None
    gap = _flag_for_review(out["rows"], s["seeds"], headcount)
    for row in out["rows"]:
        await db.attendance.update_one(
            {"session_id": session_id, "student_id": row["student_id"]},
            {"$set": {**row, "session_id": session_id}}, upsert=True)
    await db.sessions.update_one({"session_id": session_id}, {"$set": {
        "status": "closed", "closed_at": time.time(), "headcount": headcount, "gap": gap,
        "params_used": out["params"]}})
    summary = _summary(out["rows"], out["edges"], headcount, gap)
    summary["params"] = out["params"]
    await ws_manager.broadcast(session_id, {"type": "RESULT", **summary})
    return summary


def _flag_for_review(rows: list[dict], seeds: list[str], headcount: Optional[int]) -> int:
    """Headcount reconciliation. If more are PRESENT than the teacher counted, mark the `gap` least-corroborated
    non-seed PRESENT students (fewest witnesses, then longest path) with review=True. Returns the gap (0 if none).
    Targets the failure RSSI cannot resolve on its own - a phone in an open doorway looks like a back-bench student."""
    if headcount is None:
        return 0
    present = [r for r in rows if r["status"] == "PRESENT"]
    gap = len(present) - headcount
    if gap <= 0:
        return 0
    cand = sorted((r for r in present if r["student_id"] not in seeds), key=lambda r: (r["witnesses"], -r["path_m"]))
    for r in cand[:gap]:
        r["review"] = True
    return gap


def _summary(rows: list[dict], edges: int | None = None, headcount: int | None = None, gap: int = 0) -> dict:
    counts = {"PRESENT": 0, "FLAGGED": 0, "ABSENT": 0}
    for r in rows:
        counts[r["status"]] += 1
    return {"counts": counts, "edges": edges, "headcount": headcount, "gap": gap,
            "review": sum(1 for r in rows if r.get("review")), "rows": rows}


@router.get("/{session_id}/result", dependencies=[Depends(require_teacher)])
async def get_result(session_id: str, db=Depends(get_db)):
    sess = await _get_session(db, session_id)
    rows = await db.attendance.find({"session_id": session_id}, {"_id": 0}).sort("student_id", 1).to_list(length=5000)
    summary = _summary(rows, None, sess.get("headcount"), sess.get("gap", 0))
    summary["params"] = sess.get("params_used")
    return summary


@router.post("/{session_id}/adjudicate", dependencies=[Depends(require_teacher)])
async def adjudicate(session_id: str, payload: Adjudicate, db=Depends(get_db)):
    await _get_session(db, session_id)
    res = await db.attendance.update_one(
        {"session_id": session_id, "student_id": payload.student_id},
        {"$set": {"status": payload.status, "decided_by": "teacher", "review": False}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="No attendance row; close the session first.")
    await ws_manager.broadcast(session_id, {"type": "ADJUDICATED", "student_id": payload.student_id, "status": payload.status})
    return {"status": "ok"}


@router.websocket("/ws/{session_id}")
async def session_ws(websocket: WebSocket, session_id: str, token: str = ""):
    if not hmac.compare_digest(token.encode(), settings.TEACHER_TOKEN.encode()):
        await websocket.close(code=4401)
        return
    await ws_manager.connect(session_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(session_id, websocket)
