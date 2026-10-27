"""Basic settings loaded from the environment and optional local .env file."""

import os
import math
from dataclasses import dataclass, fields
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

APP_NAME = os.getenv("APP_NAME", "HealthGuard IoT")
APP_ENV = os.getenv("APP_ENV", "development")
SECRET_KEY = os.getenv("SECRET_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./healthguard.db")


def validate_session_secret() -> None:
    if len(SECRET_KEY.strip()) < 32 or SECRET_KEY.startswith("change-"):
        raise RuntimeError("Set SECRET_KEY to a random value of at least 32 characters in .env or the environment.")


@dataclass(frozen=True)
class AlertThresholds:
    """Academic demo defaults only: not medical advice or clinically validated."""

    heart_rate_low: int = 60
    heart_rate_high: int = 100
    spo2_low: float = 95.0
    temperature_low: float = 35.0
    temperature_high: float = 38.0

    def __post_init__(self):
        # These are the broader ingestion bounds, not additional alert thresholds.
        bounds = (("heart_rate_low", 1, 300), ("heart_rate_high", 1, 300),
                  ("spo2_low", 0, 100), ("temperature_low", 20, 50),
                  ("temperature_high", 20, 50))
        for name, minimum, maximum in bounds:
            value = getattr(self, name)
            numeric = type(value) in (int, float)
            if (not numeric or not minimum <= value <= maximum or not math.isfinite(value)
                    or (name.startswith("heart_rate") and type(value) is not int)):
                raise ValueError(f"ALERT_{name.upper()} must be a finite {'integer' if name.startswith('heart_rate') else 'number'} between {minimum} and {maximum}")
        if self.heart_rate_low >= self.heart_rate_high:
            raise ValueError("ALERT_HEART_RATE_LOW must be less than ALERT_HEART_RATE_HIGH")
        if self.temperature_low >= self.temperature_high:
            raise ValueError("ALERT_TEMPERATURE_LOW must be less than ALERT_TEMPERATURE_HIGH")

    @classmethod
    def from_environment(cls):
        values = {}
        for field in fields(cls):
            key = f"ALERT_{field.name.upper()}"
            raw = os.getenv(key)
            if raw is not None:
                try:
                    values[field.name] = int(raw) if field.name.startswith("heart_rate") else float(raw)
                except ValueError:
                    raise ValueError(f"{key} must be numeric (heart-rate thresholds require integers)") from None
        return cls(**values)


# Uses the existing project .env loader above. Invalid settings fail at startup.
ALERT_THRESHOLDS = AlertThresholds.from_environment()


@dataclass(frozen=True)
class FuzzySettings:
    """Academic overlap widths; reuse crisp anchors, never clinical cutoffs."""

    thresholds: AlertThresholds = AlertThresholds()
    heart_rate_transition_bpm: float = 10.0
    spo2_transition_percent: float = 3.0
    temperature_transition_c: float = 0.5

    def __post_init__(self):
        for name in ('heart_rate_transition_bpm', 'spo2_transition_percent', 'temperature_transition_c'):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError(f'FUZZY_{name.upper()} must be finite and greater than zero')
        for low, high, width in (
            (self.thresholds.heart_rate_low, self.thresholds.heart_rate_high, self.heart_rate_transition_bpm),
            (self.thresholds.temperature_low, self.thresholds.temperature_high, self.temperature_transition_c),
        ):
            if 2 * width > high - low:
                raise ValueError('Fuzzy low/high transition regions must not overlap: 2 * width <= high - low')

    @classmethod
    def from_environment(cls, thresholds):
        values = {}
        for name in ('heart_rate_transition_bpm', 'spo2_transition_percent', 'temperature_transition_c'):
            key = f'FUZZY_{name.upper()}'
            if key in os.environ:
                try:
                    values[name] = float(os.environ[key])
                except ValueError:
                    raise ValueError(f'{key} must be numeric') from None
        return cls(thresholds=thresholds, **values)


FUZZY_SETTINGS = FuzzySettings.from_environment(ALERT_THRESHOLDS)
