import base64
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner
from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker

from app import config, database
from app.auth import hash_password, verify_password
from app.main import app
from app.models import Doctor, Patient
from app.seed import DEMO_DOCTOR_EMAIL, DEMO_PASSWORD, seed_demo_data


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = database.create_sqlite_engine(f"sqlite:///{tmp_path / 'auth.db'}")
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=engine))
    seed_demo_data()
    try:
        with TestClient(app, follow_redirects=False) as client:
            yield client
    finally:
        engine.dispose()


def sign_in(client):
    return client.post("/login", data={"email": DEMO_DOCTOR_EMAIL, "password": DEMO_PASSWORD})


def test_login_page_and_static_css(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert "Doctor Monitoring Portal" in response.text
    assert 'type="password"' in response.text
    assert client.get("/static/css/style.css").status_code == 200


@pytest.mark.parametrize("path", ["/", "/dashboard", "/dashboard?doctor_id=1"])
def test_logged_out_redirects(client, path):
    response = client.get(path)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert "Dr. Ananya Sharma" not in response.text


def test_login_session_and_dashboard(client):
    response = sign_in(client)
    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard"
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "max-age=28800" in cookie
    payload = TimestampSigner(config.SECRET_KEY).unsign(client.cookies["healthguard_session"])
    session = json.loads(base64.b64decode(payload))
    with database.SessionLocal() as db:
        doctor = db.scalar(select(Doctor))
        assert session == {"doctor_id": doctor.id}
        stored_hash = doctor.password_hash
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "Welcome, Dr. Ananya Sharma" in response.text
    assert "no-store" in response.headers["cache-control"]
    assert stored_hash not in response.text
    assert DEMO_PASSWORD not in response.text
    assert set(response.context) == {"request", "doctor_name", "patients"}
    for path in ["/", "/login"]:
        response = client.get(path)
        assert response.status_code == 303
        assert response.headers["location"] == "/dashboard"


@pytest.mark.parametrize("email,password", [
    (DEMO_DOCTOR_EMAIL, "incorrect-password"),
    ("unknown@example.com", "incorrect-password"),
    ("", ""),
])
def test_invalid_login(client, email, password):
    response = client.post("/login", data={"email": email, "password": password, "doctor_id": "1"})
    assert response.status_code == 401
    assert "Invalid email or password." in response.text
    assert "healthguard_session" not in client.cookies
    assert client.get("/dashboard").headers["location"] == "/login"


def test_failure_responses_do_not_identify_existing_email(client):
    known = client.post("/login", data={"email": DEMO_DOCTOR_EMAIL, "password": "wrong"})
    unknown = client.post("/login", data={"email": "unknown@example.com", "password": "wrong"})
    assert known.status_code == unknown.status_code == 401
    assert known.text == unknown.text


def test_logout_clears_session(client):
    sign_in(client)
    response = client.post("/logout")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert "healthguard_session" not in client.cookies
    assert client.get("/dashboard").headers["location"] == "/login"
    assert client.get("/logout").status_code == 405


def test_tampered_cookie_is_rejected(client):
    sign_in(client)
    cookie = client.cookies["healthguard_session"]
    client.cookies.clear()
    client.cookies.set("healthguard_session", "X" + cookie[1:])
    assert client.get("/dashboard").headers["location"] == "/login"


def test_expired_cookie_is_rejected(client):
    payload = base64.b64encode(json.dumps({"doctor_id": 1}).encode())
    with patch.object(TimestampSigner, "get_timestamp", return_value=1):
        cookie = TimestampSigner(config.SECRET_KEY).sign(payload).decode()
    client.cookies.set("healthguard_session", cookie)
    assert client.get("/dashboard").headers["location"] == "/login"


def test_deleted_doctor_cannot_use_session(client):
    sign_in(client)
    with database.SessionLocal() as db:
        db.execute(delete(Patient))
        db.execute(delete(Doctor))
        db.commit()
    assert client.get("/dashboard").headers["location"] == "/login"
    assert "healthguard_session" not in client.cookies


def test_legacy_placeholder_fails_login_without_error(client):
    with database.SessionLocal() as db:
        db.scalar(select(Doctor)).password_hash = "demo-password-hash"
        db.commit()
    assert sign_in(client).status_code == 401


def test_health_is_public_before_and_after_login(client):
    for logged_in in [False, True]:
        if logged_in:
            sign_in(client)
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "service": "healthguard-iot"}


def test_password_hashing():
    hashed = hash_password(DEMO_PASSWORD)
    assert hashed != DEMO_PASSWORD
    assert hashed.startswith("$argon2id$")
    assert verify_password(DEMO_PASSWORD, hashed)
    assert not verify_password("wrong", hashed)
    assert hash_password(DEMO_PASSWORD) != hashed
    assert not verify_password(DEMO_PASSWORD, "demo-password-hash")


@pytest.mark.parametrize("secret", ["", "short", "change-me-for-local-development-please"])
def test_unsafe_session_secret_rejected(monkeypatch, secret):
    monkeypatch.setattr(config, "SECRET_KEY", secret)
    with pytest.raises(RuntimeError, match="Set SECRET_KEY"):
        config.validate_session_secret()
