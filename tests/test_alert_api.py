"""Atomic persistence and ownership checks for academic demo alerts."""
from datetime import datetime, timedelta
from itertools import islice
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.exc import SQLAlchemyError

from app import config, database, readings
from app.alert_rules import evaluate_reading
from app.auth import hash_password
from app.main import app
from app.models import Alert, Doctor, Patient, Reading
from app.simulator import generate_readings
from app.websocket_manager import manager


@pytest.fixture
def client(isolated_database, monkeypatch):
    monkeypatch.setattr(config, 'ALERT_THRESHOLDS', config.AlertThresholds())
    with database.SessionLocal() as db:
        owner = Doctor(name='Owner', email='alerts@example.com', password_hash=hash_password('test-password'))
        other = Doctor(name='Other', email='other@example.com', password_hash='unused')
        db.add_all([owner, other]); db.flush()
        db.add_all([Patient(id=42, name='Own patient', age=45, gender='Male', doctor=owner),
                    Patient(id=43, name='Empty patient', age=32, gender='Female', doctor=owner),
                    Patient(id=99, name='Private patient', age=50, gender='Male', doctor=other)])
        db.commit()
    with TestClient(app, follow_redirects=False) as client:
        yield client


def login(client):
    assert client.post('/login', data={'email': 'alerts@example.com', 'password': 'test-password'}).status_code == 303


def payload(**values):
    return dict(patient_id=42, heart_rate=78, spo2=98, temperature_c=36.8) | values


def counts():
    with database.SessionLocal() as db:
        return tuple(db.scalar(select(func.count()).select_from(model)) for model in (Reading, Alert))


@pytest.mark.parametrize('values,types', [
    ({}, []), ({'heart_rate': 59}, ['heart_rate_low']),
    ({'heart_rate': 101}, ['heart_rate_high']), ({'spo2': 94}, ['spo2_low']),
    ({'temperature_c': 34.9}, ['temperature_low']), ({'temperature_c': 38.1}, ['temperature_high']),
    ({'heart_rate': 110, 'spo2': 90, 'temperature_c': 39}, ['heart_rate_high', 'spo2_low', 'temperature_high']),
    ({'heart_rate': 60}, []), ({'heart_rate': 100}, []), ({'spo2': 95}, []),
    ({'temperature_c': 35}, []), ({'temperature_c': 38}, []),
])
def test_ingestion_candidates_and_relationships(client, values, types):
    result = client.post('/api/readings', json=payload(**values))
    assert result.status_code == 201
    assert set(result.json()) == {'id', 'patient_id', 'heart_rate', 'spo2', 'temperature_c', 'recorded_at'}
    assert counts() == (1, len(types))
    with database.SessionLocal() as db:
        reading = db.get(Reading, result.json()['id'])
        alerts = db.scalars(select(Alert).order_by(Alert.id)).all()
        assert [a.alert_type for a in alerts] == types
        expected = evaluate_reading(reading)
        for alert, candidate in zip(alerts, expected):
            assert alert.reading_id == reading.id and alert.patient_id == reading.patient_id
            assert alert in reading.alerts and alert in reading.patient.alerts
            assert (alert.message, alert.severity) == (candidate.message, 'warning')
            assert alert.is_resolved is False
            assert alert.created_at is not None


def test_custom_config_applies_only_to_new_alerts(client, monkeypatch):
    monkeypatch.setattr(config, 'ALERT_THRESHOLDS', config.AlertThresholds(heart_rate_high=90))
    assert client.post('/api/readings', json=payload(heart_rate=95)).status_code == 201
    monkeypatch.setattr(config, 'ALERT_THRESHOLDS', config.AlertThresholds())
    assert client.post('/api/readings', json=payload(heart_rate=95)).status_code == 201
    login(client)
    monkeypatch.setattr(readings, 'evaluate_reading', Mock(side_effect=AssertionError('GET must not evaluate')))
    result = client.get('/api/patients/42/alerts')
    assert result.status_code == 200 and len(result.json()) == 1
    assert result.json()[0]['alert_type'] == 'heart_rate_high'


@pytest.mark.parametrize('values,status', [({'heart_rate': 500}, 422), ({'patient_id': 999}, 404)])
def test_rejected_packet_never_evaluates_or_broadcasts(client, monkeypatch, values, status):
    evaluator = Mock(side_effect=AssertionError('Invalid/missing patient must not evaluate'))
    broadcast = AsyncMock()
    monkeypatch.setattr(readings, 'evaluate_reading', evaluator)
    monkeypatch.setattr(manager, 'broadcast', broadcast)
    assert client.post('/api/readings', json=payload(**values)).status_code == status
    assert counts() == (0, 0)
    evaluator.assert_not_called(); broadcast.assert_not_awaited()


@pytest.mark.parametrize('failure', ['alert_insert', 'commit'])
def test_atomic_failure_rolls_back_everything(client, monkeypatch, failure):
    factory = database.SessionLocal
    session = factory()
    rollback = Mock(wraps=session.rollback)
    close = Mock(wraps=session.close)
    broadcast = AsyncMock()
    monkeypatch.setattr(database, 'SessionLocal', lambda: session)
    monkeypatch.setattr(session, 'rollback', rollback)
    monkeypatch.setattr(session, 'close', close)
    monkeypatch.setattr(manager, 'broadcast', broadcast)
    inserted = []

    def fail_on_second_alert(mapper, connection, target):
        inserted.append(target.alert_type)
        if len(inserted) == 2:
            raise SQLAlchemyError('private failure details')

    if failure == 'alert_insert':
        event.listen(Alert, 'before_insert', fail_on_second_alert)
    else:
        def fail_commit():
            session.flush()  # Both reading and alerts have reached SQLite, but are uncommitted.
            raise SQLAlchemyError('private failure details')
        monkeypatch.setattr(session, 'commit', fail_commit)
    try:
        result = client.post('/api/readings', json=payload(heart_rate=110, spo2=90, temperature_c=39))
    finally:
        if failure == 'alert_insert':
            event.remove(Alert, 'before_insert', fail_on_second_alert)
    assert result.status_code == 500
    assert result.json() == {'detail': 'Unable to save reading'}
    rollback.assert_called_once(); close.assert_called_once(); broadcast.assert_not_awaited()
    assert not session.in_transaction()
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Reading)) == 0
        assert db.scalar(select(func.count()).select_from(Alert)) == 0


def test_alert_api_requires_login(client):
    result = client.get('/api/patients/42/alerts')
    assert result.status_code == 303 and result.headers['location'] == '/login'


@pytest.mark.parametrize('patient_id', [99, 999, 0, -1, 9223372036854775808])
def test_alert_api_ownership(client, patient_id):
    client.post('/api/readings', json=payload(patient_id=99, heart_rate=110))
    login(client)
    result = client.get(f'/api/patients/{patient_id}/alerts')
    assert result.status_code == 404 and result.json() == {'detail': 'Patient not found'}


def test_empty_list(client):
    login(client)
    response = client.get('/api/patients/43/alerts')
    assert response.status_code == 200 and response.json() == []
    assert response.headers['cache-control'] == 'no-store'


def test_order_limit_and_serialization(client):
    with database.SessionLocal() as db:
        for index in range(55):
            db.add(Alert(id=index + 1, patient_id=42, reading_id=None, alert_type='heart_rate_high',
                         message='Demo threshold crossed.', severity='warning',
                         created_at=datetime(2026, 10, 6) + timedelta(seconds=(54-index)//2)))
        db.add(Alert(id=99, patient_id=99, alert_type='private', message='Private message', severity='warning'))
        db.commit()
    login(client)
    result = client.get('/api/patients/42/alerts?limit=1000')
    assert result.status_code == 200
    rows = result.json()
    assert len(rows) == 50
    assert [(row['created_at'], row['id']) for row in rows] == sorted(
        [(row['created_at'], row['id']) for row in rows], reverse=True)
    assert rows[0]['id'] == 1 and rows[-1]['id'] == 51
    assert all(row['patient_id'] == 42 and row['created_at'].endswith('Z') for row in rows)
    assert set(rows[0]) == {'id', 'patient_id', 'reading_id', 'alert_type', 'message', 'severity', 'is_resolved', 'created_at'}
    assert rows[0]['reading_id'] is None


def test_one_reading_event_after_reading_and_alerts_commit(client, monkeypatch):
    login(client)
    original = manager.broadcast
    async def committed_then_broadcast(patient_id, message):
        assert counts() == (1, 3)  # Independent session can see all rows before delivery.
        await original(patient_id, message)
    broadcast = AsyncMock(side_effect=committed_then_broadcast)
    monkeypatch.setattr(manager, 'broadcast', broadcast)
    with client.websocket_connect('/ws/patients/42') as ws:
        assert ws.receive_json()['type'] == 'connected'
        response = client.post('/api/readings', json=payload(heart_rate=110, spo2=90, temperature_c=39))
        assert response.status_code == 201
        assert ws.receive_json() == {'type': 'reading', 'data': response.json()}
        broadcast.assert_awaited_once_with(42, {'type': 'reading', 'data': response.json()})
    alerts = client.get('/api/patients/42/alerts').json()
    assert len(alerts) == 3 and all(a['reading_id'] == response.json()['id'] for a in alerts)


def test_normal_simulator_sequence_has_no_alerts(client):
    for data in islice(generate_readings(42, seed=42), 10):
        assert client.post('/api/readings', json=data).status_code == 201
    assert counts() == (10, 0)
