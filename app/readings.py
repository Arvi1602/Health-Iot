"""Local device ingestion and persistence; no browser-session authentication."""

import logging

from anyio import from_thread
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.alert_rules import evaluate_reading
from app.models import Alert, Patient, Reading
from app.schemas import ReadingCreate, ReadingResponse
from app.websocket_manager import manager

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/api/readings", status_code=201, response_model=ReadingResponse)
def create_reading(payload: ReadingCreate, db: Session = Depends(get_db)):
    try:
        if db.get(Patient, payload.patient_id) is None:
            raise HTTPException(status_code=404, detail="Patient not found")
        reading = Reading(**payload.model_dump(exclude_none=True))
        db.add(reading)
        # Read back defaults before committing so a refresh failure can roll back
        # the insertion too. No second transaction is needed to build the response.
        db.flush()
        db.refresh(reading)
        response = ReadingResponse.model_validate(reading)
        for candidate in evaluate_reading(reading):
            db.add(Alert(patient_id=reading.patient_id, reading_id=reading.id,
                         alert_type=candidate.alert_type, message=candidate.message,
                         severity=candidate.severity))
        # One commit includes both the reading and every generated demo alert.
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=500, detail="Unable to save reading") from None
    # FastAPI runs this sync route in an AnyIO worker. Send on the owning event
    # loop only after commit, using the same serialized values as the REST result.
    try:
        from_thread.run(manager.broadcast, response.patient_id,
                        {"type": "reading", "data": response.model_dump(mode="json")})
    except Exception:
        logger.warning("Live delivery failed; reading remains committed.")
    return response
