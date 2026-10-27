"""Dashboard snapshots and refreshes enforce the same doctor ownership."""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import database
from app.auth import hash_password
from app.main import app
from app.models import Doctor, Patient, Reading


@pytest.fixture
def client(isolated_database):
    with database.SessionLocal() as db:
        doctor = Doctor(name="Dr. Dashboard", email="dashboard@example.com", password_hash=hash_password("test-password"))
        other = Doctor(name="Other", email="other@example.com", password_hash="unused")
        db.add_all([doctor, other])
        db.flush()
        db.add_all([Patient(id=41, name="Assigned Patient", age=45, gender="Male", doctor_id=doctor.id),
                    Patient(id=42, name="No Readings", age=32, gender="Female", doctor_id=doctor.id),
                    Patient(id=99, name="Private Other Patient", age=61, gender="Male", doctor_id=other.id)])
        db.commit()
    with TestClient(app, follow_redirects=False) as client:
        yield client


def login(client):
    assert client.post("/login", data={"email": "dashboard@example.com", "password": "test-password"}).status_code == 303


def test_dashboard_and_refresh_require_login(client):
    for url in ["/dashboard", "/api/patients/41/latest-reading"]:
        response = client.get(url)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"


def test_only_assigned_patients_and_empty_state(client):
    login(client)
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "Assigned Patient" in response.text and "No Readings" in response.text
    assert "Private Other Patient" not in response.text
    assert "No readings available for this patient yet." in response.text
    assert "No readings received yet" in response.text
    assert client.get("/api/patients/42/latest-reading").json() is None
    assert client.get("/static/js/dashboard.js").status_code == 200


@pytest.mark.parametrize("patient_id", [99, 999, 0, -1, 9223372036854775808])
def test_refresh_rejects_unowned_or_missing_patient(client, patient_id):
    login(client)
    assert client.get(f"/api/patients/{patient_id}/latest-reading").status_code == 404


def test_latest_timestamp_and_id_tiebreaker(client):
    with database.SessionLocal() as db:
        for identifier, timestamp, heart_rate in [(1, datetime(2026, 10, 6), 70), (2, datetime(2026, 10, 6), 83), (3, datetime(2025, 1, 1), 65)]:
            db.add(Reading(id=identifier, patient_id=41, heart_rate=heart_rate, spo2=97.5,
                           temperature_c=36.9, recorded_at=timestamp))
        db.commit()
    login(client)
    response = client.get("/dashboard")
    assert response.context["patients"][0]["reading"]["id"] == 2
    for value in ['id="heart-rate" class="vital-value">83', 'id="spo2" class="vital-value">97.5', 'id="temperature" class="vital-value">36.9']:
        assert value in response.text
    latest = client.get("/api/patients/41/latest-reading")
    assert latest.json() == response.context["patients"][0]["reading"]
    assert latest.json()["recorded_at"] == "2026-10-06T00:00:00Z"
    assert latest.headers["cache-control"] == "no-store"


def test_no_assigned_patients(client):
    with database.SessionLocal() as db:
        doctor = db.scalar(select(Doctor).where(Doctor.email == "dashboard@example.com"))
        for patient in doctor.patients:
            db.delete(patient)
        db.commit()
    login(client)
    assert "No patients assigned to your account." in client.get("/dashboard").text


def test_recent_requires_login(client):
    response = client.get("/api/patients/41/readings/recent")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


@pytest.mark.parametrize("patient_id", [99, 999, 0, -1, 9223372036854775808])
def test_recent_ownership(client, patient_id):
    login(client)
    assert client.get(f"/api/patients/{patient_id}/readings/recent").status_code == 404


def test_recent_empty(client):
    login(client)
    response = client.get("/api/patients/41/readings/recent")
    assert response.json() == []
    assert response.headers["cache-control"] == "no-store"


def test_recent_limit_order_and_patient_isolation(client):
    from datetime import timedelta
    with database.SessionLocal() as db:
        # Insert reverse chronology, including ties, to exercise both sort keys.
        for index in range(25):
            db.add(Reading(id=index + 1, patient_id=41, heart_rate=70 + index,
                           spo2=98, temperature_c=36.8,
                           recorded_at=datetime(2026, 10, 6) + timedelta(seconds=(24-index)//2)))
        db.add(Reading(id=99, patient_id=42, heart_rate=80, spo2=98, temperature_c=37))
        db.commit()
    login(client)
    response = client.get("/api/patients/41/readings/recent?limit=1000")
    assert response.status_code == 200
    readings = response.json()
    assert len(readings) == 20
    assert all(row["patient_id"] == 41 for row in readings)
    assert [(r["recorded_at"], r["id"]) for r in readings] == sorted((r["recorded_at"], r["id"]) for r in readings)
    assert readings[-1]["id"] == 1
    assert readings[0]["id"] == 21  # Same timestamp as ID 20; larger ID is newer.
    assert readings[-1] == client.get("/api/patients/41/latest-reading").json()
