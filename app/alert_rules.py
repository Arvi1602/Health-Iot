"""DEMO THRESHOLDS ONLY. NOT MEDICAL ADVICE. NOT VALIDATED FOR CLINICAL USE.

Evaluate already-validated readings; ingestion validation remains separate.
No persistence, transport, or UI integration occurs here.
"""

from dataclasses import dataclass
from typing import Protocol

from app import config


class VitalReading(Protocol):
    """Shared attributes of Reading, ReadingCreate, and ReadingResponse."""

    heart_rate: int
    spo2: float
    temperature_c: float


@dataclass(frozen=True)
class AlertCandidate:
    alert_type: str
    severity: str
    message: str


def evaluate_reading(reading: VitalReading,
                     thresholds: config.AlertThresholds | None = None) -> list[AlertCandidate]:
    """Return candidates in heart-rate, SpO₂, temperature order.

    Exact boundaries are inside the demo range. Inputs must already be valid.
    Configuration is immutable; pass explicit thresholds for isolated evaluation.
    """
    limits = thresholds if thresholds is not None else config.ALERT_THRESHOLDS
    candidates = []
    checks = (
        (reading.heart_rate < limits.heart_rate_low, "heart_rate_low", "Heart rate", "below"),
        (reading.heart_rate > limits.heart_rate_high, "heart_rate_high", "Heart rate", "above"),
        (reading.spo2 < limits.spo2_low, "spo2_low", "SpO₂", "below"),
        (reading.temperature_c < limits.temperature_low, "temperature_low", "Temperature", "below"),
        (reading.temperature_c > limits.temperature_high, "temperature_high", "Temperature", "above"),
    )
    for matched, alert_type, label, direction in checks:
        if matched:
            candidates.append(AlertCandidate(alert_type, "warning",
                f"{label} is {direction} the configured demo threshold."))
    return candidates
