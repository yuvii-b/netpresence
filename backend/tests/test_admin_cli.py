from mongomock_motor import AsyncMongoMockClient

from tools import admin


async def test_admin_cli_seeds_teacher_subject_and_resets(tmp_path, capsys):
    db = AsyncMongoMockClient()["cli"]
    csv_path = tmp_path / "r.csv"
    csv_path.write_text("student_id,name\n21CT001,A\n21CT002,B\n\n21CT001,dup\n", encoding="utf-8")
    assert await admin.main(["add-teacher", "--name", "Dr X", "--code", "X-CODE"], db) == 0
    assert await admin.main(["add-subject", "--teacher-code", "X-CODE", "--code", "cs1", "--name", "OS", "--roster", str(csv_path)], db) == 0
    assert await admin.main(["add-subject", "--teacher-code", "WRONG", "--code", "cs2", "--name", "OS", "--roster", str(csv_path)], db) == 1
    sub = await db.subjects.find_one({"code": "CS1"})
    assert sub["roster"] == ["21CT001", "21CT002"]
    t = await db.teachers.find_one({})
    assert "X-CODE" not in str(t) and len(t["code_hash"]) == 64          # only a salted hash is stored
    await db.students.insert_one({"student_id": "21CT001"})
    assert await admin.main(["reset-device", "--student", "21CT001"], db) == 0
    assert await admin.main(["reset-device", "--student", "21CT001"], db) == 1
    assert await admin.main(["list"], db) == 0
    assert "CS1" in capsys.readouterr().out
