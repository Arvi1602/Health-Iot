"""Small database queries for the monitoring dashboard."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Alert, Patient, Reading
from app.schemas import ReadingResponse

RECENT_READING_LIMIT = 20


def reading_history(db: Session, patient_id: int, limit: int = RECENT_READING_LIMIT) -> list[ReadingResponse]:
    rows = db.scalars(select(Reading).where(Reading.patient_id == patient_id)
                      .order_by(Reading.recorded_at.desc(), Reading.id.desc())
                      .limit(limit)).all()
    return [ReadingResponse.model_validate(row) for row in rows]


def recent_readings(db: Session, patient_id: int) -> list[ReadingResponse]:
    return list(reversed(reading_history(db, patient_id)))


def owns_patient(db: Session, doctor_id: int, patient_id: int) -> bool:
    if not 0 < patient_id <= 9223372036854775807:
        return False
    patient = db.get(Patient, patient_id)
    return patient is not None and patient.doctor_id == doctor_id


def latest_reading(db: Session, patient_id: int) -> ReadingResponse | None:
    reading = db.scalar(select(Reading).where(Reading.patient_id == patient_id)
                        .order_by(Reading.recorded_at.desc(), Reading.id.desc()).limit(1))
    return ReadingResponse.model_validate(reading) if reading else None


def assigned_patients(db: Session, doctor_id: int) -> list[dict]:
    # One query: each patient joins only their newest reading; counts come from stored alerts.
    latest_id = (select(Reading.id).where(Reading.patient_id == Patient.id)
                 .order_by(Reading.recorded_at.desc(), Reading.id.desc()).limit(1)
                 .correlate(Patient).scalar_subquery())
    alert_count = (select(func.count(Alert.id)).where(Alert.patient_id == Patient.id)
                   .correlate(Patient).scalar_subquery())
    rows = db.execute(select(Patient, Reading, alert_count)
                      .outerjoin(Reading, Reading.id == latest_id)
                      .where(Patient.doctor_id == doctor_id).order_by(Patient.id)).all()
    return [{"id": patient.id, "name": patient.name, "age": patient.age,
             "gender": patient.gender, "alert_count": min(count, 10),
             "reading": ReadingResponse.model_validate(reading).model_dump(mode="json") if reading else None}
            for patient, reading, count in rows]
