import pytest
from mongomock_motor import AsyncMongoMockClient
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import settings
from app.db.mongo import db_instance
from app.main import app
from app.services import crypto
from tests.conftest import Device


def test_session_scoped_ws_receives_checkin_and_rejects_bad_token():
    db_instance.db = AsyncMongoMockClient()["ws"]
    c = TestClient(app)              # not used as a context manager, so the real-Mongo lifespan is skipped
    h = {"X-Teacher-Token": settings.TEACHER_TOKEN}
    d = Device("w1")
    assert c.post("/api/devices/register", json=d.register_body()).status_code == 201
    s = c.post("/api/sessions/start", json={}, headers=h).json()
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect(f"/api/sessions/ws/{s['session_id']}?token=nope"):
            pass
    with c.websocket_connect(f"/api/sessions/ws/{s['session_id']}?token={settings.TEACHER_TOKEN}") as ws:
        sig = d.sign(crypto.checkin_message(s["session_id"], s["nonce"]))
        assert c.post(f"/api/sessions/{s['session_id']}/checkin", json={"student_id": "w1", "signature": sig}).status_code == 200
        msg = ws.receive_json()
        assert msg["type"] == "CHECKIN" and msg["student_id"] == "w1"
    db_instance.db = None
