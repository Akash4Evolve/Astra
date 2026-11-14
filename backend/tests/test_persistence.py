"""Batch 9: SQLite persistence behind the store interface."""
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.audit import AuditEvent, AuditEventType
from app.main import create_app
from app.sqlite_store import SCHEMA_VERSION, SqliteStore
from app.store import InMemoryStore
from astra_ml.synthetic import generate_heart_rate

NOW = datetime(2026, 11, 30, 12, 0, tzinfo=timezone.utc)
CREW = {"X-ASTRA-Role": "astronaut"}


def readings(scenario="gradual_deviation"):
    return [m.model_dump(mode="json") for m in generate_heart_rate(scenario)]


def app_on(path, now=NOW):
    return TestClient(create_app(store=SqliteStore(path), clock=lambda: now, cors_origins=[]))


def test_everything_survives_a_restart(tmp_path):
    db = tmp_path / "astra.db"
    a = app_on(db)
    data = readings()
    a.post("/api/v1/measurements", json=data[:-1])
    [alert] = a.get("/api/v1/alerts").json()
    a.post(f"/api/v1/alerts/{alert['alert_id']}/acknowledge", headers=CREW)
    a.post("/api/v1/actions", headers=CREW, json={
        "alert_id": alert["alert_id"], "action_type": "FOLLOW_UP_MEASUREMENT",
        "note": "Repeat after sleep", "follow_up_at": "2026-12-01T08:00:00Z"})
    batch = {"batch_id": "B-1", "source_node": "GW-1", "created_at": "2026-11-30T10:00:00Z",
             "measurements": data[-1:], "checkins": []}
    a.post("/api/v1/sync", json=batch)
    a.post("/api/v1/sync", json=batch)  # duplicate batch
    before = {p: a.get(p).json() for p in ("/api/v1/alerts", "/api/v1/actions", "/api/v1/audit",
                                           "/api/v1/sync/status", "/api/v1/astronauts/AST-001/twin",
                                           "/api/v1/astronauts/AST-001/trends")}

    b = app_on(db)  # a new process would see the same file
    after = {p: b.get(p).json() for p in before}
    assert after == before
    assert after["/api/v1/sync/status"]["duplicate_batches_ignored"] == 1
    assert after["/api/v1/alerts"][0]["status"] == "ACKNOWLEDGED"

    again = b.post("/api/v1/measurements", json=data).json()  # retries after a restart stay idempotent
    assert again == {"accepted": 0, "duplicates": len(data), "alerts": []}


def test_an_alert_episode_continues_across_a_restart(tmp_path):
    db = tmp_path / "astra.db"
    data = readings()
    a = app_on(db)
    a.post("/api/v1/measurements", json=data[:-1])
    [first] = a.get("/api/v1/alerts").json()

    b = app_on(db)
    b.post("/api/v1/measurements", json=data[-1:])
    [same] = b.get("/api/v1/alerts").json()  # updated, not a second alert
    assert same["alert_id"] == first["alert_id"]
    assert same["explanation"]["persistence_count"] > first["explanation"]["persistence_count"]


def test_database_refuses_to_edit_or_delete_the_audit_trail(tmp_path):
    db = tmp_path / "astra.db"
    store = SqliteStore(db)
    store.add_audit(AuditEvent(timestamp_utc=NOW, event_type=AuditEventType.SYNC_APPLIED, actor="sync",
                               entity_type="sync_batch", entity_id="B-1"))
    raw = sqlite3.connect(db)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        raw.execute("UPDATE audit SET event_type = 'X'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        raw.execute("DELETE FROM audit")
    raw.close()
    assert len(store.list_audit()) == 1


def test_a_newer_database_is_not_opened(tmp_path):
    db = tmp_path / "astra.db"
    SqliteStore(db).close()
    raw = sqlite3.connect(db)
    raw.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    raw.close()
    with pytest.raises(RuntimeError, match="schema version"):
        SqliteStore(db)


def _same_story(store):
    """Drive one store through the API and return everything it can list, in order."""
    c = TestClient(create_app(store=store, clock=lambda: NOW, cors_origins=[]))
    for scenario, aid in (("gradual_deviation", "AST-001"), ("gradual_deviation", "AST-002")):
        body = [dict(m, astronaut_id=aid) for m in readings(scenario)]
        c.post("/api/v1/measurements", json=body)
    for a in c.get("/api/v1/alerts").json():
        c.post("/api/v1/actions", headers=CREW, json={"alert_id": a["alert_id"], "action_type": "PROTOCOL_FOLLOWED"})
    return {
        "alerts": [(a.astronaut_id, a.parameter, a.level) for a in store.list_alerts()],
        "series": [(m.timestamp_utc, m.value) for m in store.series("AST-002", "heart_rate")],  # IDs are random per run
        "actions": [(a.astronaut_id, a.action_type) for a in store.list_actions()],
        "audit": [(e.event_type, e.astronaut_id) for e in store.list_audit()],
        "devices": store.device_ids("AST-001"),
    }


def test_sqlite_lists_things_in_the_same_order_as_memory():
    # Both alerts share created_at (fixed clock), so this also checks tie order.
    mem, sql = _same_story(InMemoryStore()), _same_story(SqliteStore(":memory:"))
    assert len(mem["alerts"]) == 2
    assert mem == sql


def test_concurrent_writes_are_all_kept(tmp_path):
    store = SqliteStore(tmp_path / "astra.db")
    client = TestClient(create_app(store=store, clock=lambda: NOW, cors_origins=[]))
    errors: list[Exception] = []

    def worker(aid):
        try:
            body = [dict(m, astronaut_id=aid) for m in readings("stable")]
            assert client.post("/api/v1/measurements", json=body).status_code == 200
        except Exception as e:  # pragma: no cover - reported below
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(f"AST-{i:03d}",)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert sum(len(store.series(f"AST-{i:03d}", "heart_rate")) for i in range(8)) == 8 * len(readings("stable"))


def test_astra_db_environment_variable_selects_sqlite(tmp_path, monkeypatch):
    db = tmp_path / "env.db"
    monkeypatch.setenv("ASTRA_DB", str(db))
    TestClient(create_app(clock=lambda: NOW, cors_origins=[])).post("/api/v1/measurements", json=readings("stable"))
    assert db.exists()
    assert len(SqliteStore(db).series("AST-001", "heart_rate")) == len(readings("stable"))
    monkeypatch.delenv("ASTRA_DB")
    fresh = TestClient(create_app(clock=lambda: NOW + timedelta(days=1), cors_origins=[]))
    assert fresh.get("/api/v1/astronauts/AST-001/trends").json()["series"] == []  # in-memory again
