from tests.conftest import TEACHER


async def test_acoustic_flow_and_no_token_leak(client):
    r = await client.post("/api/acoustic/sessions/start", json={"session_id": "S1", "token": "A7X"})
    assert r.status_code == 401                                                      # teacher only
    r = await client.post("/api/acoustic/sessions/start", json={"session_id": "S1", "token": "A7X"}, headers=TEACHER)
    assert r.status_code == 200 and "token" not in r.json()
    lst = (await client.get("/api/acoustic/sessions/list")).json()
    assert lst[0]["session_id"] == "S1" and "token" not in lst[0]                    # leak fixed
    sub = {"session_id": "S1", "student_id": "stu1", "decoded_token": "A7X"}
    assert (await client.post("/api/acoustic/attendance/submit", json={**sub, "decoded_token": "ZZZ"})).status_code == 400
    assert (await client.post("/api/acoustic/attendance/submit", json=sub)).status_code == 200
    assert (await client.post("/api/acoustic/attendance/submit", json=sub)).status_code == 400   # single-use
    from app.db.mongo import db_instance
    doc = await db_instance.db.acoustic_attendance.find_one({"student_id": "stu1"})
    assert isinstance(doc["timestamp"], float)                                       # real timestamp, not the token


async def test_acoustic_expiry_and_trials(client):
    from app.db.mongo import db_instance
    await client.post("/api/acoustic/sessions/start", json={"session_id": "S2", "token": "B"}, headers=TEACHER)
    await db_instance.db.acoustic_sessions.update_one({"session_id": "S2"}, {"$set": {"expires_at": 0}})
    r = await client.post("/api/acoustic/attendance/submit", json={"session_id": "S2", "student_id": "x", "decoded_token": "B"})
    assert r.status_code == 400 and "expired" in r.json()["detail"]
    for ok, seat in ((True, "front"), (True, "front"), (False, "back"), (False, "back"), (True, "back")):
        t = {"session_id": "S2", "success": ok, "seat_position": seat, "fan_on": seat == "back", "device_model": "iPhone 12"}
        assert (await client.post("/api/acoustic/trials", json=t)).status_code == 201
    summ = (await client.get("/api/acoustic/trials/summary", headers=TEACHER)).json()
    by = {r["key"]: r for r in summ["seat_position"]}
    assert by["front"]["detection_rate"] == 1.0 and abs(by["back"]["detection_rate"] - 0.333) < 0.01
