import asyncio
import json
from unittest.mock import AsyncMock, Mock

import anyio
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from starlette.websockets import WebSocketDisconnect

from app import database
from app.auth import hash_password
from app.main import app
from app.models import Doctor, Patient, Reading
from app.websocket_manager import ConnectionManager, manager


def receive_event(websocket, timeout=2):
    # TestClient has no public receive timeout. Bound its underlying receive so
    # regressions fail quickly instead of hanging the test suite.
    async def receive():
        with anyio.fail_after(timeout):
            return await websocket._send_rx.receive()

    message = websocket.portal.call(receive)
    assert message["type"] == "websocket.send"
    return json.loads(message["text"])


@pytest.fixture
def client(isolated_database):
    manager.connections.clear()
    with database.SessionLocal() as db:
        doctor = Doctor(name="Stream Doctor", email="stream@example.com", password_hash=hash_password("test-password"))
        other = Doctor(name="Other Doctor", email="other@example.com", password_hash="unused-test-hash")
        db.add_all([
            Patient(id=42, name="Patient A", age=45, gender="Male", doctor=doctor),
            Patient(id=43, name="Patient B", age=32, gender="Female", doctor=doctor),
            Patient(id=99, name="Other Patient", age=61, gender="Male", doctor=other),
        ])
        db.commit()
    try:
        with TestClient(app, follow_redirects=False) as client:
            yield client
        assert manager.connections == {}
    finally:
        manager.connections.clear()


def login(client):
    assert client.post("/login", data={"email": "stream@example.com", "password": "test-password"}).status_code == 303


def post_reading(client, patient_id=42):
    return client.post("/api/readings", json={
        "patient_id": patient_id, "heart_rate": 78, "spo2": 98, "temperature_c": 36.8,
    })


def test_unauthenticated_connection_rejected(client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/patients/42"):
            pytest.fail("Unauthenticated connection accepted")
    assert exc.value.code == 1008
    assert manager.connections == {}


@pytest.mark.parametrize("patient_id", [99, 999, 0, -1, 2**63])
def test_other_doctor_missing_or_invalid_patient_rejected(client, patient_id):
    login(client)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/ws/patients/{patient_id}"):
            pytest.fail("Unauthorized connection accepted")
    assert exc.value.code == 1008
    assert manager.connections == {}


def test_tampered_session_rejected(client):
    login(client)
    cookie = client.cookies["healthguard_session"]
    client.cookies.clear()
    client.cookies.set("healthguard_session", "X" + cookie[1:])
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/patients/42"):
            pytest.fail("Tampered cookie accepted")
    assert exc.value.code == 1008


def test_cross_origin_connection_rejected(client):
    login(client)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/patients/42", headers={"origin": "https://other.example"}):
            pytest.fail("Cross-origin connection accepted")
    assert exc.value.code == 1008


def test_logged_out_connection_rejected(client):
    login(client)
    client.post("/logout")
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/patients/42"):
            pytest.fail("Logged-out connection accepted")


def test_broadcast_matches_committed_reading_and_cleans_up(client, monkeypatch):
    login(client)
    original_broadcast = manager.broadcast

    async def verify_commit(patient_id, message):
        # A separate session can see the row before the broadcast is attempted.
        with database.SessionLocal() as db:
            reading = db.get(Reading, message["data"]["id"])
            assert reading is not None
            assert reading.patient_id == patient_id
        await original_broadcast(patient_id, message)

    spy = AsyncMock(side_effect=verify_commit)
    monkeypatch.setattr(manager, "broadcast", spy)
    with client.websocket_connect("/ws/patients/42", headers={"origin": "http://testserver"}) as websocket:
        assert receive_event(websocket) == {"type": "connected", "patient_id": 42}
        response = post_reading(client)
        assert response.status_code == 201
        assert receive_event(websocket) == {"type": "reading", "data": response.json()}
        spy.assert_awaited_once()
        assert len(manager.connections[42]) == 1
    assert manager.connections == {}


def test_multiple_viewers_and_patient_isolation(client):
    login(client)
    with client.websocket_connect("/ws/patients/42") as first, \
            client.websocket_connect("/ws/patients/42") as second, \
            client.websocket_connect("/ws/patients/43") as other:
        for websocket, patient_id in [(first, 42), (second, 42), (other, 43)]:
            assert receive_event(websocket) == {"type": "connected", "patient_id": patient_id}
        response = post_reading(client, 42)
        assert response.status_code == 201
        message = {"type": "reading", "data": response.json()}
        assert receive_event(first) == message
        assert receive_event(second) == message
        with pytest.raises(TimeoutError):
            receive_event(other, timeout=0.05)
        with database.SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(Reading)) == 1
        response = post_reading(client, 43)
        assert receive_event(other) == {"type": "reading", "data": response.json()}
        for websocket in [first, second]:
            with pytest.raises(TimeoutError):
                receive_event(websocket, timeout=0.05)


@pytest.mark.parametrize("payload,status", [
    ({"patient_id": 999, "heart_rate": 78, "spo2": 98, "temperature_c": 36.8}, 404),
    ({"patient_id": 42, "heart_rate": -1, "spo2": 98, "temperature_c": 36.8}, 422),
])
def test_rejected_reading_never_broadcasts(client, monkeypatch, payload, status):
    broadcast = AsyncMock()
    monkeypatch.setattr(manager, "broadcast", broadcast)
    assert client.post("/api/readings", json=payload).status_code == status
    broadcast.assert_not_awaited()


def test_broadcast_exception_cannot_undo_commit(client, monkeypatch):
    monkeypatch.setattr(manager, "broadcast", AsyncMock(side_effect=RuntimeError("failed live transport")))
    response = post_reading(client)
    assert response.status_code == 201
    with database.SessionLocal() as db:
        assert db.get(Reading, response.json()["id"]) is not None
        assert db.scalar(select(func.count()).select_from(Reading)) == 1


def test_handshake_database_session_closes_before_stream_waits(client, monkeypatch):
    login(client)
    session = database.SessionLocal()
    close = Mock(wraps=session.close)
    monkeypatch.setattr(session, "close", close)
    monkeypatch.setattr(database, "SessionLocal", lambda: session)
    with client.websocket_connect("/ws/patients/42") as websocket:
        assert receive_event(websocket)["type"] == "connected"
        close.assert_called_once()
        assert not session.in_transaction()


class FakeSocket:
    def __init__(self, error=None):
        self.accept = AsyncMock()
        self.send_json = AsyncMock(side_effect=error)
        self.close = AsyncMock()


def test_manager_connect_disconnect_and_channels():
    async def check():
        manager = ConnectionManager()
        first, second, other = FakeSocket(), FakeSocket(), FakeSocket()
        await manager.connect(42, first)
        await manager.connect(42, second)
        await manager.connect(43, other)
        first.accept.assert_awaited_once()
        message = {"type": "reading", "data": {"patient_id": 42}}
        await manager.broadcast(42, message)
        first.send_json.assert_awaited_once_with(message)
        second.send_json.assert_awaited_once_with(message)
        other.send_json.assert_not_awaited()
        manager.disconnect(42, first)
        manager.disconnect(42, first)  # Idempotent cleanup.
        assert manager.connections[42] == {second}
        manager.disconnect(42, second)
        assert 42 not in manager.connections
        assert manager.connections[43] == {other}
    asyncio.run(check())


@pytest.mark.parametrize("error", [WebSocketDisconnect(), OSError(), RuntimeError()])
def test_manager_dead_viewer_does_not_break_remaining_viewers(error):
    async def check():
        manager = ConnectionManager()
        dead, healthy = FakeSocket(error), FakeSocket()
        await manager.connect(42, dead)
        await manager.connect(42, healthy)
        await manager.broadcast(42, {"type": "reading"})
        assert manager.connections[42] == {healthy}
        healthy.send_json.assert_awaited_once()
        dead.close.assert_awaited_once_with(code=1011)
    asyncio.run(check())


def test_dead_viewer_keeps_rest_success_and_other_delivery(client):
    login(client)
    dead = FakeSocket(OSError())
    with client.websocket_connect("/ws/patients/42") as websocket:
        receive_event(websocket)
        websocket.portal.call(manager.connect, 42, dead)
        response = post_reading(client)
        assert response.status_code == 201
        assert receive_event(websocket) == {"type": "reading", "data": response.json()}
        assert dead not in manager.connections[42]
        with database.SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(Reading)) == 1
