"""Read-only academic fuzzy assessment of the latest owned persisted reading."""
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app import config
from app.auth import require_doctor
from app.dashboard_data import latest_reading, owns_patient
from app.database import get_db
from app.fuzzy_logic import evaluate_fuzzy_vitals
from app.models import Doctor
from app.schemas import FuzzyResponse

router = APIRouter()


@router.get('/api/patients/{patient_id}/fuzzy-assessment', response_model=FuzzyResponse)
def patient_fuzzy_assessment(patient_id: int, response: Response,
                             doctor: Doctor = Depends(require_doctor), db: Session = Depends(get_db)):
    if not owns_patient(db, doctor.id, patient_id):
        raise HTTPException(404, 'Patient not found')
    response.headers['Cache-Control'] = 'no-store'
    reading = latest_reading(db, patient_id)
    if reading is None:
        return FuzzyResponse(patient_id=patient_id)
    result = evaluate_fuzzy_vitals(reading.heart_rate, reading.spo2, reading.temperature_c, config.FUZZY_SETTINGS)
    return FuzzyResponse(patient_id=patient_id, reading_id=reading.id, recorded_at=reading.recorded_at,
                         assessment=dict(risk_score=result.risk_score, status=result.status,
                                         input_memberships={k: dict(v) for k, v in result.input_memberships.items()},
                                         output_memberships=dict(result.output_memberships)))
