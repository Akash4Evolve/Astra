from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from astra_ml.alerts import Alert, analyze

from .audit import AuditEvent, AuditEventType
from .store import InMemoryStore


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def evaluate_series(
    store: InMemoryStore,
    astronaut_id: str,
    parameter: str,
    clock: Callable[[], datetime] | None = None,
) -> Alert | None:
    """Re-run analytics for one astronaut+parameter and create/update at most one alert
    per episode. An episode is identified by its first evidence record.
    Creation and level changes are written to the audit trail."""
    now = clock or _utcnow
    candidate = analyze(store.series(astronaut_id, parameter)).alert
    if candidate is None:
        return None

    existing = store.latest_alert(astronaut_id, parameter)
    same_episode = (
        existing is not None
        and existing.explanation.evidence_record_ids[0] == candidate.explanation.evidence_record_ids[0]
    )
    if same_episode:
        if existing.status == "ACKNOWLEDGED":
            return None  # already acknowledged, don't re-raise the same episode
        updated = existing.model_copy(
            update={
                "level": candidate.level,
                "title": candidate.title,
                "explanation": candidate.explanation,
                "next_step": candidate.next_step,
            }
        )
        store.save_alert(updated)
        if updated.level != existing.level:
            store.add_audit(AuditEvent(
                timestamp_utc=now(), event_type=AuditEventType.ALERT_LEVEL_CHANGED, actor="system",
                astronaut_id=astronaut_id, entity_type="alert", entity_id=updated.alert_id,
                details={"from": existing.level.value, "to": updated.level.value,
                         "model": updated.explanation.model,
                         "evidence_record_ids": updated.explanation.evidence_record_ids},
            ))
        return updated

    store.save_alert(candidate)
    store.add_audit(AuditEvent(
        timestamp_utc=now(), event_type=AuditEventType.ALERT_CREATED, actor="system",
        astronaut_id=astronaut_id, entity_type="alert", entity_id=candidate.alert_id,
        details={"parameter": parameter, "level": candidate.level.value,
                 "model": candidate.explanation.model,
                 "evidence_record_ids": candidate.explanation.evidence_record_ids},
    ))
    return candidate
