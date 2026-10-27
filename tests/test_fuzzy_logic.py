"""Academic fuzzy mathematics, independent of persistence and transport."""
from dataclasses import FrozenInstanceError
import math

import pytest

from app.config import AlertThresholds, FuzzySettings
from app.fuzzy_logic import evaluate_fuzzy_vitals, trapezoidal_membership, triangular_membership
from app.alert_rules import evaluate_reading
from app.schemas import ReadingCreate


def assess(hr=78, spo2=98, temp=36.8, settings=None):
    return evaluate_fuzzy_vitals(hr, spo2, temp, settings or FuzzySettings())


@pytest.mark.parametrize('x,expected', [(-1,0),(0,0),(2.5,.5),(5,1),(7.5,.5),(10,0),(11,0)])
def test_triangle(x, expected):
    assert triangular_membership(x, 0, 5, 10) == expected


def test_trapezoid_shoulders_and_plateau():
    assert trapezoidal_membership(0,0,0,20,45) == 1
    assert trapezoidal_membership(100,55,80,100,100) == 1
    assert trapezoidal_membership(25,0,10,30,40) == 1
    with pytest.raises(ValueError):
        triangular_membership(math.nan,0,5,10)
    with pytest.raises(ValueError):
        trapezoidal_membership(1,4,3,2,1)


@pytest.mark.parametrize('hr,expected', [(1,(1,0,0)),(50,(1,0,0)),(60,(.5,.5,0)),(66,(.2,.8,0)),(78,(0,1,0)),(94,(0,.8,.2)),(100,(0,.5,.5)),(110,(0,0,1)),(300,(0,0,1))])
def test_heart_memberships(hr, expected):
    assert tuple(assess(hr).input_memberships['heart_rate'].values()) == pytest.approx(expected)


@pytest.mark.parametrize('oxygen,low', [(0,1),(92,1),(95,.5),(96.8,.2),(98,0),(100,0)])
def test_oxygen_overlap(oxygen, low):
    m=assess(spo2=oxygen).input_memberships['spo2']
    assert m['low'] == pytest.approx(low)
    assert m['normal'] == pytest.approx(1-low)


@pytest.mark.parametrize('temp,expected', [(20,(1,0,0)),(35,(.5,.5,0)),(35.3,(.2,.8,0)),(36.8,(0,1,0)),(38,(0,.5,.5)),(39,(0,0,1)),(50,(0,0,1))])
def test_temperature_overlap(temp, expected):
    assert tuple(assess(temp=temp).input_memberships['temperature'].values()) == pytest.approx(expected)


def test_rule_cases_and_centroid():
    n,w,c=assess(),assess(120),assess(110,90,39)
    assert [r.status for r in (n,w,c)] == ['normal','warning','critical']
    assert n.risk_score < 30 and w.risk_score == pytest.approx(50) and c.risk_score > 70
    assert n.risk_score < w.risk_score < c.risk_score
    assert c.output_memberships == {'normal':0,'warning':0,'critical':1}


def test_min_max_inference_and_ties():
    r=assess(100,95,38)
    assert r.output_memberships == {'normal':.5,'warning':.5,'critical':.5}
    assert r.status == 'critical'
    assert assess(100).status == 'warning'


def test_crisp_and_fuzzy_independence_and_whiteboard():
    reading=ReadingCreate(patient_id=1,heart_rate=94,spo2=98,temperature_c=36.8)
    assert evaluate_reading(reading,AlertThresholds()) == []
    result=assess(94)
    assert result.output_memberships == pytest.approx({'normal':.8,'warning':.2,'critical':0})
    assert 20 < result.risk_score < 40
    assert result.input_memberships['heart_rate']['normal'] > 0
    assert result.input_memberships['heart_rate']['high'] > 0


def test_continuity_determinism_deep_immutability():
    scores=[assess(hr).risk_score for hr in (99,100,101)]
    assert scores == sorted(scores)
    assert max(abs(a-b) for a,b in zip(scores,scores[1:])) < 5
    assert abs(assess(100.00001).risk_score-assess(99.99999).risk_score)<.001
    r=assess(94)
    assert r==assess(94)
    with pytest.raises(FrozenInstanceError): r.status='critical'
    with pytest.raises(TypeError): r.output_memberships['normal']=0
    with pytest.raises(TypeError): r.input_memberships['heart_rate']['normal']=0


def test_bounds_across_input_grid():
    for hr in (1,50,60,78,94,100,110,300):
        for spo2 in (0,92,95,98,100):
            for temp in (20,35,36.8,38,50):
                r=assess(hr,spo2,temp)
                assert 0 <= r.risk_score <= 100
                assert all(0<=v<=1 for group in r.input_memberships.values() for v in group.values())
                assert all(0<=v<=1 for v in r.output_memberships.values())


@pytest.mark.parametrize('width', [0,-1,math.nan,math.inf,True,'3'])
def test_invalid_widths(width):
    for name in ('heart_rate_transition_bpm','spo2_transition_percent','temperature_transition_c'):
        with pytest.raises(ValueError): FuzzySettings(**{name:width})


def test_invalid_overlap_and_valid_touching():
    with pytest.raises(ValueError): FuzzySettings(heart_rate_transition_bpm=21)
    with pytest.raises(ValueError): FuzzySettings(temperature_transition_c=2)
    assert assess(settings=FuzzySettings(heart_rate_transition_bpm=20))


def test_environment_and_custom_anchors(monkeypatch):
    monkeypatch.setenv('FUZZY_HEART_RATE_TRANSITION_BPM','5')
    monkeypatch.setenv('FUZZY_SPO2_TRANSITION_PERCENT','2')
    monkeypatch.setenv('FUZZY_TEMPERATURE_TRANSITION_C','.25')
    settings=FuzzySettings.from_environment(AlertThresholds(heart_rate_high=90))
    assert assess(90,settings=settings).input_memberships['heart_rate']['high']==.5
    assert settings.spo2_transition_percent==2 and settings.temperature_transition_c==.25
    monkeypatch.setenv('FUZZY_HEART_RATE_TRANSITION_BPM','bad')
    with pytest.raises(ValueError, match='FUZZY_HEART_RATE'): FuzzySettings.from_environment(AlertThresholds())


@pytest.mark.parametrize('values', [(math.nan,98,36.8),(78,math.inf,36.8),(78,98,19),(0,98,36.8),(78,101,36.8),(True,98,36.8)])
def test_invalid_input(values):
    with pytest.raises(ValueError): assess(*values)


@pytest.mark.parametrize('hr,oxygen,temp', [(40,90,36.8),(40,98,34),(40,98,39),(120,98,34),(78,90,34),(78,90,39)])
def test_all_abnormal_pair_combinations(hr,oxygen,temp):
    r=assess(hr,oxygen,temp)
    assert r.status=='critical' and r.output_memberships['critical']==1


def test_centroid_reference_and_huge_finite_width():
    assert assess(94).risk_score==pytest.approx(23.429850746268656)
    r=assess(settings=FuzzySettings(spo2_transition_percent=1e308))
    assert r.input_memberships['spo2']['low']==pytest.approx(.5)


@pytest.mark.parametrize('raw', ['0','nan','21'])
def test_invalid_config_fails_startup(raw):
    import os
    import subprocess
    import sys
    result=subprocess.run([sys.executable,'-c','from app.main import app'],
        env=dict(os.environ,FUZZY_HEART_RATE_TRANSITION_BPM=raw),capture_output=True,text=True)
    assert result.returncode!=0 and ('FUZZY_' in result.stderr or 'Fuzzy low/high' in result.stderr)
