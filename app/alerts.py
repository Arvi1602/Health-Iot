"""Authenticated retrieval of stored academic demo alerts; no re-evaluation."""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_doctor
from app.dashboard_data import owns_patient
from app.database import get_db
from app.models import Alert, Doctor
from app.schemas import AlertResponse

router = APIRouter()


@router.get('/api/patients/{patient_id}/alerts', response_model=list[AlertResponse])
def patient_alerts(patient_id: int, response: Response,
                   doctor: Doctor = Depends(require_doctor), db: Session = Depends(get_db)):
    if not owns_patient(db, doctor.id, patient_id):
        raise HTTPException(404, 'Patient not found')
    response.headers['Cache-Control'] = 'no-store'
    return db.scalars(select(Alert).where(Alert.patient_id == patient_id)
                      .order_by(Alert.created_at.desc(), Alert.id.desc()).limit(50)).all()
