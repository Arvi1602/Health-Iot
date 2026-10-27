"""Sensor input bounds validate data, not clinical conditions."""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReadingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: int = Field(strict=True, gt=0, le=9223372036854775807)
    heart_rate: int = Field(strict=True, gt=0, le=300)
    spo2: float = Field(strict=True, ge=0, le=100, allow_inf_nan=False)
    temperature_c: float = Field(strict=True, ge=20, le=50, allow_inf_nan=False)
    recorded_at: datetime | None = None

    @field_validator("recorded_at", mode="before")
    @classmethod
    def require_iso_timestamp(cls, value):
        if value is not None and not isinstance(value, (str, datetime)):
            raise ValueError("recorded_at must be an ISO 8601 datetime")
        if isinstance(value, str):
            # Prevent Pydantic from interpreting numeric strings as Unix epochs.
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value

    @field_validator("recorded_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        # Existing SQLite DateTime columns store UTC without timezone information.
        # A supplied timestamp without an offset is interpreted as UTC.
        try:
            return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(
                timezone.utc
            ).replace(tzinfo=None)
        except (OverflowError, ValueError) as exc:
            raise ValueError("recorded_at is outside the supported UTC range") from exc


class ReadingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patient_id: int
    heart_rate: int
    spo2: float
    temperature_c: float
    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def expose_utc(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class AlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patient_id: int
    reading_id: int | None
    alert_type: str
    message: str
    severity: str
    is_resolved: bool
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def expose_utc(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


# A single envelope for data and no-data responses; memberships are rule degrees.


class FuzzyAssessmentResponse(BaseModel):
    risk_score: float = Field(ge=0, le=100, allow_inf_nan=False)
    status: Literal['normal', 'warning', 'critical']
    input_memberships: dict[str, dict[str, float]]
    output_memberships: dict[str, float]


class FuzzyResponse(BaseModel):
    patient_id: int
    reading_id: int | None = None
    recorded_at: datetime | None = None
    assessment: FuzzyAssessmentResponse | None = None
