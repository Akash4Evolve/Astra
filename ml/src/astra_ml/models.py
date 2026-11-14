from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


class SourceType(str, Enum):
    DEVICE = "DEVICE"
    SIMULATED = "SIMULATED"
    MANUAL = "MANUAL"
    NASA_RESEARCH = "NASA_RESEARCH"
    PUBLIC_RESEARCH = "PUBLIC_RESEARCH"
    CLINICAL = "CLINICAL"


class QualityStatus(str, Enum):
    VALID = "VALID"
    SUSPECT = "SUSPECT"
    MISSING = "MISSING"
    STALE = "STALE"


# parameter -> (expected unit, min, max).
# The bounds only reject physically impossible values (garbage input).
# They are NOT clinical thresholds.
PARAMETERS: dict[str, tuple[str, float, float]] = {
    "heart_rate": ("bpm", 20.0, 250.0),
    "skin_temperature": ("degC", 10.0, 45.0),
    "sleep_hours": ("h", 0.0, 24.0),
}


class Measurement(BaseModel):
    record_id: UUID = Field(default_factory=uuid4)
    astronaut_id: str = Field(min_length=1)
    device_id: str | None = None
    timestamp_utc: datetime  # when it was measured (source time)
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    parameter: str
    value: float
    unit: str
    source_type: SourceType
    quality_status: QualityStatus = QualityStatus.VALID
    is_simulated: bool
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp_utc", "received_at")
    @classmethod
    def _require_timezone(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("timestamp must include a timezone, e.g. 2026-11-01T10:30:00Z")
        return v.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _check_consistency(self) -> "Measurement":
        spec = PARAMETERS.get(self.parameter)
        if spec is None:
            raise ValueError(f"unknown parameter '{self.parameter}'")
        unit, lo, hi = spec
        if self.unit != unit:
            raise ValueError(f"{self.parameter} must use unit '{unit}', got '{self.unit}'")
        if not (lo <= self.value <= hi):  # also rejects NaN
            raise ValueError(f"{self.parameter} value {self.value} is outside plausible range")
        if self.is_simulated != (self.source_type == SourceType.SIMULATED):
            raise ValueError("is_simulated must be true exactly when source_type is SIMULATED")
        return self
