"""Software demo rule tests; values are not clinical recommendations."""

from dataclasses import FrozenInstanceError
from datetime import datetime
import os
import subprocess
import sys
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import func, select

from app import config, database
from app.alert_rules import AlertCandidate, evaluate_reading
from app.config import AlertThresholds
from app.models import Alert, Reading
from app.schemas import ReadingCreate, ReadingResponse
from app.websocket_manager import manager


def reading(**values):
    return ReadingCreate(**({'patient_id': 1, 'heart_rate': 78, 'spo2': 98,
                             'temperature_c': 36.8} | values))


def test_in_range():
    assert evaluate_reading(reading(), AlertThresholds()) == []


@pytest.mark.parametrize('field,value,kind,label,direction', [
    ('heart_rate', 59, 'heart_rate_low', 'Heart rate', 'below'),
    ('heart_rate', 101, 'heart_rate_high', 'Heart rate', 'above'),
    ('spo2', 94, 'spo2_low', 'SpO₂', 'below'),
    ('temperature_c', 34.9, 'temperature_low', 'Temperature', 'below'),
    ('temperature_c', 38.1, 'temperature_high', 'Temperature', 'above'),
])
def test_each_rule(field, value, kind, label, direction):
    assert evaluate_reading(reading(**{field: value}), AlertThresholds()) == [
        AlertCandidate(kind, 'warning', f'{label} is {direction} the configured demo threshold.')]


@pytest.mark.parametrize('field,value', [('heart_rate', 60), ('heart_rate', 100),
    ('spo2', 95), ('temperature_c', 35.0), ('temperature_c', 38.0)])
def test_exact_boundaries(field, value):
    assert evaluate_reading(reading(**{field: value}), AlertThresholds()) == []


def test_multiple_candidates_order_determinism_and_immutability():
    value = reading(heart_rate=110, spo2=90, temperature_c=39)
    before = value.model_dump()
    first = evaluate_reading(value, AlertThresholds())
    assert [item.alert_type for item in first] == ['heart_rate_high', 'spo2_low', 'temperature_high']
    assert evaluate_reading(value, AlertThresholds()) == first
    assert value.model_dump() == before
    with pytest.raises(FrozenInstanceError):
        first[0].severity = 'changed'


@pytest.mark.parametrize('field,raw', [('heart_rate_low', '70'), ('heart_rate_high', '90'),
    ('spo2_low', '99'), ('temperature_low', '36.5'), ('temperature_high', '37.0')])
def test_environment_settings(field, raw, monkeypatch):
    for name in AlertThresholds.__dataclass_fields__:
        monkeypatch.delenv('ALERT_' + name.upper(), raising=False)
    monkeypatch.setenv('ALERT_' + field.upper(), raw)
    settings = AlertThresholds.from_environment()
    assert getattr(settings, field) == float(raw)
    monkeypatch.setattr(config, 'ALERT_THRESHOLDS', settings)
    inputs = {'heart_rate_low': {'heart_rate': 65}, 'heart_rate_high': {'heart_rate': 95},
              'spo2_low': {'spo2': 98}, 'temperature_low': {'temperature_c': 36.4},
              'temperature_high': {'temperature_c': 37.1}}
    assert [item.alert_type for item in evaluate_reading(reading(**inputs[field]))] == [field]


@pytest.mark.parametrize('values', [
    {'heart_rate_low': 120, 'heart_rate_high': 80}, {'heart_rate_low': 100},
    {'temperature_low': 39}, {'temperature_low': 38},
    {'heart_rate_low': 0}, {'heart_rate_high': 301}, {'heart_rate_high': 99.5},
    {'spo2_low': -1}, {'spo2_low': 101}, {'temperature_low': 19}, {'temperature_high': 51},
    {'spo2_low': float('nan')}, {'temperature_high': float('inf')},
    {'heart_rate_low': True}, {'temperature_low': '35'},
])
def test_invalid_configuration(values):
    with pytest.raises(ValueError, match='ALERT_'):
        AlertThresholds(**values)


@pytest.mark.parametrize('raw', ['', 'abc', '99.5', 'nan', 'inf'])
def test_invalid_environment_number(raw, monkeypatch):
    monkeypatch.setenv('ALERT_HEART_RATE_HIGH', raw)
    with pytest.raises(ValueError, match='ALERT_HEART_RATE_HIGH'):
        AlertThresholds.from_environment()


def test_invalid_config_prevents_app_import():
    env = {key: value for key, value in os.environ.items() if not key.startswith('ALERT_')}
    env.update(ALERT_HEART_RATE_LOW='120', ALERT_HEART_RATE_HIGH='80')
    result = subprocess.run([sys.executable, '-c', 'from app.main import app'], env=env,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert 'ALERT_HEART_RATE_LOW must be less than ALERT_HEART_RATE_HIGH' in result.stderr


@pytest.mark.parametrize('kind', ['schema', 'response', 'orm'])
def test_existing_reading_types_and_no_side_effects(kind, isolated_database, monkeypatch):
    values = dict(patient_id=1, heart_rate=110, spo2=90, temperature_c=39)
    if kind == 'schema':
        value = ReadingCreate(**values)
    elif kind == 'response':
        value = ReadingResponse(id=1, recorded_at=datetime(2026, 10, 6), **values)
    else:
        value = Reading(**values)
    factory = database.SessionLocal
    forbidden_db = Mock(side_effect=AssertionError('Evaluation must not open sessions'))
    broadcast = AsyncMock()
    monkeypatch.setattr(database, 'SessionLocal', forbidden_db)
    monkeypatch.setattr(manager, 'broadcast', broadcast)
    assert len(evaluate_reading(value, AlertThresholds())) == 3
    assert {key: getattr(value, key) for key in values} == values
    forbidden_db.assert_not_called()
    broadcast.assert_not_awaited()
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Alert)) == 0
