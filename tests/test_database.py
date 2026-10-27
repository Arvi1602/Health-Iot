from unittest.mock import Mock

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app import database
from app.models import Alert, Doctor, Patient, Reading


@pytest.fixture
def db_engine(tmp_path, monkeypatch):
    engine = database.create_sqlite_engine(f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=engine))
    database.init_db()
    yield engine
    engine.dispose()


def test_tables_created(db_engine):
    database.init_db()  # Initialization is safe to repeat.
    assert set(inspect(db_engine).get_table_names()) == {
        "doctors", "patients", "readings", "alerts"
    }


def test_records_and_relationships(db_engine):
    with database.SessionLocal() as db:
        doctor = Doctor(name="Dr. Sharma", email="doctor@example.com", password_hash="test-hash")
        patient = Patient(name="Rahul Kumar", age=45, gender="Male", doctor=doctor)
        reading = Reading(patient=patient, heart_rate=78, spo2=98, temperature_c=36.8)
        alert = Alert(patient=patient, reading=reading, alert_type="heart_rate",
                      message="Demo alert", severity="high")
        unlinked_alert = Alert(patient=patient, alert_type="heart_rate",
                               message="Demo alert without reading", severity="low")
        db.add_all([doctor, patient, reading, alert, unlinked_alert])
        db.commit()

    # Reload in a fresh session to verify persisted relationships and defaults.
    with database.SessionLocal() as db:
        doctor = db.scalar(select(Doctor))
        patient = db.scalar(select(Patient))
        reading = db.scalar(select(Reading))
        alerts = db.scalars(select(Alert).order_by(Alert.id)).all()
        assert doctor.name == "Dr. Sharma"
        assert doctor.password_hash == "test-hash"
        assert doctor.patients == [patient]
        assert patient.doctor == doctor
        assert patient.readings == [reading]
        assert reading.patient == patient
        assert (reading.heart_rate, reading.spo2, reading.temperature_c) == (78, 98, 36.8)
        assert set(patient.alerts) == set(alerts)
        assert alerts[0].reading == reading
        assert reading.alerts == [alerts[0]]
        assert alerts[1].reading is None
        assert all(alert.patient == patient and alert.is_resolved is False for alert in alerts)
        assert all(record.created_at is not None for record in [doctor, patient, *alerts])
        assert reading.recorded_at is not None


def test_duplicate_doctor_email_rejected(db_engine):
    with database.SessionLocal() as db:
        db.add_all([
            Doctor(name="Doctor One", email="same@example.com", password_hash="test-hash"),
            Doctor(name="Doctor Two", email="same@example.com", password_hash="test-hash"),
        ])
        with pytest.raises(IntegrityError, match="UNIQUE constraint failed"):
            db.commit()
        db.rollback()


@pytest.mark.parametrize("model, fields", [
    (Patient, dict(name="Test Patient", age=45, gender="Male", doctor_id=999)),
    (Reading, dict(patient_id=999, heart_rate=78, spo2=98, temperature_c=36.8)),
    (Alert, dict(patient_id=999, alert_type="heart_rate", message="Demo", severity="high")),
])
def test_invalid_foreign_keys_rejected(db_engine, model, fields):
    with database.SessionLocal() as db:
        db.add(model(**fields))
        with pytest.raises(IntegrityError, match="FOREIGN KEY constraint failed"):
            db.commit()
        db.rollback()


def test_invalid_alert_reading_rejected(db_engine):
    with database.SessionLocal() as db:
        doctor = Doctor(name="Doctor", email="doctor@example.com", password_hash="test-hash")
        patient = Patient(name="Patient", age=45, gender="Male", doctor=doctor)
        db.add(patient)
        db.commit()
        db.add(Alert(patient_id=patient.id, reading_id=999, alert_type="heart_rate",
                     message="Demo", severity="high"))
        with pytest.raises(IntegrityError, match="FOREIGN KEY constraint failed"):
            db.commit()
        db.rollback()


def test_patient_requires_doctor(db_engine):
    with database.SessionLocal() as db:
        db.add(Patient(name="Patient", age=45, gender="Male"))
        with pytest.raises(IntegrityError, match="NOT NULL constraint failed"):
            db.commit()
        db.rollback()


@pytest.mark.parametrize("fail", [False, True])
def test_session_dependency_closes_session(db_engine, monkeypatch, fail):
    db = database.SessionLocal()
    close = Mock(wraps=db.close)
    monkeypatch.setattr(db, "close", close)
    monkeypatch.setattr(database, "SessionLocal", lambda: db)
    dependency = database.get_db()
    assert next(dependency) is db
    assert db.scalar(select(Doctor.id)) is None
    if fail:
        with pytest.raises(RuntimeError, match="endpoint failed"):
            dependency.throw(RuntimeError("endpoint failed"))
    else:
        with pytest.raises(StopIteration):
            next(dependency)
    close.assert_called_once()
