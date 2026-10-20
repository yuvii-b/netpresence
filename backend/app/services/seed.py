"""Teachers, subjects and rosters (used by tools/admin.py, the admin API and the dev-server demo seed)."""
import secrets

from app.services.auth import hash_code, normalise_code


async def add_teacher(db, name: str, code: str) -> dict:
    salt = secrets.token_hex(8)
    doc = {"teacher_id": f"T-{secrets.token_hex(4)}", "name": name, "salt": salt, "code_hash": hash_code(code, salt)}
    await db.teachers.insert_one(dict(doc))
    return {"teacher_id": doc["teacher_id"], "name": name}


async def add_subject(db, teacher_code: str, code: str, name: str, roster: list[str]) -> dict:
    from app.services.auth import find_teacher_by_code
    t = await find_teacher_by_code(db, teacher_code)
    if not t:
        raise ValueError("unknown teacher code")
    sid = f"SUB-{normalise_code(code)}-{t['teacher_id']}"
    doc = {"subject_id": sid, "code": normalise_code(code), "name": name, "teacher_id": t["teacher_id"],
           "roster": list(dict.fromkeys(roster))}
    await db.subjects.replace_one({"subject_id": sid}, doc, upsert=True)
    return {"subject_id": sid, "roster_size": len(doc["roster"])}


async def seed_demo(db) -> None:
    if await db.teachers.find_one({}):
        return
    await add_teacher(db, "Demo Teacher", "DEMO-TEACH")
    await add_subject(db, "DEMO-TEACH", "CS301", "Operating Systems", [f"21CT{i:03d}" for i in range(1, 41)])
    await add_subject(db, "DEMO-TEACH", "NW204", "Computer Networks", [f"21CT{i:03d}" for i in range(21, 61)])
