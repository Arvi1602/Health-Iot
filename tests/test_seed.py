from unittest.mock import Mock

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app import database
from app.auth import verify_password
from app.models import Alert, Doctor, Patient, Reading
from app.seed import DEMO_DOCTOR_EMAIL, DEMO_PASSWORD, seed_demo_data


@pytest.fixture
def seed_database(tmp_path, monkeypatch):
    engine = database.create_sqlite_engine(f"sqlite:///{tmp_path / 'seed.db'}")
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=engine))
    # The seed function must initialize this empty database itself.
    yield engine
    engine.dispose()


def test_seed_creates_demo_records(seed_database, capsys):
    seed_demo_data()
    with database.SessionLocal() as db:
        doctors = db.scalars(select(Doctor)).all()
        assert len(doctors) == 1
        doctor = doctors[0]
        assert doctor.email == "doctor@healthguard.local"
        assert doctor.name == "Dr. Ananya Sharma"
        assert doctor.password_hash != DEMO_PASSWORD
        assert doctor.password_hash.startswith("$argon2id$")
        assert verify_password(DEMO_PASSWORD, doctor.password_hash)
        assert not verify_password("incorrect-password", doctor.password_hash)
        patients = db.scalars(select(Patient)).all()
        assert len(patients) == 4
        assert {(p.name, p.age, p.gender) for p in patients} == {
            ("Rahul Kumar", 45, "Male"),
            ("Priya Singh", 32, "Female"),
            ("Arjun Patel", 61, "Male"),
            ("Meera Joshi", 54, "Female"),
        }
        assert all(p.doctor_id == doctor.id and p.doctor == doctor for p in patients)
        assert db.scalar(select(func.count()).select_from(Reading)) == 0
        assert db.scalar(select(func.count()).select_from(Alert)) == 0
    output = capsys.readouterr().out
    assert "Created 1 doctor(s) and 4 patient(s)." in output
    assert "demo-password-hash" not in output
    assert DEMO_PASSWORD not in output


def test_seed_twice_keeps_same_records(seed_database, capsys):
    seed_demo_data()
    with database.SessionLocal() as db:
        doctor_ids = db.scalars(select(Doctor.id)).all()
        original_hash = db.scalar(select(Doctor.password_hash))
        patient_ids = db.scalars(select(Patient.id).order_by(Patient.id)).all()
    seed_demo_data()
    with database.SessionLocal() as db:
        assert db.scalars(select(Doctor.id)).all() == doctor_ids
        assert db.scalars(select(Patient.id).order_by(Patient.id)).all() == patient_ids
        assert len(doctor_ids) == 1
        assert len(patient_ids) == 4
        assert db.scalar(select(Doctor.password_hash)) == original_hash
    assert "Created 0 doctor(s) and 0 patient(s)." in capsys.readouterr().out


def test_seed_preserves_existing_data_and_adds_missing_patients(seed_database):
    database.init_db()
    with database.SessionLocal() as db:
        doctor = Doctor(name="Existing Name", email=DEMO_DOCTOR_EMAIL,
                        password_hash="existing-test-hash")
        patient = Patient(name="Rahul Kumar", age=46, gender="Male", doctor=doctor)
        other_doctor = Doctor(name="Other Doctor", email="other@example.com",
                              password_hash="other-test-hash")
        other_patient = Patient(name="Priya Singh", age=33, gender="Female", doctor=other_doctor)
        reading = Reading(patient=other_patient, heart_rate=78, spo2=98, temperature_c=36.8)
        alert = Alert(patient=other_patient, reading=reading, alert_type="demo",
                      message="Existing demo record", severity="low")
        db.add_all([doctor, patient, other_doctor, other_patient, reading, alert])
        db.commit()
        ids = doctor.id, patient.id, other_doctor.id, other_patient.id, reading.id, alert.id

    seed_demo_data()
    with database.SessionLocal() as db:
        doctor = db.get(Doctor, ids[0])
        assert doctor.name == "Existing Name"
        assert doctor.password_hash == "existing-test-hash"
        assert len(doctor.patients) == 4
        assert db.get(Patient, ids[1]).age == 46
        assert db.get(Doctor, ids[2]).name == "Other Doctor"
        assert db.get(Patient, ids[3]).doctor_id == ids[2]
        assert db.get(Patient, ids[3]).age == 33
        assert db.get(Reading, ids[4]).heart_rate == 78
        assert db.get(Alert, ids[5]).message == "Existing demo record"
        assert db.scalar(select(func.count()).select_from(Doctor)) == 2
        assert db.scalar(select(func.count()).select_from(Patient)) == 5


def test_seed_upgrades_only_demo_placeholder(seed_database):
    database.init_db()
    with database.SessionLocal() as db:
        db.add_all([
            Doctor(name="Dr. Ananya Sharma", email=DEMO_DOCTOR_EMAIL,
                   password_hash="demo-password-hash"),
            Doctor(name="Other Doctor", email="other@example.com",
                   password_hash="demo-password-hash"),
        ])
        db.commit()
    seed_demo_data()
    with database.SessionLocal() as db:
        doctor = db.scalar(select(Doctor).where(Doctor.email == DEMO_DOCTOR_EMAIL))
        upgraded_hash = doctor.password_hash
        assert verify_password(DEMO_PASSWORD, upgraded_hash)
        other = db.scalar(select(Doctor).where(Doctor.email == "other@example.com"))
        assert other.password_hash == "demo-password-hash"
    seed_demo_data()
    with database.SessionLocal() as db:
        doctor = db.scalar(select(Doctor).where(Doctor.email == DEMO_DOCTOR_EMAIL))
        assert doctor.password_hash == upgraded_hash
        assert len(doctor.patients) == 4


def test_seed_preserves_existing_real_password(seed_database):
    seed_demo_data()
    from app.auth import hash_password

    changed_hash = hash_password("different-local-test-password")
    with database.SessionLocal() as db:
        doctor = db.scalar(select(Doctor).where(Doctor.email == DEMO_DOCTOR_EMAIL))
        doctor.password_hash = changed_hash
        db.commit()
    seed_demo_data()
    with database.SessionLocal() as db:
        doctor = db.scalar(select(Doctor).where(Doctor.email == DEMO_DOCTOR_EMAIL))
        assert doctor.password_hash == changed_hash


@pytest.mark.parametrize("fail", [False, True])
def test_seed_session_cleanup_and_rollback(seed_database, monkeypatch, capsys, fail):
    factory = database.SessionLocal
    db = factory()
    close = Mock(wraps=db.close)
    rollback = Mock(wraps=db.rollback)
    monkeypatch.setattr(db, "close", close)
    monkeypatch.setattr(db, "rollback", rollback)
    monkeypatch.setattr(database, "SessionLocal", lambda: db)
    if fail:
        def fail_commit():
            db.flush()
            raise RuntimeError("Simulated commit failure")

        monkeypatch.setattr(db, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="Simulated commit failure"):
            seed_demo_data()
        rollback.assert_called_once()
        assert "seed completed" not in capsys.readouterr().out
    else:
        seed_demo_data()
        rollback.assert_not_called()
    close.assert_called_once()
    with factory() as check:
        assert check.scalar(select(func.count()).select_from(Doctor)) == (0 if fail else 1)
        assert check.scalar(select(func.count()).select_from(Patient)) == (0 if fail else 4)
