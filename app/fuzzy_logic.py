"""Academic Mamdani demonstration. Not clinically validated or medical advice.

Pure evaluation: explicit settings, no database, transport, or persistence.
Output memberships are aggregated rule activations, not probabilities.
"""
from __future__ import annotations
from dataclasses import dataclass
from itertools import combinations
import math
from types import MappingProxyType
from typing import Mapping, TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import FuzzySettings

OUTPUT_SHAPES = MappingProxyType({
    'normal': (0, 0, 20, 45),
    'warning': (30, 50, 50, 70),
    'critical': (55, 80, 100, 100),
})
OUTPUT_UNIVERSE = tuple(range(101))


def trapezoidal_membership(x, a, b, c, d):
    """Closed shoulders when a=b or c=d; zero outside [a,d]."""
    if not all(math.isfinite(v) for v in (x, a, b, c, d)) or not a <= b <= c <= d or a == d:
        raise ValueError('Finite ordered membership points with a < d required')
    if x < a or x > d:
        return 0.0
    if b <= x <= c:
        return 1.0
    return (x - a) / (b - a) if x < b else (d - x) / (d - c)


def triangular_membership(x, a, b, c):
    return trapezoidal_membership(x, a, b, b, c)


def _low(x, anchor, width):
    return max(0.0, min(1.0, 0.5 + (anchor - x) / width / 2))


def _three(x, low, high, width):
    lo, hi = _low(x, low, width), 1.0 - _low(x, high, width)
    return {'low': lo, 'normal': min(1.0 - lo, 1.0 - hi), 'high': hi}


@dataclass(frozen=True)
class FuzzyAssessment:
    risk_score: float
    status: str
    output_memberships: Mapping[str, float]
    input_memberships: Mapping[str, Mapping[str, float]]


def evaluate_fuzzy_vitals(heart_rate, spo2, temperature_c, settings: FuzzySettings):
    for value, low, high in ((heart_rate, 1, 300), (spo2, 0, 100), (temperature_c, 20, 50)):
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError('Vitals must be finite numbers within ingestion bounds')
    t = settings.thresholds
    oxygen_low = _low(spo2, t.spo2_low, settings.spo2_transition_percent)
    inputs = {
        'heart_rate': _three(heart_rate, t.heart_rate_low, t.heart_rate_high, settings.heart_rate_transition_bpm),
        'spo2': {'low': oxygen_low, 'normal': 1.0 - oxygen_low},
        'temperature': _three(temperature_c, t.temperature_low, t.temperature_high, settings.temperature_transition_c),
    }
    normal = [v['normal'] for v in inputs.values()]
    # OR combines low/high for each vital; min implements each rule's AND.
    abnormal = [max(v.get('low', 0), v.get('high', 0)) for v in inputs.values()]
    output = {
        'normal': min(normal),
        'warning': max(min(abnormal[i], *(normal[j] for j in range(3) if j != i)) for i in range(3)),
        'critical': max(min(abnormal[i], abnormal[j]) for i, j in combinations(range(3), 2)),
    }
    # Mamdani clipping, max aggregation, discrete centroid at unit spacing.
    curve = [max(min(output[name], trapezoidal_membership(x, *shape))
                 for name, shape in OUTPUT_SHAPES.items()) for x in OUTPUT_UNIVERSE]
    area = sum(curve)
    if area <= 0:
        raise ValueError('No fuzzy output activated')
    score = sum(x * mu for x, mu in zip(OUTPUT_UNIVERSE, curve)) / area
    status = max(('normal', 'warning', 'critical'), key=lambda name: (output[name], ('normal', 'warning', 'critical').index(name)))
    return FuzzyAssessment(score, status, MappingProxyType(output),
                           MappingProxyType({name: MappingProxyType(v) for name, v in inputs.items()}))
