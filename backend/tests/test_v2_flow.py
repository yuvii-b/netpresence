import math

from app.services import crypto
from tests.conftest import TEACHER, Device, checkin, enrol


def rssi(d, A=-59, n=3.0):
    return round(A - 10 * n * math.log10(d))


async def make_room(client, n=5):
    devs = [Device(f"stu{i}") for i in range(n)]
    await enrol(client, devs)
    s = (await client.post("/api/sessions/start", json={}, headers=TEACHER)).json()
    for d in devs:
        await checkin(client, s, d)
    return s, devs


def full_mesh(devs, d=1.5):
    """Everyone sees everyone at d metres."""
    for me in devs:
        nb = [{"peer_id": o.eph, "rssi_median": rssi(d), "sample_count": 20} for o in devs if o is not me]
        yield me, nb


async def test_happy_path(client):
    s, devs = await make_room(client)
    for me, nb in full_mesh(devs):
        r = await client.post(f"/api/sessions/{s['session_id']}/report", json=me.report_body(s["session_id"], nb))
        assert r.status_code == 200, r.text
    r = await client.post(f"/api/sessions/{s['session_id']}/verify-seeds", json={"student_ids": ["stu0"]}, headers=TEACHER)
    assert r.status_code == 200
    out = (await client.post(f"/api/sessions/{s['session_id']}/close", headers=TEACHER)).json()
    assert out["counts"] == {"PRESENT": 5, "FLAGGED": 0, "ABSENT": 0}
    res = (await client.get(f"/api/sessions/{s['session_id']}/result", headers=TEACHER)).json()
    assert res["counts"]["PRESENT"] == 5


async def test_remote_cheater_is_flagged_and_noncheckin_absent(client):
    s, devs = await make_room(client, 4)
    cheater = Device("remote")
    await enrol(client, [cheater])
    await checkin(client, s, cheater)
    absent = Device("never-came")
    await enrol(client, [absent])
    for me, nb in full_mesh(devs):                        # real students see each other, nobody sees `remote`
        await client.post(f"/api/sessions/{s['session_id']}/report", json=me.report_body(s["session_id"], nb))
    # the cheater claims strong edges to everybody, but nobody reports them back (one-sided)
    nb = [{"peer_id": o.eph, "rssi_median": -50, "sample_count": 30} for o in devs]
    r = await client.post(f"/api/sessions/{s['session_id']}/report", json=cheater.report_body(s["session_id"], nb))
    assert r.status_code == 200
    await client.post(f"/api/sessions/{s['session_id']}/verify-seeds", json={"student_ids": ["stu0"]}, headers=TEACHER)
    out = (await client.post(f"/api/sessions/{s['session_id']}/close", headers=TEACHER)).json()
    st = {r["student_id"]: r["status"] for r in out["rows"]}
    assert st["remote"] == "FLAGGED" and st["never-came"] == "ABSENT"
    assert all(st[f"stu{i}"] == "PRESENT" for i in range(4))
    # teacher adjudicates the flagged one
    r = await client.post(f"/api/sessions/{s['session_id']}/adjudicate", json={"student_id": "remote", "status": "ABSENT"}, headers=TEACHER)
    assert r.status_code == 200
    res = (await client.get(f"/api/sessions/{s['session_id']}/result", headers=TEACHER)).json()
    assert {r["student_id"]: r["decided_by"] for r in res["rows"]}["remote"] == "teacher"


async def test_colluders_can_vouch_k_but_not_fewer(client):
    """Documented limit: k colluders physically present can vouch for one absent friend; k-1 cannot."""
    s, devs = await make_room(client, 4)
    friend = Device("friend")
    await enrol(client, [friend])
    await checkin(client, s, friend)
    by_id = {d.student_id: d for d in devs}
    for me, nb in full_mesh(devs):
        if me.student_id in ("stu1", "stu2"):             # two colluders fabricate mutual edges with friend
            nb.append({"peer_id": friend.eph, "rssi_median": rssi(1.0), "sample_count": 30})
        await client.post(f"/api/sessions/{s['session_id']}/report", json=me.report_body(s["session_id"], nb))
    fb = [{"peer_id": by_id[i].eph, "rssi_median": rssi(1.0), "sample_count": 30} for i in ("stu1", "stu2")]
    await client.post(f"/api/sessions/{s['session_id']}/report", json=friend.report_body(s["session_id"], fb))
    await client.post(f"/api/sessions/{s['session_id']}/verify-seeds", json={"student_ids": ["stu0"]}, headers=TEACHER)
    out = (await client.post(f"/api/sessions/{s['session_id']}/close", headers=TEACHER)).json()
    assert {r["student_id"]: r["status"] for r in out["rows"]}["friend"] == "PRESENT"   # k=2 colluders suffice


async def test_signature_and_auth_enforced(client):
    s, devs = await make_room(client, 3)
    me = devs[0]
    # wrong signer
    body = me.report_body(s["session_id"], [{"peer_id": devs[1].eph, "rssi_median": -60, "sample_count": 5}])
    body["signature"] = devs[1].sign("whatever")
    assert (await client.post(f"/api/sessions/{s['session_id']}/report", json=body)).status_code == 401
    # tampered payload after signing
    body = me.report_body(s["session_id"], [{"peer_id": devs[1].eph, "rssi_median": -60, "sample_count": 5}])
    body["neighbours"][0]["rssi_median"] = -40
    assert (await client.post(f"/api/sessions/{s['session_id']}/report", json=body)).status_code == 401
    # teacher endpoints need the token
    assert (await client.post("/api/sessions/start", json={})).status_code == 401
    assert (await client.post(f"/api/sessions/{s['session_id']}/close")).status_code == 401
    # close requires a seed
    assert (await client.post(f"/api/sessions/{s['session_id']}/close", headers=TEACHER)).status_code == 400
    # cannot seed someone who hasn't checked in
    assert (await client.post(f"/api/sessions/{s['session_id']}/verify-seeds", json={"student_ids": ["ghost"]}, headers=TEACHER)).status_code == 400


async def test_enrolment_rules(client):
    d = Device("a1")
    await enrol(client, [d])
    assert (await client.post("/api/devices/register", json=Device("a1").register_body())).status_code == 409   # no hijack
    bad = Device("b1").register_body()
    bad["signature"] = Device("b1").register_body()["signature"]                                                # key mismatch
    assert (await client.post("/api/devices/register", json=bad)).status_code == 400
    assert (await client.delete("/api/devices/a1")).status_code == 401
    assert (await client.delete("/api/devices/a1", headers=TEACHER)).status_code == 200
    assert (await client.post("/api/devices/register", json=Device("a1").register_body())).status_code == 201


async def test_checkin_idempotent_and_ephemeral_ids_unique(client):
    s, devs = await make_room(client, 6)
    assert len({d.eph for d in devs}) == 6
    again = await checkin(client, s, devs[0])
    assert again["eph_id"] == devs[0].eph and again["advertise_name"] == f"NP-{devs[0].eph}"


async def test_model_calibration_offset_applied(client):
    # iPhone reads 10 dB lower than reference; without an offset the edge (implied ~4.5m) is rejected
    a, b, c = Device("a"), Device("b"), Device("c", model="iPhone 12")
    await enrol(client, [a, b, c])
    s = (await client.post("/api/sessions/start", json={}, headers=TEACHER)).json()
    for d in (a, b, c):
        await checkin(client, s, d)

    async def run(offset):
        await client.put("/api/devices/calibration", json={"model": "iPhone 12", "rssi_offset_db": offset}, headers=TEACHER)
        for me, others in ((a, (b, c)), (b, (a, c)), (c, (a, b))):
            nb = [{"peer_id": o.eph, "rssi_median": rssi(1.5) - (10 if me is c else 0), "sample_count": 10} for o in others]
            await client.post(f"/api/sessions/{s['session_id']}/report", json=me.report_body(s["session_id"], nb))
        await client.post(f"/api/sessions/{s['session_id']}/verify-seeds", json={"student_ids": ["a"]}, headers=TEACHER)
        out = (await client.post(f"/api/sessions/{s['session_id']}/close", headers=TEACHER)).json()
        return {r["student_id"]: r["status"] for r in out["rows"]}

    assert (await run(10.0))["c"] == "PRESENT"


async def test_windows_enforced(client):
    s, devs = await make_room(client, 2)
    from app.db.mongo import db_instance
    await db_instance.db.sessions.update_one({"session_id": s["session_id"]}, {"$set": {"window_ends_at": 0, "report_deadline": 0}})
    late = Device("late")
    await enrol(client, [late])
    r = await client.post(f"/api/sessions/{s['session_id']}/checkin", json={"student_id": "late", "signature": late.sign(crypto.checkin_message(s["session_id"], s["nonce"]))})
    assert r.status_code == 400
    r = await client.post(f"/api/sessions/{s['session_id']}/report", json=devs[0].report_body(s["session_id"], []))
    assert r.status_code in (400, 422)
    assert (await client.get("/api/sessions/open")).json()["status"] == "none"


async def test_single_colluder_cannot_vouch_with_k2(client):
    s, devs = await make_room(client, 4)
    friend = Device("friend")
    await enrol(client, [friend])
    await checkin(client, s, friend)
    for me, nb in full_mesh(devs):
        if me.student_id == "stu1":                       # only ONE colluder vouches
            nb.append({"peer_id": friend.eph, "rssi_median": rssi(1.0), "sample_count": 30})
        await client.post(f"/api/sessions/{s['session_id']}/report", json=me.report_body(s["session_id"], nb))
    fb = [{"peer_id": devs[1].eph, "rssi_median": rssi(1.0), "sample_count": 30}]
    await client.post(f"/api/sessions/{s['session_id']}/report", json=friend.report_body(s["session_id"], fb))
    await client.post(f"/api/sessions/{s['session_id']}/verify-seeds", json={"student_ids": ["stu0"]}, headers=TEACHER)
    out = (await client.post(f"/api/sessions/{s['session_id']}/close", headers=TEACHER)).json()
    assert {r["student_id"]: r["status"] for r in out["rows"]}["friend"] == "FLAGGED"


async def test_headcount_flags_least_corroborated_present(client):
    s, devs = await make_room(client, 5)
    # stu4 is only weakly corroborated: linked to stu0 and stu1 only; the rest form a tight clique
    for me, nb in full_mesh(devs):
        if me.student_id == "stu4":
            nb = [x for x in nb if x["peer_id"] in (devs[0].eph, devs[1].eph)]
        elif me.student_id in ("stu2", "stu3"):
            nb = [x for x in nb if x["peer_id"] != devs[4].eph]
        await client.post(f"/api/sessions/{s['session_id']}/report", json=me.report_body(s["session_id"], nb))
    await client.post(f"/api/sessions/{s['session_id']}/verify-seeds", json={"student_ids": ["stu0"]}, headers=TEACHER)
    out = (await client.post(f"/api/sessions/{s['session_id']}/close", headers=TEACHER, json={"headcount": 4})).json()
    assert out["counts"]["PRESENT"] == 5 and out["gap"] == 1 and out["review"] == 1
    assert [r["student_id"] for r in out["rows"] if r.get("review")] == ["stu4"]
    # teacher confirms; the review flag clears
    await client.post(f"/api/sessions/{s['session_id']}/adjudicate", json={"student_id": "stu4", "status": "ABSENT"}, headers=TEACHER)
    res = (await client.get(f"/api/sessions/{s['session_id']}/result", headers=TEACHER)).json()
    assert res["review"] == 0 and res["gap"] == 1 and res["headcount"] == 4


async def test_server_time_is_exposed_for_clock_skew_correction(client):
    import time
    s, devs = await make_room(client, 2)
    o = (await client.get("/api/sessions/open")).json()
    assert abs(o["server_time"] - time.time()) < 5 and o["window_ends_at"] > o["server_time"]
    c = await checkin(client, s, devs[0])
    assert abs(c["server_time"] - time.time()) < 5


async def test_fast_timing_and_identity_in_the_service_uuid(client):
    from app.config import settings
    from app.routers.sessions import SERVICE_UUID
    a = Device("t1")
    await enrol(client, [a])
    s = (await client.post("/api/sessions/start", json={}, headers=TEACHER)).json()
    assert abs(s["discovery_ends_at"] - s["window_ends_at"] - settings.DISCOVERY_TAIL_SECONDS) < 1e-6
    assert s["report_deadline"] > s["discovery_ends_at"]
    r = await checkin(client, s, a)
    assert r["advertise_uuid"].startswith(SERVICE_UUID[:-12] + "6500") and r["advertise_uuid"].endswith(r["eph_id"])
    assert r["discovery_ends_at"] == s["discovery_ends_at"]
    opened = (await client.get("/api/sessions/open")).json()
    assert opened["discovery_ends_at"] == s["discovery_ends_at"]


async def test_enrolment_code_when_configured(client, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "ENROL_CODE", "BLUE42")
    d = Device("c1")
    assert (await client.post("/api/devices/register", json=d.register_body())).status_code == 403
    assert (await client.post("/api/devices/register", json={**d.register_body(), "enrol_code": "blue42"})).status_code == 403
    assert (await client.post("/api/devices/register", json={**d.register_body(), "enrol_code": "BLUE42"})).status_code == 201


async def test_malformed_keys_are_rejected_not_crashing(client):
    import base64
    d = Device("m1")
    for bad in (base64.b64encode(b"\x04" + b"\x00" * 64).decode(),            # not a point on P-256
                base64.b64encode(b"\x30\x03\x02\x01\x01").decode(),             # DER garbage
                base64.b64encode(b"hello").decode()):
        r = await client.post("/api/devices/register", json={**d.register_body(), "public_key": bad})
        assert r.status_code == 400, (bad, r.status_code)
