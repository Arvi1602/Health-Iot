"""Overview snapshots stay scoped to the doctor and match panel count semantics."""
from datetime import datetime
import pytest
from sqlalchemy import event
from app import database
from app.models import Reading, Alert, Patient
from tests.test_dashboard import client, login


def overview(client):
    login(client)
    return client.get('/dashboard').context['patients']


def test_overview_ownership_order_and_no_readings(client):
    rows = overview(client)
    assert [p['id'] for p in rows] == [41,42]
    assert all(p['reading'] is None and p['alert_count']==0 for p in rows)
    assert rows[0]['age']==45 and rows[0]['gender']=='Male'
    page = client.get('/dashboard').text
    assert 'Patient Overview' in page and 'No readings yet' in page
    assert 'Private Other Patient' not in page


def test_overview_latest_timestamp_tie_and_no_duplicates(client):
    with database.SessionLocal() as db:
        for id, timestamp, hr in [(1,datetime(2026,1,1),70),(2,datetime(2026,1,1),83),(3,datetime(2025,1,1),90)]:
            db.add(Reading(id=id,patient_id=41,recorded_at=timestamp,heart_rate=hr,spo2=97,temperature_c=36.9))
        db.commit()
    rows = overview(client)
    assert len(rows)==2
    assert rows[0]['reading']['id']==2 and rows[0]['reading']['heart_rate']==83
    assert rows[0]['reading']['recorded_at']=='2026-01-01T00:00:00Z'
    assert rows[1]['reading'] is None


@pytest.mark.parametrize('count,expected', [(3,3),(14,10)])
def test_overview_recent_alert_count_includes_resolved(client,count,expected):
    with database.SessionLocal() as db:
        for i in range(count):
            db.add(Alert(patient_id=41,alert_type='heart_rate_high',message='Demo threshold crossed.',severity='warning',is_resolved=i==0))
        db.add(Alert(patient_id=99,alert_type='spo2_low',message='Private',severity='warning'))
        db.commit()
    rows=overview(client)
    assert rows[0]['alert_count']==expected and rows[1]['alert_count']==0
    assert rows[0]['alert_count']==min(len(client.get('/api/patients/41/alerts').json()),10)


def test_overview_single_query(client):
    from app.dashboard_data import assigned_patients
    queries=[]
    def observe(*args): queries.append(args[2])
    with database.SessionLocal() as db:
        doctor_id=db.get(Patient,41).doctor_id
        event.listen(database.engine,'before_cursor_execute',observe)
        try: assert len(assigned_patients(db,doctor_id))==2
        finally: event.remove(database.engine,'before_cursor_execute',observe)
    assert len(queries)==1
