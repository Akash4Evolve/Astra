from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from .models import Measurement, QualityStatus, SourceType


class CheckIn(BaseModel):
    """Daily self-report. Scales (assumption, documented): mood/stress/fatigue 1 (low) to 5 (high)."""

    checkin_id: UUID = Field(default_factory=uuid4)
    astronaut_id: str = Field(min_length=1)
    timestamp_utc: datetime
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sleep_hours: float = Field(ge=0, le=24)
    mood: int = Field(ge=1, le=5)
    stress: int = Field(ge=1, le=5)
    fatigue: int = Field(ge=1, le=5)
    symptoms: list[str] = Field(default_factory=list, max_length=20)
    note: str | None = Field(default=None, max_length=500)
    source_type: SourceType = SourceType.MANUAL
    is_simulated: bool = False

    @field_validator("timestamp_utc", "received_at")
    @classmethod
    def _require_timezone(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("timestamp must include a timezone, e.g. 2026-11-01T20:00:00Z")
        return v.astimezone(timezone.utc)

    @field_validator("symptoms")
    @classmethod
    def _clean_symptoms(cls, v: list[str]) -> list[str]:
        cleaned = [s.strip() for s in v]
        if any(not s or len(s) > 60 for s in cleaned):
            raise ValueError("each symptom must be 1-60 characters")
        return cleaned

    @model_validator(mode="after")
    def _check_consistency(self) -> "CheckIn":
        if self.is_simulated != (self.source_type == SourceType.SIMULATED):
            raise ValueError("is_simulated must be true exactly when source_type is SIMULATED")
        return self


def checkin_to_measurement(c: CheckIn) -> Measurement:
    """Sleep duration is continuous, so it can use the baseline/alert engine.
    record_id = checkin_id, so alert evidence traces back to the check-in."""
    return Measurement(
        record_id=c.checkin_id,
        astronaut_id=c.astronaut_id,
        device_id=None,
        timestamp_utc=c.timestamp_utc,
        received_at=c.received_at,
        parameter="sleep_hours",
        value=c.sleep_hours,
        unit="h",
        source_type=c.source_type,
        quality_status=QualityStatus.VALID,
        is_simulated=c.is_simulated,
        metadata={"origin": "check-in"},
    )
