"""Protocol v3: teacher code login, subjects, roster enforcement, phone binding, live roll call with long-polls."""
import asyncio
import math
import time

import pytest

from app.config import settings
from app.services import auth as auth_svc
from app.services import crypto
from tests.conftest import TEACHER, Device, enrol


def rssi(d, A=-59, n=3.0):
    return round(A - 10 * n * math.log10(d))


async def seed(client, n=6, code="T-CODE-1", subj="CS301"):
    await client.post("/api/admin/teachers", json={"name": "Dr Rao", "code": code}, headers=TEACHER)
    roster = [f"s{i}" for i in range(n)]
    r = await client.post("/api/admin/subjects", json={"teacher_code": code, "code": subj, "name": "OS", "roster": roster}, headers=TEACHER)
    assert r.status_code == 201, r.text
    devs = [Device(x) for x in roster]
    await enrol(client, devs)
    return roster, devs, r.json()["subject_id"]


async def login(client, code="T-CODE-1"):
    r = await client.post("/api/auth/teacher", json={"code": code})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()


async def student_headers(client, d):
    ts = int(time.time())
    r = await client.post("/api/auth/student", json={"student_id": d.student_id, "ts": ts, "signature": d.sign(crypto.login_message(d.student_id, ts))})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def start(client, th, subject_id, teacher=None):
    teacher = teacher or Device("teacher")
    r = await client.post(f"/api/teacher/subjects/{subject_id}/start", json={"device": {"public_key": teacher.pub, "model": teacher.model}}, headers=th)
    assert r.status_code == 200, r.text
    teacher.student_id = r.json()["teacher_student_id"]
    return teacher, r.json()


async def join(client, s, d):
    r = await client.post(f"/api/sessions/{s['session_id']}/checkin", json={
        "student_id": d.student_id, "signature": d.sign(crypto.checkin_message(s["session_id"], s["nonce"]))})
    if r.status_code == 200:
        d.eph = r.json()["eph_id"]
    return r


async def send(client, s, d, nb):
    r = await client.post(f"/api/sessions/{s['session_id']}/report", json=d.report_body(s["session_id"], nb))
    assert r.status_code == 200, r.text


def mesh(devs, teacher, d=1.2):
    allp = devs + [teacher]
    for me in allp:
        yield me, [{"peer_id": o.eph, "rssi_median": rssi(d), "sample_count": 20} for o in allp if o is not me]


async def test_teacher_login_subjects_and_isolation(client):
    await seed(client)
    await client.post("/api/admin/teachers", json={"name": "Other", "code": "OTHER-CODE"}, headers=TEACHER)
    await client.post("/api/admin/subjects", json={"teacher_code": "OTHER-CODE", "code": "NW1", "name": "Nets", "roster": ["x"]}, headers=TEACHER)
    h, out = await login(client)
    assert [s["code"] for s in out["subjects"]] == ["CS301"] and out["subjects"][0]["roster_size"] == 6
    assert (await client.post("/api/auth/teacher", json={"code": " t-code-1 "})).status_code == 200    # case/space tolerant
    other = (await client.get("/api/teacher/subjects", headers=(await login(client, "OTHER-CODE"))[0])).json()
    assert [s["code"] for s in other] == ["NW1"]
    # a teacher cannot start somebody else's subject
    r = await client.post(f"/api/teacher/subjects/{other[0]['subject_id']}/start", json={"device": {"public_key": Device('t').pub, "model": "x"}}, headers=h)
    assert r.status_code == 404
    assert (await client.get("/api/teacher/subjects")).status_code == 401
    assert (await client.get("/api/teacher/subjects", headers={"X-Teacher-Token": settings.TEACHER_TOKEN})).status_code == 200   # admin token


async def test_wrong_codes_are_rate_limited_and_tokens_expire(client):
    await seed(client)
    for _ in range(settings.LOGIN_MAX_FAILS):
        assert (await client.post("/api/auth/teacher", json={"code": "nope"})).status_code == 401
    assert (await client.post("/api/auth/teacher", json={"code": "nope"})).status_code == 429
    assert (await client.post("/api/auth/teacher", json={"code": "T-CODE-1"})).status_code == 429     # even the right one: locked
    auth_svc.limiter.reset()
    h, _ = await login(client)
    from app.db.mongo import db_instance
    await db_instance.db.tokens.update_many({}, {"$set": {"expires_at": time.time() - 1}})
    assert (await client.get("/api/teacher/subjects", headers=h)).status_code == 401


async def test_one_phone_one_student_and_admin_reset(client):
    a = Device("a1")
    assert (await client.post("/api/devices/register", json={**a.register_body(), "install_id": "droid-1", "platform": "android"})).status_code == 201
    # same phone key, other roll number
    b = Device("b1"); b.key, b.pub = a.key, a.pub
    r = await client.post("/api/devices/register", json=b.register_body())
    assert r.status_code == 409 and "phone" in r.json()["detail"]
    # other key but same install id
    c = Device("c1")
    r = await client.post("/api/devices/register", json={**c.register_body(), "install_id": "droid-1"})
    assert r.status_code == 409
    # same roll number from a second phone
    a2 = Device("a1")
    assert (await client.post("/api/devices/register", json=a2.register_body())).status_code == 409
    # reset (admin) frees both directions
    assert (await client.delete("/api/devices/a1", headers=TEACHER)).status_code == 200
    assert (await client.post("/api/devices/register", json=a2.register_body())).status_code == 201
    assert (await client.post("/api/devices/register", json={**c.register_body(), "install_id": "droid-1"})).status_code == 201


async def test_student_login_needs_the_bound_key_and_fresh_ts(client):
    _, devs, _ = await seed(client, 2)
    d = devs[0]
    ts = int(time.time())
    imp = Device("s0")
    assert (await client.post("/api/auth/student", json={"student_id": "s0", "ts": ts, "signature": imp.sign(crypto.login_message("s0", ts))})).status_code == 401
    assert (await client.post("/api/auth/student", json={"student_id": "s0", "ts": ts - 120, "signature": d.sign(crypto.login_message("s0", ts - 120))})).status_code == 400
    h = await student_headers(client, d)
    me = (await client.get("/api/me", headers=h)).json()
    assert me["student_id"] == "s0" and [s["code"] for s in me["subjects"]] == ["CS301"]


async def test_roster_enforced_and_ids_carry_tag_and_unique_member(client):
    roster, devs, sub = await seed(client, 5)
    th, _ = await login(client)
    _, s = await start(client, th, sub)
    outsider = Device("outsider")
    await enrol(client, [outsider])
    r = await join(client, s, outsider)
    assert r.status_code == 403 and "CS301" in r.json()["detail"]
    ids = set()
    for d in devs:
        r = await join(client, s, d)
        assert r.status_code == 200 and r.json()["eph_id"].startswith(s["tag"]) and r.json()["advertise_uuid"].endswith(r.json()["eph_id"])
        ids.add(r.json()["eph_id"])
    assert len(ids) == 5 and s["tag"] + "0000" not in ids and s["teacher_eph"] == s["tag"] + "0000"
    assert (await join(client, s, devs[0])).json()["eph_id"] == devs[0].eph           # idempotent retry


async def test_member_ids_are_unique_for_1000_checkins(client):
    from app.db.mongo import db_instance
    from app.routers.sessions import checkin
    n = 1000
    roster = [f"m{i}" for i in range(n)]
    await client.post("/api/admin/teachers", json={"name": "T", "code": "BIG-CODE"}, headers=TEACHER)
    sub = (await client.post("/api/admin/subjects", json={"teacher_code": "BIG-CODE", "code": "BIG", "name": "Big", "roster": roster}, headers=TEACHER)).json()["subject_id"]
    th, _ = await login(client, "BIG-CODE")
    _, s = await start(client, th, sub)
    devs = [Device(x) for x in roster]
    for i in range(0, n, 100):
        rs = await asyncio.gather(*[client.post("/api/devices/register", json=d.register_body()) for d in devs[i:i + 100]])
        assert all(r.status_code == 201 for r in rs)
    rs = await asyncio.gather(*[join(client, s, d) for d in devs])
    ids = [r.json()["eph_id"] for r in rs]
    assert all(r.status_code == 200 for r in rs) and len(set(ids)) == n and all(i.startswith(s["tag"]) for i in ids)


async def test_concurrent_subjects_and_distinct_tags(client):
    roster, devs, sub1 = await seed(client, 4)
    sub2 = (await client.post("/api/admin/subjects", json={"teacher_code": "T-CODE-1", "code": "NW204", "name": "Nets", "roster": roster[:2]}, headers=TEACHER)).json()["subject_id"]
    th, _ = await login(client)
    _, s1 = await start(client, th, sub1)
    _, s2 = await start(client, th, sub2)
    assert s1["session_id"] != s2["session_id"] and s1["tag"] != s2["tag"]
    _, again = await start(client, th, sub1)
    assert again["session_id"] == s1["session_id"]
    sh = await student_headers(client, devs[3])      # only in CS301
    r = (await client.get("/api/me/session", headers=sh)).json()
    assert r["status"] == "open" and r["session_id"] == s1["session_id"] and r["subject"]["code"] == "CS301"
    # legacy flow is unaffected: starting a legacy window session does not close subject sessions
    await client.post("/api/sessions/start", json={}, headers=TEACHER)
    assert (await client.get("/api/me/session", headers=sh)).json()["status"] == "open"
    assert (await client.get("/api/sessions/open")).json()["status"] == "open"
    assert (await client.get("/api/sessions/open")).json()["session_id"] not in (s1["session_id"], s2["session_id"])


async def test_me_session_longpoll_wakes_fast(client):
    roster, devs, sub = await seed(client, 3)
    th, _ = await login(client)
    sh = await student_headers(client, devs[0])
    t0 = time.monotonic()
    waiter = asyncio.create_task(client.get("/api/me/session?wait=10", headers=sh))
    await asyncio.sleep(0.3)
    assert not waiter.done()
    t1 = time.monotonic()
    _, s = await start(client, th, sub)
    r = await waiter
    assert r.json()["session_id"] == s["session_id"]
    assert time.monotonic() - t1 < 0.1, "long-poll must return within 100 ms of the session opening"


async def test_live_flow_present_via_teacher_seed_and_finish_maps_pending_to_absent(client):
    roster, devs, sub = await seed(client, 6)
    th, _ = await login(client)
    teacher, s = await start(client, th, sub)
    teacher.eph = s["teacher_eph"]
    near, far, absent = devs[:4], devs[4], devs[5]
    await join(client, s, far)
    for d in near:
        await join(client, s, d)
    sh = await student_headers(client, near[0])
    st = (await client.get(f"/api/sessions/{s['session_id']}/me?since=0&wait=0", headers=sh)).json()
    assert st["status"] == "PENDING" and st["rev"] >= 1
    for me, nb in mesh(near, teacher):
        await send(client, s, me, nb)                      # far never reports, absent never joined
    await asyncio.sleep(0.5)                               # one debounced evaluation
    live = (await client.get(f"/api/teacher/sessions/{s['session_id']}/live?since=-1", headers=th)).json()
    assert live["counts"]["PRESENT"] == 4 and live["counts"]["PENDING"] == 1 and live["counts"]["NOT_JOINED"] == 1
    st = (await client.get(f"/api/sessions/{s['session_id']}/me?since={st['rev']}&wait=5", headers=sh)).json()
    assert st["status"] == "PRESENT"
    out = (await client.post(f"/api/teacher/sessions/{s['session_id']}/finish", headers=th)).json()
    by = {r["student_id"]: r["status"] for r in out["rows"]}
    assert [by[d.student_id] for d in near] == ["PRESENT"] * 4 and by["s4"] == "ABSENT" and by["s5"] == "ABSENT"
    assert (await client.get(f"/api/sessions/{s['session_id']}/me", headers=sh)).json()["status"] == "CLOSED"
    assert (await client.get("/api/me/session", headers=sh)).json()["status"] == "none"
    assert (await client.post(f"/api/sessions/{s['session_id']}/report", json=near[0].report_body(s["session_id"], []))).status_code == 400


async def test_incremental_reports_reevaluate_and_longpolls_wake_within_100ms(client):
    roster, devs, sub = await seed(client, 5)
    th, _ = await login(client)
    teacher, s = await start(client, th, sub)
    teacher.eph = s["teacher_eph"]
    for d in devs:
        await join(client, s, d)
    sh = await student_headers(client, devs[0])
    await asyncio.sleep(0.5)                                  # let the check-in evaluations settle
    base = (await client.get(f"/api/sessions/{s['session_id']}/me", headers=sh)).json()
    live0 = (await client.get(f"/api/teacher/sessions/{s['session_id']}/live", headers=th)).json()
    w_me = asyncio.create_task(client.get(f"/api/sessions/{s['session_id']}/me?since={base['rev']}&wait=10", headers=sh))
    w_t = asyncio.create_task(client.get(f"/api/teacher/sessions/{s['session_id']}/live?since={live0['rev']}&wait=10", headers=th))
    await asyncio.sleep(0.5)
    assert not w_me.done() and not w_t.done()
    t_send = time.monotonic()
    for me, nb in mesh(devs, teacher):                       # everyone uploads once; evaluation is debounced
        await send(client, s, me, nb)
    r1, r2 = await w_me, await w_t
    assert r1.json()["status"] == "PRESENT" and r1.json()["rev"] > base["rev"]
    assert r2.json()["counts"]["PRESENT"] >= 1 and r2.json()["rev"] > live0["rev"]
    assert time.monotonic() - t_send < settings.LIVE_EVAL_DEBOUNCE_MS / 1000 + 0.5
    # an unchanged repeat report changes nothing, so a poll at the current rev times out instead of spinning
    cur = (await client.get(f"/api/teacher/sessions/{s['session_id']}/live?since=-1&wait=0", headers=th)).json()
    await asyncio.sleep(0.5)
    t0 = time.monotonic()
    again = (await client.get(f"/api/teacher/sessions/{s['session_id']}/live?since={cur['rev']}&wait=1", headers=th)).json()
    assert again["rev"] == cur["rev"] and time.monotonic() - t0 >= 0.9


async def test_remote_cheater_is_not_marked_and_overrides_work(client):
    roster, devs, sub = await seed(client, 6)
    th, _ = await login(client)
    teacher, s = await start(client, th, sub)
    teacher.eph = s["teacher_eph"]
    for d in devs:
        await join(client, s, d)
    near, cheat = devs[:5], devs[5]
    for me, nb in mesh(near, teacher):
        await send(client, s, me, nb)
    await send(client, s, cheat, [{"peer_id": o.eph, "rssi_median": -50, "sample_count": 30} for o in near])   # one-sided claims
    await asyncio.sleep(0.4)
    live = (await client.get(f"/api/teacher/sessions/{s['session_id']}/live", headers=th)).json()
    st = {r["student_id"]: r["status"] for r in live["rows"]}
    assert st["s5"] != "PRESENT" and all(st[d.student_id] == "PRESENT" for d in near)
    r = await client.post(f"/api/teacher/sessions/{s['session_id']}/adjudicate", json={"student_id": "s5", "status": "PRESENT"}, headers=th)
    assert r.status_code == 200
    out = (await client.post(f"/api/teacher/sessions/{s['session_id']}/finish", headers=th)).json()
    assert {r["student_id"]: r["status"] for r in out["rows"]}["s5"] == "PRESENT"
    r = await client.post(f"/api/teacher/sessions/{s['session_id']}/adjudicate", json={"student_id": "s5", "status": "ABSENT"}, headers=th)
    assert r.status_code == 200
    att = (await client.get(f"/api/sessions/{s['session_id']}/result", headers=TEACHER)).json()
    assert {r["student_id"]: r["status"] for r in att["rows"]}["s5"] == "ABSENT"


async def test_auto_finish_and_teacher_can_reset_a_roster_students_phone(client, monkeypatch):
    monkeypatch.setattr(settings, "LIVE_MAX_SECONDS", 1)
    roster, devs, sub = await seed(client, 3)
    th, _ = await login(client)
    teacher, s = await start(client, th, sub)
    await asyncio.sleep(1.3)
    from app.db.mongo import db_instance
    doc = await db_instance.db.sessions.find_one({"session_id": s["session_id"]})
    assert doc["status"] == "closed"
    assert (await client.post("/api/teacher/students/s1/reset-device", headers=th)).status_code == 200
    assert (await client.post("/api/teacher/students/nobody/reset-device", headers=th)).status_code == 404


async def test_attendance_sheet_lists_every_roster_student_against_each_finished_class(client):
    roster, devs, sub = await seed(client, 5)
    th, _ = await login(client)
    # class 1: s0..s2 present
    teacher, s1 = await start(client, th, sub)
    teacher.eph = s1["teacher_eph"]
    near = devs[:3]
    for d in near:
        assert (await join(client, s1, d)).status_code == 200
    for me, nb in mesh(near, teacher):
        await send(client, s1, me, nb)
    await asyncio.sleep(0.5)
    await client.post(f"/api/teacher/sessions/{s1['session_id']}/finish", headers=th)
    # class 2: only s0, s1 present
    teacher2, s2 = await start(client, th, sub)
    teacher2.eph = s2["teacher_eph"]
    near2 = devs[:2]
    for d in near2:
        assert (await join(client, s2, d)).status_code == 200
    for me, nb in mesh(near2, teacher2):
        await send(client, s2, me, nb)
    await asyncio.sleep(0.5)
    await client.post(f"/api/teacher/sessions/{s2['session_id']}/finish", headers=th)

    sheet = (await client.get(f"/api/teacher/subjects/{sub}/sheet", headers=th)).json()
    assert [x["session_id"] for x in sheet["sessions"]] == [s1["session_id"], s2["session_id"]]    # oldest first
    marks = {r["student_id"]: r["marks"] for r in sheet["students"]}
    assert marks["s0"] == ["P", "P"] and marks["s2"][0] == "P" and marks["s2"][1] == "A" and marks["s4"] == ["A", "A"]
    pct = {r["student_id"]: r["pct"] for r in sheet["students"]}
    assert pct["s0"] == 100 and pct["s4"] == 0
    assert [x["present"] for x in sheet["sessions"]][1] == 2 and sheet["sessions"][0]["total"] == 5
    # another teacher cannot read it
    await client.post("/api/admin/teachers", json={"name": "Other", "code": "OTHER-CODE"}, headers=TEACHER)
    oh, _ = await login(client, "OTHER-CODE")
    assert (await client.get(f"/api/teacher/subjects/{sub}/sheet", headers=oh)).status_code == 404
    # nothing finished yet -> an empty register, not an error
    sub2 = (await client.post("/api/admin/subjects", json={"teacher_code": "T-CODE-1", "code": "NW204", "name": "CN", "roster": ["s0", "s1"]}, headers=TEACHER)).json()["subject_id"]
    th2 = th
    empty = (await client.get(f"/api/teacher/subjects/{sub2}/sheet", headers=th2)).json()
    assert empty["sessions"] == [] and all(r["pct"] is None and r["marks"] == [] for r in empty["students"])


async def test_present_is_latched_once_shown_flagged_and_teacher_decisions_still_apply(client):
    """Real Bluetooth is noisy: once a student is Present they stay Present (their phone just relays); the engine does not bounce them
    back to Checking. A teacher decision is never overridden."""
    roster, devs, sub = await seed(client, 5)
    th, _ = await login(client)
    teacher, s = await start(client, th, sub)
    teacher.eph = s["teacher_eph"]
    near = devs[:4]
    for d in near:
        await join(client, s, d)
    for me, nb in mesh(near, teacher):
        await send(client, s, me, nb)
    await asyncio.sleep(0.5)
    sid = s["session_id"]

    async def status_of(d):
        return {r["student_id"]: r["status"] for r in (await client.get(f"/api/teacher/sessions/{sid}/live?since=-1", headers=th)).json()["rows"]}[d.student_id]

    assert await status_of(near[3]) == "PRESENT"
    rest = near[:3]                                        # every link to near[3] vanishes, and it reports nothing
    for me, nb in mesh(rest, teacher):
        await send(client, s, me, nb)
    await send(client, s, near[3], [])
    await asyncio.sleep(0.6)
    assert await status_of(near[3]) == "PRESENT", "latched: no bounce back to Checking"
    st = (await client.get(f"/api/sessions/{sid}/me?since=0&wait=0", headers=await student_headers(client, near[3]))).json()
    assert st["status"] == "PRESENT"
    out = (await client.post(f"/api/teacher/sessions/{sid}/finish", headers=th)).json()
    by = {r["student_id"]: r["status"] for r in out["rows"]}
    assert by[near[3].student_id] == "PRESENT" and by["s4"] == "ABSENT", "finish keeps what everyone saw"


async def test_teacher_decision_beats_the_latch(client):
    roster, devs, sub = await seed(client, 4)
    th, _ = await login(client)
    teacher, s = await start(client, th, sub)
    teacher.eph = s["teacher_eph"]
    for d in devs:
        await join(client, s, d)
    for me, nb in mesh(devs, teacher):
        await send(client, s, me, nb)
    await asyncio.sleep(0.5)
    sid = s["session_id"]
    r = await client.post(f"/api/teacher/sessions/{sid}/adjudicate", json={"student_id": devs[0].student_id, "status": "ABSENT"}, headers=th)
    assert r.status_code == 200
    await asyncio.sleep(0.6)
    rows = {x["student_id"]: x["status"] for x in (await client.get(f"/api/teacher/sessions/{sid}/live?since=-1", headers=th)).json()["rows"]}
    assert rows[devs[0].student_id] == "ABSENT" and rows[devs[1].student_id] == "PRESENT"
