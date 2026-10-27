"""Owned latest-reading assessment; no new persistence or WebSocket format."""
from datetime import datetime
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from app import config, database
from app.auth import hash_password
from app.config import AlertThresholds, FuzzySettings
from app.main import app
from app.models import Alert, Doctor, Patient, Reading


@pytest.fixture
def client(isolated_database, monkeypatch):
    monkeypatch.setattr(config,'FUZZY_SETTINGS',FuzzySettings())
    monkeypatch.setattr(config,'ALERT_THRESHOLDS',AlertThresholds())
    with database.SessionLocal() as db:
        a=Doctor(name='Fuzzy',email='fuzzy@example.com',password_hash=hash_password('test-pass'))
        b=Doctor(name='Other',email='other@example.com',password_hash='unused')
        db.add_all([a,b]); db.flush()
        db.add_all([Patient(id=1,name='Own',age=30,gender='Female',doctor=a),Patient(id=2,name='Other',age=30,gender='Male',doctor=b)])
        db.commit()
    with TestClient(app,follow_redirects=False) as c: yield c


def login(c):
    assert c.post('/login',data={'email':'fuzzy@example.com','password':'test-pass'}).status_code==303


def counts():
    with database.SessionLocal() as db:
        return tuple(db.scalar(select(func.count()).select_from(m)) for m in (Reading,Alert))


def test_auth(client):
    r=client.get('/api/patients/1/fuzzy-assessment')
    assert r.status_code==303 and r.headers['location']=='/login'


@pytest.mark.parametrize('patient',[2,999,0,-1,9223372036854775808])
def test_ownership(client,patient):
    login(client)
    r=client.get(f'/api/patients/{patient}/fuzzy-assessment')
    assert r.status_code==404 and r.json()=={'detail':'Patient not found'}


def test_empty(client):
    login(client)
    r=client.get('/api/patients/1/fuzzy-assessment')
    assert r.status_code==200 and r.headers['cache-control']=='no-store'
    assert r.json()=={'patient_id':1,'reading_id':None,'recorded_at':None,'assessment':None}


def test_latest_tie_and_no_writes(client):
    with database.SessionLocal() as db:
        for id,year,hr in [(1,2026,78),(2,2026,94),(3,2025,120)]:
            db.add(Reading(id=id,patient_id=1,heart_rate=hr,spo2=98,temperature_c=36.8,recorded_at=datetime(year,1,1)))
        db.commit()
    login(client); before=counts()
    for _ in range(2):
        r=client.get('/api/patients/1/fuzzy-assessment'); data=r.json()
        assert r.status_code==200 and r.headers['cache-control']=='no-store'
        assert data['reading_id']==2 and data['recorded_at']=='2026-01-01T00:00:00Z'
        assert data['assessment']['input_memberships']['heart_rate']['high']==pytest.approx(.2)
    assert counts()==before


def test_independent_crisp_alerts_and_event(client):
    login(client)
    with client.websocket_connect('/ws/patients/1') as ws:
        ws.receive_json()
        r=client.post('/api/readings',json={'patient_id':1,'heart_rate':110,'spo2':90,'temperature_c':39})
        assert r.status_code==201
        event=ws.receive_json()
        assert event=={'type':'reading','data':r.json()}
        before=counts(); assert before==(1,3)
        a=client.get('/api/patients/1/fuzzy-assessment').json()
        assert a['reading_id']==r.json()['id'] and a['assessment']['status']=='critical'
        assert counts()==before


def test_custom_configuration(client,monkeypatch):
    login(client)
    client.post('/api/readings',json={'patient_id':1,'heart_rate':94,'spo2':98,'temperature_c':36.8})
    monkeypatch.setattr(config,'FUZZY_SETTINGS',FuzzySettings(thresholds=AlertThresholds(heart_rate_high=90),heart_rate_transition_bpm=5))
    r=client.get('/api/patients/1/fuzzy-assessment').json()['assessment']
    assert r['input_memberships']['heart_rate']['high']==pytest.approx(.9)
    assert r['status']=='warning' and counts()==(1,0)
