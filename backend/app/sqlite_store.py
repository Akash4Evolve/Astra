"""SQLite store (batch 9): the same interface as InMemoryStore, kept on disk.

Each record is stored whole as JSON (the pydantic model), next to the few columns used
for filtering and ordering. Results come back in exactly the order InMemoryStore gives:
`seq` is the order a record was first stored, and an update keeps its `seq`, just as
updating a Python dict keeps the key's position. Alert episodes and the audit trail
depend on that order.

Standard library only (sqlite3). One connection shared by the API's worker threads,
guarded by a lock; WAL journal so a crash never leaves a half-written file.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

from astra_ml.alerts import Alert
from astra_ml.checkins import CheckIn
from astra_ml.models import Measurement

from .audit import AuditEvent
from .schemas import Action
from .sync import SyncLogEntry

SCHEMA_VERSION = 1
SCHEMA = """
CREATE TABLE IF NOT EXISTS measurements (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id TEXT NOT NULL UNIQUE,
    astronaut_id TEXT NOT NULL,
    parameter TEXT NOT NULL,
    device_id TEXT,
    body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_measurements_series ON measurements (astronaut_id, parameter);
CREATE INDEX IF NOT EXISTS ix_measurements_device ON measurements (device_id);

CREATE TABLE IF NOT EXISTS checkins (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    checkin_id TEXT NOT NULL UNIQUE,
    astronaut_id TEXT NOT NULL,
    body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_checkins_astronaut ON checkins (astronaut_id);

CREATE TABLE IF NOT EXISTS alerts (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id TEXT NOT NULL UNIQUE,
    astronaut_id TEXT NOT NULL,
    parameter TEXT NOT NULL,
    status TEXT NOT NULL,
    created_us INTEGER NOT NULL,
    body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_alerts_astronaut ON alerts (astronaut_id, parameter);

CREATE TABLE IF NOT EXISTS actions (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id TEXT NOT NULL UNIQUE,
    alert_id TEXT NOT NULL,
    astronaut_id TEXT NOT NULL,
    timestamp_us INTEGER NOT NULL,
    body TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    astronaut_id TEXT,
    event_type TEXT NOT NULL,
    entity_id TEXT,
    body TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_log (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT NOT NULL UNIQUE,
    source_node TEXT NOT NULL,
    body TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS counters (
    name TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);

-- The audit trail is append-only: the database refuses edits and deletes.
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
BEGIN SELECT RAISE(ABORT, 'audit trail is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
BEGIN SELECT RAISE(ABORT, 'audit trail is append-only'); END;
CREATE TRIGGER IF NOT EXISTS actions_no_update BEFORE UPDATE ON actions
BEGIN SELECT RAISE(ABORT, 'actions are append-only'); END;
CREATE TRIGGER IF NOT EXISTS actions_no_delete BEFORE DELETE ON actions
BEGIN SELECT RAISE(ABORT, 'actions are append-only'); END;
"""


def _us(dt: datetime) -> int:
    """Microseconds since the epoch, for exact ordering of timezone-aware datetimes."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = dt - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


class SqliteStore:
    """Persistent store. `path` is a file, or ":memory:" for a throwaway database."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        with self._lock:
            version = self._db.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"{self.path} has schema version {version}; this ASTRA understands up to {SCHEMA_VERSION}"
                )
            if self.path != ":memory:":
                self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=NORMAL")
            self._db.executescript(SCHEMA)
            self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # --- helpers ---
    def _rows(self, sql: str, args: tuple = ()) -> list[str]:
        with self._lock:
            return [r[0] for r in self._db.execute(sql, args).fetchall()]

    def _write(self, fn):
        """Run fn(cursor) in one transaction."""
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                out = fn(self._db)
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            self._db.execute("COMMIT")
            return out

    # --- measurements ---
    def add_measurements(self, items: list[Measurement]) -> tuple[list[Measurement], int]:
        def run(db):
            accepted: list[Measurement] = []
            duplicates = 0
            for m in items:
                cur = db.execute(
                    "INSERT OR IGNORE INTO measurements (record_id, astronaut_id, parameter, device_id, body) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (str(m.record_id), m.astronaut_id, m.parameter, m.device_id, m.model_dump_json()),
                )
                if cur.rowcount:
                    accepted.append(m)
                else:
                    duplicates += 1  # idempotent: same record_id is never stored twice
            return accepted, duplicates
        return self._write(run)

    def series(self, astronaut_id: str, parameter: str) -> list[Measurement]:
        return [Measurement.model_validate_json(b) for b in self._rows(
            "SELECT body FROM measurements WHERE astronaut_id = ? AND parameter = ? ORDER BY seq",
            (astronaut_id, parameter))]

    def device_series(self, device_id: str) -> list[Measurement]:
        return [Measurement.model_validate_json(b) for b in self._rows(
            "SELECT body FROM measurements WHERE device_id = ? ORDER BY seq", (device_id,))]

    def device_ids(self, astronaut_id: str) -> list[str]:
        return self._rows(
            "SELECT DISTINCT device_id FROM measurements WHERE astronaut_id = ? AND device_id IS NOT NULL "
            "AND device_id != '' ORDER BY device_id", (astronaut_id,))

    # --- check-ins ---
    def add_checkin(self, checkin: CheckIn) -> bool:
        """Returns False if this checkin_id already exists (idempotent)."""
        return self._write(lambda db: db.execute(
            "INSERT OR IGNORE INTO checkins (checkin_id, astronaut_id, body) VALUES (?, ?, ?)",
            (str(checkin.checkin_id), checkin.astronaut_id, checkin.model_dump_json()),
        ).rowcount == 1)

    def checkins(self, astronaut_id: str) -> list[CheckIn]:
        return [CheckIn.model_validate_json(b) for b in self._rows(
            "SELECT body FROM checkins WHERE astronaut_id = ? ORDER BY seq", (astronaut_id,))]

    # --- alerts ---
    def list_alerts(self, status: str | None = None, astronaut_id: str | None = None) -> list[Alert]:
        sql, args = "SELECT body FROM alerts WHERE 1=1", []
        if status is not None:
            sql += " AND status = ?"
            args.append(status)
        if astronaut_id is not None:
            sql += " AND astronaut_id = ?"
            args.append(astronaut_id)
        # Newest first; ties keep the order alerts were first stored (as Python's stable sort does).
        sql += " ORDER BY created_us DESC, seq ASC"
        return [Alert.model_validate_json(b) for b in self._rows(sql, tuple(args))]

    def get_alert(self, alert_id: str) -> Alert | None:
        rows = self._rows("SELECT body FROM alerts WHERE alert_id = ?", (alert_id,))
        return Alert.model_validate_json(rows[0]) if rows else None

    def latest_alert(self, astronaut_id: str, parameter: str) -> Alert | None:
        matches = [a for a in self.list_alerts(astronaut_id=astronaut_id) if a.parameter == parameter]
        return matches[0] if matches else None

    def save_alert(self, alert: Alert) -> None:
        self._write(lambda db: db.execute(
            "INSERT INTO alerts (alert_id, astronaut_id, parameter, status, created_us, body) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(alert_id) DO UPDATE SET astronaut_id = excluded.astronaut_id, "
            "parameter = excluded.parameter, status = excluded.status, "
            "created_us = excluded.created_us, body = excluded.body",
            (alert.alert_id, alert.astronaut_id, alert.parameter, alert.status, _us(alert.created_at),
             alert.model_dump_json()),
        ))

    # --- actions (append-only) ---
    def add_action(self, action: Action) -> None:
        self._write(lambda db: db.execute(
            "INSERT INTO actions (action_id, alert_id, astronaut_id, timestamp_us, body) VALUES (?, ?, ?, ?, ?)",
            (action.action_id, action.alert_id, action.astronaut_id, _us(action.timestamp_utc),
             action.model_dump_json()),
        ))

    def list_actions(self, alert_id: str | None = None, astronaut_id: str | None = None) -> list[Action]:
        sql, args = "SELECT body FROM actions WHERE 1=1", []
        if alert_id is not None:
            sql += " AND alert_id = ?"
            args.append(alert_id)
        if astronaut_id is not None:
            sql += " AND astronaut_id = ?"
            args.append(astronaut_id)
        sql += " ORDER BY timestamp_us DESC, seq ASC"
        return [Action.model_validate_json(b) for b in self._rows(sql, tuple(args))]

    # --- audit trail (append-only, never edited) ---
    def add_audit(self, event: AuditEvent) -> None:
        self._write(lambda db: db.execute(
            "INSERT INTO audit (astronaut_id, event_type, entity_id, body) VALUES (?, ?, ?, ?)",
            (event.astronaut_id, event.event_type.value, event.entity_id, event.model_dump_json()),
        ))

    def list_audit(
        self,
        astronaut_id: str | None = None,
        event_type: str | None = None,
        entity_id: str | None = None,
    ) -> list[AuditEvent]:
        sql, args = "SELECT body FROM audit WHERE 1=1", []
        for col, val in (("astronaut_id", astronaut_id), ("event_type", event_type), ("entity_id", entity_id)):
            if val is not None:
                sql += f" AND {col} = ?"
                args.append(val)
        sql += " ORDER BY seq DESC"  # newest first
        return [AuditEvent.model_validate_json(b) for b in self._rows(sql, tuple(args))]

    # --- sync log ---
    def get_sync(self, batch_id: str) -> SyncLogEntry | None:
        rows = self._rows("SELECT body FROM sync_log WHERE batch_id = ?", (batch_id,))
        return SyncLogEntry.model_validate_json(rows[0]) if rows else None

    def add_sync(self, entry: SyncLogEntry) -> None:
        self._write(lambda db: db.execute(
            "INSERT INTO sync_log (batch_id, source_node, body) VALUES (?, ?, ?) "
            "ON CONFLICT(batch_id) DO UPDATE SET source_node = excluded.source_node, body = excluded.body",
            (entry.batch_id, entry.source_node, entry.model_dump_json()),
        ))

    def count_duplicate_batch(self) -> None:
        self._write(lambda db: db.execute(
            "INSERT INTO counters (name, value) VALUES ('duplicate_batches', 1) "
            "ON CONFLICT(name) DO UPDATE SET value = value + 1"))

    def list_sync(self, source_node: str | None = None) -> list[SyncLogEntry]:
        if source_node is None:
            rows = self._rows("SELECT body FROM sync_log ORDER BY seq DESC")
        else:
            rows = self._rows("SELECT body FROM sync_log WHERE source_node = ? ORDER BY seq DESC", (source_node,))
        return [SyncLogEntry.model_validate_json(b) for b in rows]

    def duplicate_batches(self) -> int:
        rows = self._rows("SELECT value FROM counters WHERE name = 'duplicate_batches'")
        return int(rows[0]) if rows else 0
