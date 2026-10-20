"""Roll-call evaluation shared by the legacy window flow and the live flow: roster, statuses, finish."""
import asyncio
import time
from dataclasses import replace
from typing import Optional

from app.config import settings
from app.services.graph import Params, adaptive_edge_m, evaluate, platform_of
from app.services.live import hub


def default_params() -> Params:
    return Params(
        ref_dbm=settings.RSSI_REF_DBM, n=settings.PATH_LOSS_N, max_edge_m=settings.MAX_EDGE_M, ttl=settings.TTL_HOPS,
        max_path_m=settings.MAX_PATH_M, k=settings.K_WITNESS, delta_db=settings.AGREE_DELTA_DB,
        independent=settings.INDEPENDENT, near_m=settings.NEAR_M, near_k=settings.NEAR_K, autocal=settings.AUTOCAL,
        colocation_db=settings.COLOCATION_DB)


def is_expired(s: dict) -> bool:
    return s["status"] != "open" or time.time() > s["report_deadline"]


async def load_roster(db, s: dict) -> dict[str, str]:
    """student_id -> name of everyone who may be marked in this session (the subject roster, or every enrolled student)."""
    if s.get("subject_id"):
        subj = await db.subjects.find_one({"subject_id": s["subject_id"]}, {"_id": 0}) or {"roster": []}
        names = {st["student_id"]: st["name"] async for st in db.students.find({"student_id": {"$in": subj["roster"]}}, {"_id": 0})}
        return {i: names.get(i, i) for i in subj["roster"]}
    return {st["student_id"]: st["name"] async for st in db.students.find({}, {"_id": 0, "student_id": 1, "name": 1})}


async def compute(db, s: dict, final: bool = False) -> dict:
    """Evaluate the session now. Legacy rows: PRESENT / FLAGGED / ABSENT. Live rows add PENDING (checked in, not corroborated
    yet) and NOT_JOINED; with final=True those become ABSENT (a co-located id stays FLAGGED for the teacher)."""
    sid = s["session_id"]
    live = bool(s.get("live"))
    params = Params(**s["params"])
    checkins = await db.checkins.find({"session_id": sid}, {"_id": 0}).to_list(length=5000)
    if s.get("adaptive"):
        params = replace(params, max_edge_m=adaptive_edge_m(len([c for c in checkins if c["student_id"] != (s.get("teacher_phone") or {}).get("student_id")])))
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
    seeds = list(s.get("seeds", []))
    if live and s.get("teacher_phone"):
        seeds = [s["teacher_phone"]["student_id"]] + seeds
    result = await asyncio.to_thread(evaluate, seeds, reports, params, groups)
    colocated = result.get("colocated", {})

    roster = await load_roster(db, s)
    overrides = s.get("overrides", {})
    checked = set(by_eph.values())
    rows = []
    for stu, name in roster.items():
        if stu in overrides:
            rows.append({"student_id": stu, "name": name, "status": overrides[stu], "decided_by": "teacher"})
        elif stu in result["present"]:
            info = result["present"][stu]
            rows.append({"student_id": stu, "name": name, "status": "PRESENT", "decided_by": "graph", **info})
        elif stu in checked:
            row = {"student_id": stu, "name": name, "decided_by": "graph", "reported": stu in reports,
                   "status": "FLAGGED" if not live or stu in colocated else ("ABSENT" if final else "PENDING")}
            if stu in colocated:           # looks like the same radio as another id: a relay or a copied id, never automatic
                partner = colocated[stu]["partner"]
                row.update(reason="co-located", partner=partner, partner_name=roster.get(partner, partner),
                           spread_db=colocated[stu]["spread_db"])
            rows.append(row)
        else:
            rows.append({"student_id": stu, "name": name, "status": "ABSENT" if (final or not live) else "NOT_JOINED",
                         "decided_by": "graph"})
    return {"rows": rows, "edges": result["edges"], "params": params.as_dict()}


def flag_for_review(rows: list[dict], seeds: list[str], headcount: Optional[int]) -> int:
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


def summary(rows: list[dict], edges: int | None = None, headcount: int | None = None, gap: int = 0) -> dict:
    counts = {"PRESENT": 0, "FLAGGED": 0, "ABSENT": 0}
    for r in rows:
        counts[r["status"]] += 1
    return {"counts": counts, "edges": edges, "headcount": headcount, "gap": gap,
            "review": sum(1 for r in rows if r.get("review")), "rows": rows}


async def finish(db, s: dict, headcount: Optional[int] = None) -> dict:
    """Finalise a session (legacy close, teacher Finish, or the live auto-finish) and store the attendance."""
    from app.services.ws_manager import ws_manager
    sid = s["session_id"]
    out = await compute(db, s, final=True)
    if s.get("live"):
        out["rows"] = hub.latch_final(sid, out["rows"])
    seeds = list(s.get("seeds", []))
    gap = flag_for_review(out["rows"], seeds, headcount)
    for row in out["rows"]:
        await db.attendance.update_one({"session_id": sid, "student_id": row["student_id"]},
                                       {"$set": {**row, "session_id": sid, "subject_id": s.get("subject_id")}}, upsert=True)
    await db.sessions.update_one({"session_id": sid}, {"$set": {
        "status": "closed", "closed_at": time.time(), "headcount": headcount, "gap": gap, "params_used": out["params"]}})
    res = summary(out["rows"], out["edges"], headcount, gap)
    res["params"] = out["params"]
    await ws_manager.broadcast(sid, {"type": "RESULT", **res})
    if s.get("live"):
        await hub.publish_close(sid, out["rows"])
    return res
