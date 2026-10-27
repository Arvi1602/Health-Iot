"""Authenticated, patient-specific live reading transport."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from app import database
from app.auth import get_current_doctor
from app.models import Patient
from app.websocket_manager import manager

router = APIRouter()


def can_monitor(websocket: WebSocket, patient_id: int) -> bool:
    # Close this session before waiting on the long-lived WebSocket connection.
    with database.SessionLocal() as db:
        doctor = get_current_doctor(websocket, db)
        if doctor is None or not 0 < patient_id <= 9223372036854775807:
            return False
        patient = db.get(Patient, patient_id)
        return patient is not None and patient.doctor_id == doctor.id


@router.websocket("/ws/patients/{patient_id}")
async def patient_stream(websocket: WebSocket, patient_id: int):
    # Browsers must originate from this app; non-browser test clients may omit Origin.
    origin = websocket.headers.get("origin")
    scheme = "https" if websocket.url.scheme == "wss" else "http"
    if origin and origin != f"{scheme}://{websocket.headers.get('host')}":
        await websocket.close(code=1008)
        return
    if not await run_in_threadpool(can_monitor, websocket, patient_id):
        await websocket.close(code=1008)
        return
    try:
        await manager.connect(patient_id, websocket)
        await websocket.send_json({"type": "connected", "patient_id": patient_id})
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
    except (WebSocketDisconnect, OSError, RuntimeError):
        pass  # Normal disconnect/send-on-closed-socket races.
    finally:
        manager.disconnect(patient_id, websocket)
