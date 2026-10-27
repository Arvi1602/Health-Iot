from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app import database
from app.main import app
from app.models import Alert, Doctor, Patient, Reading
from app.websocket_manager import manager


@pytest.fixture
def patient_id(isolated_database):
    with database.SessionLocal() as db:
        doctor = Doctor(name="Test Doctor", email="sensor-test@example.com", password_hash="test-hash")
        # A non-default ID catches accidentally hard-coded patient selection.
        patient = Patient(id=42, name="Test Patient", age=45, gender="Male", doctor=doctor)
        db.add(patient)
        db.commit()
        return patient.id


@pytest.fixture
def client(patient_id):
    with TestClient(app) as client:
        yield client


@pytest.fixture
def payload(patient_id):
    return {"patient_id": patient_id, "heart_rate": 78, "spo2": 98, "temperature_c": 36.8}


def assert_no_readings():
    with database.SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Reading)) == 0


def test_create_reading_without_login(client, payload):
    before = datetime.now(timezone.utc) - timedelta(seconds=1)
    response = client.post("/api/readings", json=payload)
    assert response.status_code == 201
    result = response.json()
    assert set(result) == {"id", "patient_id", "heart_rate", "spo2", "temperature_c", "recorded_at"}
    assert {key: result[key] for key in payload} == payload
    timestamp = datetime.fromisoformat(result["recorded_at"].replace("Z", "+00:00"))
    assert before <= timestamp <= datetime.now(timezone.utc)
    with database.SessionLocal() as db:
        reading = db.get(Reading, result["id"])
        assert reading.patient_id == payload["patient_id"]
        assert reading.patient.name == "Test Patient"
        assert (reading.heart_rate, reading.spo2, reading.temperature_c) == (78, 98, 36.8)
        assert reading.recorded_at == timestamp.replace(tzinfo=None)
        assert db.scalar(select(func.count()).select_from(Reading)) == 1
        assert db.scalar(select(func.count()).select_from(Alert)) == 0


def test_unknown_patient(client, payload):
    payload["patient_id"] = 999
    response = client.post("/api/readings", json=payload)
    assert response.status_code == 404
    assert response.json() == {"detail": "Patient not found"}
    assert_no_readings()


def test_multiple_readings_and_chronological_query(client, payload):
    # Insert out of chronological order so ordering cannot rely on row IDs.
    samples = [
        (78, 98, 36.8, "2026-10-06T03:02:00Z"),
        (82, 97, 37.0, "2026-10-06T03:00:00Z"),
        (76, 99, 36.7, "2026-10-06T03:01:00Z"),
    ]
    ids = []
    for heart_rate, spo2, temperature_c, recorded_at in samples:
        response = client.post("/api/readings", json={
            **payload, "heart_rate": heart_rate, "spo2": spo2,
            "temperature_c": temperature_c, "recorded_at": recorded_at,
        })
        assert response.status_code == 201
        ids.append(response.json()["id"])
        with database.SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(Reading)) == len(ids)

    assert len(set(ids)) == 3
    with database.SessionLocal() as db:
        readings = db.scalars(select(Reading).where(
            Reading.patient_id == payload["patient_id"]
        ).order_by(Reading.recorded_at)).all()
        assert [reading.id for reading in readings] == [ids[1], ids[2], ids[0]]
        assert [(r.heart_rate, r.spo2, r.temperature_c, r.recorded_at) for r in readings] == [
            (82, 97, 37.0, datetime(2026, 10, 6, 3, 0)),
            (76, 99, 36.7, datetime(2026, 10, 6, 3, 1)),
            (78, 98, 36.8, datetime(2026, 10, 6, 3, 2)),
        ]
        patient = db.get(Patient, payload["patient_id"])
        assert {reading.id for reading in patient.readings} == set(ids)
        assert all(reading.patient == patient for reading in readings)


def test_rejected_requests_preserve_existing_reading(client, payload):
    response = client.post("/api/readings", json=payload)
    assert response.status_code == 201
    original = response.json()
    for field, value, expected_status in [
        ("heart_rate", -1, 422), ("heart_rate", 500, 422),
        ("spo2", -1, 422), ("spo2", 101, 422),
        ("temperature_c", 10, 422), ("temperature_c", 60, 422),
        ("patient_id", 999, 404),
    ]:
        response = client.post("/api/readings", json={**payload, field: value})
        assert response.status_code == expected_status
        with database.SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(Reading)) == 1
            reading = db.get(Reading, original["id"])
            assert reading.patient_id == payload["patient_id"]
            assert (reading.heart_rate, reading.spo2, reading.temperature_c) == (78, 98, 36.8)
            assert reading.recorded_at == datetime.fromisoformat(
                original["recorded_at"].replace("Z", "+00:00")
            ).replace(tzinfo=None)


@pytest.mark.parametrize("field,value", [
    ("patient_id", 0), ("patient_id", -1), ("patient_id", "abc"),
    ("patient_id", True), ("patient_id", 2**63),
    ("heart_rate", -1), ("heart_rate", 0), ("heart_rate", 500),
    ("heart_rate", 78.5), ("heart_rate", "fast"), ("heart_rate", "78"), ("heart_rate", True),
    ("spo2", -1), ("spo2", 101), ("spo2", "good"), ("spo2", "NaN"), ("spo2", True),
    ("temperature_c", 10), ("temperature_c", 60), ("temperature_c", "warm"),
    ("temperature_c", "Infinity"), ("temperature_c", True),
    ("recorded_at", "not-a-date"), ("recorded_at", 1234567890),
    ("recorded_at", "1234567890"),
    ("recorded_at", "2026-02-30T03:00:00Z"),
])
def test_invalid_values_are_not_saved(client, payload, field, value):
    payload[field] = value
    response = client.post("/api/readings", json=payload)
    assert response.status_code == 422
    assert_no_readings()


@pytest.mark.parametrize("field", ["patient_id", "heart_rate", "spo2", "temperature_c"])
@pytest.mark.parametrize("missing", [True, False])
def test_required_fields(client, payload, field, missing):
    if missing:
        del payload[field]
    else:
        payload[field] = None
    assert client.post("/api/readings", json=payload).status_code == 422
    assert_no_readings()


@pytest.mark.parametrize("values", [(1, 0, 20), (300, 100, 50)])
def test_input_bounds_are_inclusive(client, payload, values):
    payload.update(zip(("heart_rate", "spo2", "temperature_c"), values))
    assert client.post("/api/readings", json=payload).status_code == 201


@pytest.mark.parametrize("supplied", [
    "2026-10-06T03:00:00Z", "2026-10-06T08:30:00+05:30", "2026-10-06T03:00:00",
])
def test_supplied_timestamp_preserves_instant(client, payload, supplied):
    payload["recorded_at"] = supplied
    response = client.post("/api/readings", json=payload)
    assert response.status_code == 201
    assert response.json()["recorded_at"] == "2026-10-06T03:00:00Z"
    with database.SessionLocal() as db:
        reading = db.get(Reading, response.json()["id"])
        assert reading.recorded_at == datetime(2026, 10, 6, 3)


def test_null_timestamp_uses_default(client, payload):
    payload["recorded_at"] = None
    response = client.post("/api/readings", json=payload)
    assert response.status_code == 201
    assert response.json()["recorded_at"].endswith("Z")


def test_malformed_json(client):
    assert client.post("/api/readings", content="{", headers={"Content-Type": "application/json"}).status_code == 422
    assert_no_readings()


def test_unrecognized_fields_are_rejected(client, payload):
    payload["timestamp"] = "2026-10-06T03:00:00Z"
    assert client.post("/api/readings", json=payload).status_code == 422
    assert_no_readings()


@pytest.mark.parametrize("failure_stage", [None, "get", "flush", "refresh", "commit"])
def test_transaction_cleanup(client, payload, monkeypatch, failure_stage):
    broadcast = AsyncMock()
    monkeypatch.setattr(manager, "broadcast", broadcast)
    factory = database.SessionLocal
    session = factory()
    rollback = Mock(wraps=session.rollback)
    close = Mock(wraps=session.close)
    monkeypatch.setattr(session, "rollback", rollback)
    monkeypatch.setattr(session, "close", close)
    monkeypatch.setattr(database, "SessionLocal", lambda: session)
    if failure_stage:
        monkeypatch.setattr(session, failure_stage, Mock(side_effect=SQLAlchemyError("private database details")))
    response = client.post("/api/readings", json=payload)
    close.assert_called_once()
    if failure_stage:
        assert response.status_code == 500
        assert response.json() == {"detail": "Unable to save reading"}
        rollback.assert_called_once()
        assert not session.in_transaction()
        broadcast.assert_not_awaited()
    else:
        assert response.status_code == 201
        rollback.assert_not_called()
        broadcast.assert_awaited_once_with(payload["patient_id"], {"type": "reading", "data": response.json()})
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Reading)) == (0 if failure_stage else 1)
