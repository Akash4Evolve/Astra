"""Append-only audit trail (FR-15).

Every state change (ingest, check-in, alert created/updated/acknowledged, action, sync)
is written here. Events are never edited or deleted.

`actor` is the channel the change came through, NOT a verified person: there is no
authentication yet, so we do not claim to know who did it. `role` is the role the client
declared in X-ASTRA-Role (see roles.py), also unverified, or null if none was sent.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class AuditEventType(str, Enum):
    MEASUREMENTS_INGESTED = "MEASUREMENTS_INGESTED"
    CHECKIN_RECORDED = "CHECKIN_RECORDED"
    ALERT_CREATED = "ALERT_CREATED"
    ALERT_LEVEL_CHANGED = "ALERT_LEVEL_CHANGED"
    ALERT_ACKNOWLEDGED = "ALERT_ACKNOWLEDGED"
    ACTION_RECORDED = "ACTION_RECORDED"
    SYNC_APPLIED = "SYNC_APPLIED"
    SYNC_DUPLICATE_IGNORED = "SYNC_DUPLICATE_IGNORED"
    PPG_QUALITY_ASSESSED = "PPG_QUALITY_ASSESSED"  # experimental gate; stores nothing else


Actor = Literal["api_client", "system", "sync"]


class AuditEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: f"EVT-{uuid4().hex[:10].upper()}")
    timestamp_utc: datetime  # server time
    event_type: AuditEventType
    actor: Actor
    astronaut_id: str | None = None
    role: str | None = None  # declared, not authenticated
    entity_type: str
    entity_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
