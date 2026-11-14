"""Delayed / offline sync (FR-13, T-09, T-10).

ASTRA runs locally, so the core loop never needs Earth. Data that was buffered while a
device or node was offline arrives later as one batch. A batch is applied exactly once:
re-sending the same batch_id returns the original result and changes nothing.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from astra_ml.checkins import CheckIn
from astra_ml.models import Measurement

MAX_ITEMS_PER_BATCH = 5000


class SyncBatch(BaseModel):
    batch_id: str = Field(min_length=1, max_length=64)  # chosen by the sender, used for idempotency
    source_node: str = Field(min_length=1, max_length=64)  # e.g. "CREWBAND-GW-01"
    created_at: datetime  # when the sender assembled the batch (it may have been offline)
    measurements: list[Measurement] = Field(default_factory=list)
    checkins: list[CheckIn] = Field(default_factory=list)

    @field_validator("created_at")
    @classmethod
    def _require_timezone(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("created_at must include a timezone, e.g. 2026-11-20T08:00:00Z")
        return v.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _size(self) -> "SyncBatch":
        n = len(self.measurements) + len(self.checkins)
        if n == 0:
            raise ValueError("a sync batch must contain at least one measurement or check-in")
        if n > MAX_ITEMS_PER_BATCH:
            raise ValueError(f"a sync batch may contain at most {MAX_ITEMS_PER_BATCH} items")
        return self


class SyncLogEntry(BaseModel):
    batch_id: str
    source_node: str
    status: Literal["APPLIED", "DUPLICATE_BATCH"]
    batch_created_at: datetime
    received_at: datetime
    measurements_accepted: int
    measurements_duplicate: int
    checkins_accepted: int
    checkins_duplicate: int
    alerts: list[str]
    oldest_reading_at: datetime | None
    newest_reading_at: datetime | None
    max_delivery_delay_seconds: int | None  # received_at minus the oldest reading time


class SourceSyncState(BaseModel):
    source_node: str
    last_sync_at: datetime
    last_batch_id: str
    batches_applied: int


class SyncStatusOut(BaseModel):
    generated_at: datetime
    batches_applied: int
    duplicate_batches_ignored: int
    last_sync_at: datetime | None
    sources: list[SourceSyncState]
    note: str = (
        "ASTRA's core loop runs locally. Sync only delivers data that was buffered while "
        "a device or node was offline."
    )
