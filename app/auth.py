"""Password hashing and reusable session authentication helpers."""

from fastapi import Depends, HTTPException
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from sqlalchemy.orm import Session
from starlette.requests import HTTPConnection

from app.database import get_db
from app.models import Doctor

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return password_hash.verify(plain_password, hashed_password)
    except (UnknownHashError, ValueError):
        # Old placeholders or malformed hashes must fail authentication.
        return False


# Unknown emails still perform password verification to reduce timing differences.
DUMMY_PASSWORD_HASH = hash_password("unused-login-timing-placeholder")


def get_current_doctor(request: HTTPConnection, db: Session = Depends(get_db)) -> Doctor | None:
    doctor_id = request.session.get("doctor_id")
    if type(doctor_id) is not int:
        request.session.clear()
        return None
    doctor = db.get(Doctor, doctor_id)
    if doctor is None:
        request.session.clear()
    return doctor


def require_doctor(doctor: Doctor | None = Depends(get_current_doctor)) -> Doctor:
    if doctor is None:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return doctor
