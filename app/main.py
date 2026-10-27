"""HealthGuard IoT backend entry point."""

from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request, Response, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app.auth import DUMMY_PASSWORD_HASH, get_current_doctor, require_doctor, verify_password
from app.config import APP_ENV, APP_NAME, SECRET_KEY, validate_session_secret
from app.database import get_db
from app.models import Doctor
from app.dashboard_data import assigned_patients, latest_reading, owns_patient, recent_readings, reading_history
from app.schemas import ReadingResponse
from app.alerts import router as alerts_router
from app.readings import router as readings_router
from app.websockets import router as websocket_router
from app.fuzzy_api import router as fuzzy_router

validate_session_secret()
app = FastAPI(title=f"{APP_NAME} API")
app.include_router(readings_router)
app.include_router(alerts_router)
app.include_router(websocket_router)
app.include_router(fuzzy_router)
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie="healthguard_session",
    max_age=8 * 60 * 60,
    same_site="strict",
    https_only=APP_ENV == "production",
)
APP_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=APP_DIR / "templates")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "healthguard-iot"}


@app.get("/")
def root(doctor: Doctor | None = Depends(get_current_doctor)):
    return RedirectResponse("/dashboard" if doctor else "/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, doctor: Doctor | None = Depends(get_current_doctor)):
    if doctor:
        return RedirectResponse("/dashboard", status_code=303)
    return templates.TemplateResponse(
        request=request, name="login.html", context={"error": None},
        headers={"Cache-Control": "no-store"},
    )


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, email: str = Form(""), password: str = Form(""),
          db: Session = Depends(get_db)):
    doctor = db.scalar(select(Doctor).where(Doctor.email == email.strip()))
    valid = verify_password(password, doctor.password_hash if doctor else DUMMY_PASSWORD_HASH)
    request.session.clear()
    if doctor is None or not valid:
        return templates.TemplateResponse(
            request=request, name="login.html",
            context={"error": "Invalid email or password."}, status_code=401,
            headers={"Cache-Control": "no-store"},
        )
    request.session["doctor_id"] = doctor.id
    return RedirectResponse("/dashboard", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, doctor: Doctor = Depends(require_doctor),
              db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request=request, name="dashboard.html",
        context={"doctor_name": doctor.name, "patients": assigned_patients(db, doctor.id)},
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/patients/{patient_id}/latest-reading", response_model=ReadingResponse | None)
def patient_latest_reading(patient_id: int, response: Response,
                          doctor: Doctor = Depends(require_doctor),
                          db: Session = Depends(get_db)):
    if not owns_patient(db, doctor.id, patient_id):
        raise HTTPException(404, "Patient not found")
    response.headers["Cache-Control"] = "no-store"
    return latest_reading(db, patient_id)


@app.get("/api/patients/{patient_id}/readings/recent", response_model=list[ReadingResponse])
def patient_recent_readings(patient_id: int, response: Response,
                            doctor: Doctor = Depends(require_doctor),
                            db: Session = Depends(get_db)):
    if not owns_patient(db, doctor.id, patient_id):
        raise HTTPException(404, "Patient not found")
    response.headers["Cache-Control"] = "no-store"
    return recent_readings(db, patient_id)


@app.get("/api/patients/{patient_id}/readings", response_model=list[ReadingResponse])
def patient_reading_history(patient_id: int, response: Response,
                            limit: int = Query(20, ge=1, le=100),
                            doctor: Doctor = Depends(require_doctor),
                            db: Session = Depends(get_db)):
    if not owns_patient(db, doctor.id, patient_id):
        raise HTTPException(404, "Patient not found")
    response.headers["Cache-Control"] = "no-store"
    return reading_history(db, patient_id, limit)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
