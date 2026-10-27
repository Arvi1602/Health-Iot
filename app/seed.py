"""Development demo data. Run from the project root with python -m app.seed."""

from sqlalchemy import select

from app import database
from app.auth import hash_password
from app.models import Doctor, Patient

DEMO_DOCTOR_EMAIL = "doctor@healthguard.local"
# Public local-development credential only; never used as a session secret.
DEMO_PASSWORD = "HealthGuard123!"
DEMO_PATIENTS = (
    ("Rahul Kumar", 45, "Male"),
    ("Priya Singh", 32, "Female"),
    ("Arjun Patel", 61, "Male"),
    ("Meera Joshi", 54, "Female"),
)


def seed_demo_data() -> None:
    database.init_db()
    doctors_created = 0
    patients_created = 0
    password_upgraded = False

    with database.SessionLocal() as db:
        try:
            doctor = db.scalar(select(Doctor).where(Doctor.email == DEMO_DOCTOR_EMAIL))
            if doctor is None:
                doctor = Doctor(
                    name="Dr. Ananya Sharma",
                    email=DEMO_DOCTOR_EMAIL,
                    password_hash=hash_password(DEMO_PASSWORD),
                )
                db.add(doctor)
                db.flush()
                doctors_created = 1
            elif doctor.password_hash == "demo-password-hash":
                # Only upgrade the known TASK-003 placeholder for this demo email.
                doctor.password_hash = hash_password(DEMO_PASSWORD)
                password_upgraded = True

            for name, age, gender in DEMO_PATIENTS:
                patient = db.scalar(select(Patient).where(
                    Patient.doctor_id == doctor.id,
                    Patient.name == name,
                ))
                if patient is None:
                    db.add(Patient(name=name, age=age, gender=gender, doctor_id=doctor.id))
                    patients_created += 1

            db.commit()
        except Exception:
            db.rollback()
            raise

    print("HealthGuard demo data seed completed.")
    print(f"Created {doctors_created} doctor(s) and {patients_created} patient(s).")
    if password_upgraded:
        print("Upgraded the demo account's legacy password placeholder.")
    print(f"\nDoctor:\n- {DEMO_DOCTOR_EMAIL}\n\nPatients:")
    for name, _, _ in DEMO_PATIENTS:
        print(f"- {name}")


if __name__ == "__main__":
    seed_demo_data()
