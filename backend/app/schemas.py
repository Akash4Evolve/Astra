from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from astra_ml.checkins import CheckIn


class ActionType(str, Enum):
    NOTE = "NOTE"
    FOLLOW_UP_MEASUREMENT = "FOLLOW_UP_MEASUREMENT"
    PROTOCOL_FOLLOWED = "PROTOCOL_FOLLOWED"
    ESCALATION_REQUESTED = "ESCALATION_REQUESTED"  # recorded by the astronaut; ASTRA never decides this


Outcome = Literal["PENDING", "COMPLETED", "NOT_NEEDED"]


class ActionCreate(BaseModel):
    alert_id: str = Field(min_length=1, max_length=40)
    action_type: ActionType
    note: str | None = Field(default=None, max_length=500)
    follow_up_at: datetime | None = None
    outcome: Outcome = "PENDING"

    @field_validator("follow_up_at")
    @classmethod
    def _require_timezone(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return None
        if v.tzinfo is None:
            raise ValueError("follow_up_at must include a timezone, e.g. 2026-11-25T08:00:00Z")
        return v.astimezone(timezone.utc)

    @field_validator("note")
    @classmethod
    def _clean_note(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None

    @model_validator(mode="after")
    def _requirements(self) -> "ActionCreate":
        if self.action_type == ActionType.NOTE and not self.note:
            raise ValueError("a NOTE action needs text")
        if self.action_type == ActionType.FOLLOW_UP_MEASUREMENT and self.follow_up_at is None:
            raise ValueError("a follow-up measurement needs follow_up_at")
        return self


class Action(BaseModel):
    action_id: str = Field(default_factory=lambda: f"ACT-{uuid4().hex[:8].upper()}")
    alert_id: str
    astronaut_id: str
    timestamp_utc: datetime  # assigned by the server
    action_type: ActionType
    note: str | None = None
    follow_up_at: datetime | None = None
    outcome: Outcome = "PENDING"


class CheckInResult(BaseModel):
    checkin: CheckIn
    duplicate: bool
    alerts: list[str]


class AlertSummary(BaseModel):
    alert_id: str
    level: str
    title: str
    domain: str
    created_at: datetime
    status: str


class LatestValue(BaseModel):
    value: float
    unit: str
    timestamp_utc: datetime
    quality_status: str
    source_type: str
    is_simulated: bool


class IndicatorOut(BaseModel):
    parameter: str
    label: str
    unit: str
    data_status: Literal["AVAILABLE", "INSUFFICIENT_DATA", "NO_DATA"]
    latest: LatestValue | None = None
    position_vs_baseline: str | None = None
    robust_z: float | None = None


class DomainOut(BaseModel):
    domain: str
    label: str
    data_status: Literal["AVAILABLE", "INSUFFICIENT_DATA", "NO_DATA", "NOT_CONNECTED"]
    note: str | None = None
    indicators: list[IndicatorOut] = Field(default_factory=list)
    open_alert_count: int = 0
    highest_open_level: str | None = None


class DeviceStatusOut(BaseModel):
    device_id: str
    state: Literal["CONNECTED", "STALE"]
    last_seen_at: datetime
    last_reading_at: datetime
    seconds_since_last_seen: int
    stale_after_seconds: int
    battery_percent: float | None = None
    battery_note: str = "Not reported by this source"
    recent_quality: dict[str, int]
    source_types: list[str]
    contains_simulated_data: bool


class DashboardOut(BaseModel):
    astronaut_id: str
    generated_at: datetime
    domains: list[DomainOut]
    open_alerts: list[AlertSummary]
    devices: list[DeviceStatusOut]
    data_sources: list[str]
    contains_simulated_data: bool
    notice: str


class TrendPoint(BaseModel):
    record_id: str
    timestamp_utc: datetime
    value: float
    quality_status: str
    is_simulated: bool


class BaselineOut(BaseModel):
    established: bool
    reason: str
    centre: float | None = None
    dispersion: float | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    sample_count: int | None = None
    model_version: str | None = None


class TrendSeries(BaseModel):
    parameter: str
    unit: str
    points: list[TrendPoint]
    total_points: int
    limit: int
    offset: int
    baseline: BaselineOut


class TrendsOut(BaseModel):
    astronaut_id: str
    start: datetime | None
    end: datetime | None
    series: list[TrendSeries]