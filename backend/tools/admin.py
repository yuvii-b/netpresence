"""Seed and manage teachers, subjects and rosters (talks to the MongoDB in MONGO_URL / DB_NAME, like the server).

    python -m tools.admin add-teacher --name "Dr Rao" --code RAO-2026
    python -m tools.admin add-subject --teacher-code RAO-2026 --code CS301 --name "Operating Systems" --roster roster.csv
    python -m tools.admin reset-device --student 21CT042
    python -m tools.admin list

roster.csv: one student per line; first column is the roll number (a header row named student_id/roll is skipped).
Teacher codes are stored salted+hashed: keep a copy, they cannot be read back.
"""
import argparse
import asyncio
import csv
import sys

from motor.motor_asyncio import AsyncIOMotorClient

from app.config import settings
from app.services import seed


def read_roster(path: str) -> list[str]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        ids = [row[0].strip() for row in csv.reader(f) if row and row[0].strip()]
    return [i for i in ids if i.lower() not in ("student_id", "roll", "roll_no", "roll number")]


async def main(argv=None, db=None) -> int:
    ap = argparse.ArgumentParser(prog="tools.admin")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("add-teacher"); t.add_argument("--name", required=True); t.add_argument("--code", required=True)
    s = sub.add_parser("add-subject"); s.add_argument("--teacher-code", required=True); s.add_argument("--code", required=True)
    s.add_argument("--name", required=True); s.add_argument("--roster", required=True, help="CSV file")
    r = sub.add_parser("reset-device"); r.add_argument("--student", required=True)
    sub.add_parser("list")
    a = ap.parse_args(argv)
    if db is None:
        db = AsyncIOMotorClient(settings.MONGO_URL)[settings.DB_NAME]
    if a.cmd == "add-teacher":
        print("teacher added:", await seed.add_teacher(db, a.name, a.code))
    elif a.cmd == "add-subject":
        try:
            print("subject saved:", await seed.add_subject(db, a.teacher_code, a.code, a.name, read_roster(a.roster)))
        except ValueError as e:
            print("error:", e)
            return 1
    elif a.cmd == "reset-device":
        res = await db.students.delete_one({"student_id": a.student})
        print("device reset" if res.deleted_count else "no such student")
        return 0 if res.deleted_count else 1
    else:
        async for tch in db.teachers.find({}, {"_id": 0}):
            print(f"{tch['teacher_id']}  {tch['name']}")
            async for sb in db.subjects.find({"teacher_id": tch["teacher_id"]}, {"_id": 0}):
                print(f"    {sb['code']:8} {sb['name']}  ({len(sb['roster'])} students)")
        print(f"{await db.students.count_documents({})} phones registered")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
