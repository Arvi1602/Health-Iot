"""Protected, bounded persisted measurement history."""
from datetime import datetime, timedelta

import pytest
from app import database
from app.models import Reading
from tests.test_dashboard import client, login


def test_history_auth(client):
    response = client.get('/api/patients/41/readings')
    assert response.status_code == 303 and response.headers['location'] == '/login'


@pytest.mark.parametrize('patient_id', [99, 999, 0, -1, 9223372036854775808])
def test_history_ownership(client, patient_id):
    login(client)
    response = client.get(f'/api/patients/{patient_id}/readings')
    assert response.status_code == 404 and response.json() == {'detail': 'Patient not found'}


def test_history_empty(client):
    login(client)
    response = client.get('/api/patients/41/readings')
    assert response.status_code == 200 and response.json() == []
    assert response.headers['cache-control'] == 'no-store'


@pytest.mark.parametrize('query,limit', [('',20), ('?limit=1',1), ('?limit=5',5), ('?limit=20',20), ('?limit=100',100)])
def test_history_order_limit_values_and_isolation(client, query, limit):
    with database.SessionLocal() as db:
        for index in range(105):
            db.add(Reading(id=index+1, patient_id=41, heart_rate=78, spo2=97.5, temperature_c=36.8,
                           recorded_at=datetime(2026,10,6)+timedelta(seconds=(104-index)//2)))
        db.add(Reading(id=999,patient_id=42,heart_rate=99,spo2=99,temperature_c=37))
        db.commit()
    login(client)
    response = client.get('/api/patients/41/readings'+query)
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == limit
    assert rows[0]['id'] == 1
    if limit >= 3:
        assert [row['id'] for row in rows[:3]] == [1,3,2]
    assert [(r['recorded_at'],r['id']) for r in rows] == sorted([(r['recorded_at'],r['id']) for r in rows],reverse=True)
    assert all(r['patient_id']==41 and (r['heart_rate'],r['spo2'],r['temperature_c'])==(78,97.5,36.8) for r in rows)
    assert all(r['recorded_at'].endswith('Z') for r in rows)
    assert set(rows[0]) == {'id','patient_id','heart_rate','spo2','temperature_c','recorded_at'}


@pytest.mark.parametrize('limit', ['0','101','-1','abc','1.5'])
def test_history_invalid_limit(client, limit):
    login(client)
    assert client.get('/api/patients/41/readings?limit='+limit).status_code == 422
