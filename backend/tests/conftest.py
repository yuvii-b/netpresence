import httpx
import pytest
import pytest_asyncio
from mongomock_motor import AsyncMongoMockClient

from app.config import settings
from app.db.mongo import db_instance, ensure_indexes
from app.main import app
from app.services import crypto
from sim.phone import Device  # noqa: F401  (re-exported for the tests)

TEACHER = {"X-Teacher-Token": settings.TEACHER_TOKEN}


@pytest_asyncio.fixture
async def client():
    db_instance.db = AsyncMongoMockClient()["test"]
    await ensure_indexes(db_instance.db)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c
    db_instance.db = None


async def enrol(client, devices):
    for d in devices:
        r = await client.post("/api/devices/register", json=d.register_body())
        assert r.status_code == 201, r.text


async def checkin(client, session, d):
    r = await client.post(f"/api/sessions/{session['session_id']}/checkin",
                          json={"student_id": d.student_id,
                                "signature": d.sign(crypto.checkin_message(session["session_id"], session["nonce"]))})
    assert r.status_code == 200, r.text
    d.eph = r.json()["eph_id"]
    return r.json()
