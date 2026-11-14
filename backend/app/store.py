from threading import RLock
from uuid import UUID

from astra_ml.alerts import Alert
from astra_ml.checkins import CheckIn
from astra_ml.models import Measurement

from .audit import AuditEvent
from .schemas import Action
from .sync import SyncLogEntry


class InMemoryStore:
    """In-memory store: fast, and everything is lost when the process stops.
    Every public method here is the interface a database version must implement;
    SqliteStore (sqlite_store.py) is the persistent one. Choose with ASTRA_DB."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._measurements: dict[UUID, Measurement] = {}
        self._alerts: dict[str, Alert] = {}
        self._checkins: dict[UUID, CheckIn] = {}
        self._actions: dict[str, Action] = {}
        self._audit: list[AuditEvent] = []
        self._sync: dict[str, SyncLogEntry] = {}
        self._duplicate_batches = 0

    # --- measurements ---
    def add_measurements(self, items: list[Measurement]) -> tuple[list[Measurement], int]:
        accepted: list[Measurement] = []
        duplicates = 0
        with self._lock:
            for m in items:
                if m.record_id in self._measurements:
                    duplicates += 1  # idempotent: same record_id is never stored twice
                    continue
                self._measurements[m.record_id] = m
                accepted.append(m)
        return accepted, duplicates

    def series(self, astronaut_id: str, parameter: str) -> list[Measurement]:
        with self._lock:
            return [
                m for m in self._measurements.values()
                if m.astronaut_id == astronaut_id and m.parameter == parameter
            ]

    def device_series(self, device_id: str) -> list[Measurement]:
        with self._lock:
            return [m for m in self._measurements.values() if m.device_id == device_id]

    def device_ids(self, astronaut_id: str) -> list[str]:
        with self._lock:
            return sorted(
                {m.device_id for m in self._measurements.values()
                 if m.astronaut_id == astronaut_id and m.device_id}
            )

    # --- check-ins ---
    def add_checkin(self, checkin: CheckIn) -> bool:
        """Returns False if this checkin_id already exists (idempotent)."""
        with self._lock:
            if checkin.checkin_id in self._checkins:
                return False
            self._checkins[checkin.checkin_id] = checkin
            return True

    def checkins(self, astronaut_id: str) -> list[CheckIn]:
        with self._lock:
            return [c for c in self._checkins.values() if c.astronaut_id == astronaut_id]

    # --- alerts ---
    def list_alerts(self, status: str | None = None, astronaut_id: str | None = None) -> list[Alert]:
        with self._lock:
            found = [
                a for a in self._alerts.values()
                if (status is None or a.status == status)
                and (astronaut_id is None or a.astronaut_id == astronaut_id)
            ]
        return sorted(found, key=lambda a: a.created_at, reverse=True)

    def get_alert(self, alert_id: str) -> Alert | None:
        with self._lock:
            return self._alerts.get(alert_id)

    def latest_alert(self, astronaut_id: str, parameter: str) -> Alert | None:
        matches = [a for a in self.list_alerts(astronaut_id=astronaut_id) if a.parameter == parameter]
        return matches[0] if matches else None

    def save_alert(self, alert: Alert) -> None:
        with self._lock:
            self._alerts[alert.alert_id] = alert

    # --- actions (append-only) ---
    def add_action(self, action: Action) -> None:
        with self._lock:
            self._actions[action.action_id] = action

    def list_actions(self, alert_id: str | None = None, astronaut_id: str | None = None) -> list[Action]:
        with self._lock:
            found = [
                a for a in self._actions.values()
                if (alert_id is None or a.alert_id == alert_id)
                and (astronaut_id is None or a.astronaut_id == astronaut_id)
            ]
        return sorted(found, key=lambda a: a.timestamp_utc, reverse=True)

    # --- audit trail (append-only, never edited) ---
    def add_audit(self, event: AuditEvent) -> None:
        with self._lock:
            self._audit.append(event)

    def list_audit(
        self,
        astronaut_id: str | None = None,
        event_type: str | None = None,
        entity_id: str | None = None,
    ) -> list[AuditEvent]:
        with self._lock:
            found = [
                e for e in self._audit
                if (astronaut_id is None or e.astronaut_id == astronaut_id)
                and (event_type is None or e.event_type.value == event_type)
                and (entity_id is None or e.entity_id == entity_id)
            ]
        return list(reversed(found))  # newest first, insertion order kept for equal timestamps

    # --- sync log ---
    def get_sync(self, batch_id: str) -> SyncLogEntry | None:
        with self._lock:
            return self._sync.get(batch_id)

    def add_sync(self, entry: SyncLogEntry) -> None:
        with self._lock:
            self._sync[entry.batch_id] = entry

    def count_duplicate_batch(self) -> None:
        with self._lock:
            self._duplicate_batches += 1

    def list_sync(self, source_node: str | None = None) -> list[SyncLogEntry]:
        with self._lock:
            found = [e for e in self._sync.values() if source_node is None or e.source_node == source_node]
        return list(reversed(found))  # newest first, by arrival order (dicts keep insertion order)

    def duplicate_batches(self) -> int:
        with self._lock:
            return self._duplicate_batches
