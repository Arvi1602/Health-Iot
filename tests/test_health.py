from fastapi.testclient import TestClient

from app.main import app


def test_health():
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "healthguard-iot"}


def test_health_rejects_post():
    with TestClient(app) as client:
        response = client.post("/health")

    assert response.status_code == 405
    assert response.json() == {"detail": "Method Not Allowed"}
