import base64
import json

import httpx
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from mongomock_motor import AsyncMongoMockClient

from app.config import settings
from app.db.mongo import db_instance, ensure_indexes
from app.main import app
from app.services import crypto

TEACHER = {"X-Teacher-Token": settings.TEACHER_TOKEN}


class Device:
    """A fake phone: holds a P-256 key and signs exactly what the real clients must sign."""

    def __init__(self, student_id, model="Pixel 6"):
        self.student_id, self.model = student_id, model
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.pub = base64.b64encode(self.key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
        self.eph = None

    def sign(self, msg: str) -> str:
        return base64.b64encode(self.key.sign(msg.encode(), ec.ECDSA(hashes.SHA256()))).decode()

    def register_body(self, name=None):
        return {"student_id": self.student_id, "name": name or self.student_id, "model": self.model,
                "public_key": self.pub, "signature": self.sign(crypto.register_message(self.student_id, self.model))}

    def report_body(self, session_id, neighbours):
        return {"student_id": self.student_id, "neighbours": neighbours,
                "signature": self.sign(crypto.report_message(session_id, self.student_id, neighbours))}


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
