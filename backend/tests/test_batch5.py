"""Batch 5: audit trail (FR-15), delayed/offline sync (FR-13, T-09, T-10), Digital Twin (FR-10, T-12)."""
import random
import socket
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from astra_ml.scenarios import generate_checkins, generate_series
from astra_ml.synthetic import START

MEAS = "/api/v1/measurements"
ALERTS = "/api/v1/alerts"
ACTIONS = "/api/v1/actions"
CHECKINS = "/api/v1/check-ins"
AUDIT = "/api/v1/audit"
SYNC = "/api/v1/sync"
ASTRO = "AST-001"
TWIN = f"/api/v1/astronauts/{ASTRO}/twin"
NOW = START + timedelta(days=20, minutes=10)


@pytest.fixture
def client():
    return TestClient(create_app(clock=lambda: NOW, cors_origins=[]))


def hr(scenario):
    return [m.model_dump(mode="json") for m in generate_series("heart_rate", scenario)]


def checkins(scenario):
    return [c.model_dump(mode="json") for c in generate_checkins(scenario)]


def events(client, **params):
    return client.get(AUDIT, params=params).json()


def batch(batch_id, measurements=(), cis=(), created_at="2026-11-21T07:00:00Z"):
    return {"batch_id": batch_id, "source_node": "CREWBAND-GW-01", "created_at": created_at,
            "measurements": list(measurements), "checkins": list(cis)}


def domain(twin, key):
    return next(d for d in twin["domains"] if d["domain"] == key)


# ======================= audit trail =======================
def test_full_flow_is_audited_in_order(client):
    client.post(MEAS, json=hr("gradual_deviation"))
    alert_id = client.get(ALERTS).json()[0]["alert_id"]
    client.post(f"{ALERTS}/{alert_id}/acknowledge")
    client.post(ACTIONS, json={"alert_id": alert_id, "action_type": "NOTE", "note": "Rested, will re-measure"})

    types = [e["event_type"] for e in reversed(events(client))]  # oldest first
    assert types == ["MEASUREMENTS_INGESTED", "ALERT_CREATED", "ALERT_ACKNOWLEDGED", "ACTION_RECORDED"]

    created = events(client, event_type="ALERT_CREATED")[0]
    assert created["actor"] == "system" and created["entity_id"] == alert_id
    assert len(created["details"]["evidence_record_ids"]) == 3
    assert created["details"]["model"] == "robust_baseline_v2+persistence_v1"


def test_acknowledging_twice_is_logged_once(client):
    client.post(MEAS, json=hr("gradual_deviation"))
    alert_id = client.get(ALERTS).json()[0]["alert_id"]
    client.post(f"{ALERTS}/{alert_id}/acknowledge")
    client.post(f"{ALERTS}/{alert_id}/acknowledge")
    assert len(events(client, event_type="ALERT_ACKNOWLEDGED")) == 1


def test_incremental_arrival_logs_creation_once_and_each_level_change(client):
    for item in hr("gradual_deviation"):
        client.post(MEAS, json=[item])
    assert len(events(client, event_type="ALERT_CREATED")) == 1
    changes = events(client, event_type="ALERT_LEVEL_CHANGED")
    assert [(c["details"]["from"], c["details"]["to"]) for c in changes] == [("WATCH", "REVIEW")]


def test_duplicates_are_visible_in_the_audit(client):
    body = hr("stable")[:3]
    client.post(MEAS, json=body)
    client.post(MEAS, json=body)
    latest = events(client, event_type="MEASUREMENTS_INGESTED")[0]
    assert latest["details"] == {"accepted": 0, "duplicates": 3}


def test_audit_filters_and_rejects_unknown_type(client):
    client.post(MEAS, json=hr("gradual_deviation"))
    alert_id = client.get(ALERTS).json()[0]["alert_id"]
    assert {e["entity_id"] for e in events(client, entity_id=alert_id)} == {alert_id}
    assert events(client, astronaut_id="AST-999") == []
    assert client.get(AUDIT, params={"event_type": "DELETED_EVERYTHING"}).status_code == 422


# ======================= delayed / offline sync =======================
def test_delayed_shuffled_batch_gives_same_alert_as_live_data(client):  # T-10
    data = hr("gradual_deviation")
    live = TestClient(create_app(clock=lambda: NOW, cors_origins=[]))
    live.post(MEAS, json=data)
    expected = live.get(ALERTS).json()[0]

    client.post(MEAS, json=data[:14])  # online part of the mission
    late = data[14:]
    random.Random(1).shuffle(late)  # buffered offline, arrives out of order
    r = client.post(SYNC, json=batch("B-001", late))
    assert r.status_code == 201
    entry = r.json()
    assert entry["status"] == "APPLIED" and entry["measurements_accepted"] == 7 and len(entry["alerts"]) == 1

    got = client.get(ALERTS).json()[0]
    assert got["level"] == expected["level"] == "REVIEW"
    assert got["explanation"]["evidence_record_ids"] == expected["explanation"]["evidence_record_ids"]


def test_resent_batch_is_applied_once(client):  # T-10
    data = hr("stable")
    first = client.post(SYNC, json=batch("B-002", data))
    again = client.post(SYNC, json=batch("B-002", data))
    assert first.status_code == 201 and again.status_code == 200
    assert again.json()["status"] == "DUPLICATE_BATCH"
    assert again.json()["measurements_accepted"] == first.json()["measurements_accepted"] == 21
    trend = client.get(f"/api/v1/astronauts/{ASTRO}/trends", params={"parameter": "heart_rate"}).json()
    assert trend["series"][0]["total_points"] == 21
    assert len(events(client, event_type="SYNC_DUPLICATE_IGNORED")) == 1


def test_overlapping_batches_never_double_count(client):
    data = hr("stable")
    client.post(SYNC, json=batch("B-003", data[:15]))
    r = client.post(SYNC, json=batch("B-004", data[10:])).json()  # days 10-14 sent twice
    assert r["measurements_accepted"] == 6 and r["measurements_duplicate"] == 5


def test_sync_reports_delivery_delay(client):
    r = client.post(SYNC, json=batch("B-005", hr("stable")[15:])).json()
    assert r["oldest_reading_at"].startswith("2026-11-16")
    assert r["max_delivery_delay_seconds"] == int(timedelta(days=5, minutes=10).total_seconds())


def test_sync_carries_check_ins_and_raises_behavioural_alert(client):
    r = client.post(SYNC, json=batch("B-006", cis=checkins("gradual_deviation"))).json()
    assert r["checkins_accepted"] == 21 and len(r["alerts"]) == 1
    assert client.get(ALERTS).json()[0]["domain"] == "behavioural"


@pytest.mark.parametrize("body", [
    batch("B-007"),                                                        # empty
    {**batch("B-008", hr("stable")[:1]), "created_at": "2026-11-21T07:00:00"},  # no timezone
    {**batch("B-009", hr("stable")[:1]), "batch_id": ""},
])
def test_invalid_batches_rejected(client, body):
    r = client.post(SYNC, json=body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_sync_rejects_device_sourced_check_ins(client):
    bad = {**checkins("stable")[0], "source_type": "DEVICE", "is_simulated": False}
    r = client.post(SYNC, json=batch("B-010", cis=[bad]))
    assert r.status_code == 422
    assert client.get("/api/v1/sync/log").json() == []  # nothing half-applied


def test_sync_status_and_log(client):
    data = hr("stable")
    client.post(SYNC, json=batch("B-011", data[:7]))
    client.post(SYNC, json=batch("B-012", data[7:]))
    client.post(SYNC, json=batch("B-012", data[7:]))
    status = client.get("/api/v1/sync/status").json()
    assert status["batches_applied"] == 2 and status["duplicate_batches_ignored"] == 1
    assert status["sources"][0]["source_node"] == "CREWBAND-GW-01"
    assert status["sources"][0]["batches_applied"] == 2 and status["sources"][0]["last_batch_id"] == "B-012"
    assert [e["batch_id"] for e in client.get("/api/v1/sync/log").json()] == ["B-012", "B-011"]


LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def test_core_loop_runs_with_no_network(client, monkeypatch):  # T-09
    """Blocks every connection that leaves this machine. Loopback stays allowed,
    because Windows' asyncio uses a local socket pair internally."""
    real_connect = socket.socket.connect
    real_create = socket.create_connection

    def guarded_connect(sock, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if host not in LOOPBACK:
            raise OSError(f"external network disabled for this test: {host}")
        return real_connect(sock, address, *args, **kwargs)

    def guarded_create(address, *args, **kwargs):
        if address[0] not in LOOPBACK:
            raise OSError(f"external network disabled for this test: {address[0]}")
        return real_create(address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "create_connection", guarded_create)
    with pytest.raises(OSError):  # proves the block is active
        socket.create_connection(("example.com", 80), timeout=1)

    client.post(MEAS, json=hr("gradual_deviation"))
    alert_id = client.get(ALERTS).json()[0]["alert_id"]
    assert client.post(f"{ALERTS}/{alert_id}/acknowledge").status_code == 200
    assert client.post(ACTIONS, json={"alert_id": alert_id, "action_type": "NOTE", "note": "ok"}).status_code == 201
    assert client.get(TWIN).status_code == 200


# ======================= digital twin =======================
def test_twin_without_data_is_honest(client):
    t = client.get(TWIN).json()
    assert domain(t, "cardiovascular")["state"] == "NO_DATA"
    assert domain(t, "radiation")["state"] == "NOT_CONNECTED"
    assert t["attention_needed"] is False and t["data_through"] is None
    assert "does not diagnose" in t["notice"]


def test_twin_changes_before_and_after_new_data(client):  # T-12
    data = hr("gradual_deviation")
    client.post(MEAS, json=data[:15])
    before = client.get(TWIN).json()
    assert domain(before, "cardiovascular")["state"] == "WITHIN_PERSONAL_BASELINE"
    assert before["attention_needed"] is False

    client.post(MEAS, json=data[15:])
    after = client.get(TWIN).json()
    cardio = domain(after, "cardiovascular")
    assert cardio["state"] == "CHANGE_FROM_BASELINE" and cardio["highest_open_level"] == "REVIEW"
    assert after["attention_needed"] is True
    assert after["twin_version"] != before["twin_version"]
    assert after["data_through"] > before["data_through"]


def test_twin_version_is_stable_without_changes(client):
    client.post(MEAS, json=hr("stable"))
    assert client.get(TWIN).json()["twin_version"] == client.get(TWIN).json()["twin_version"]


def test_acknowledged_change_stays_visible(client):
    client.post(MEAS, json=hr("gradual_deviation"))
    alert_id = client.get(ALERTS).json()[0]["alert_id"]
    client.post(f"{ALERTS}/{alert_id}/acknowledge")
    t = client.get(TWIN).json()
    assert domain(t, "cardiovascular")["state"] == "CHANGE_ACKNOWLEDGED"
    assert t["attention_needed"] is False


def test_overdue_follow_up_needs_attention(client):
    client.post(MEAS, json=hr("gradual_deviation"))
    alert_id = client.get(ALERTS).json()[0]["alert_id"]
    client.post(f"{ALERTS}/{alert_id}/acknowledge")
    client.post(ACTIONS, json={"alert_id": alert_id, "action_type": "FOLLOW_UP_MEASUREMENT",
                               "follow_up_at": "2026-11-21T07:00:00Z"})  # before NOW
    t = client.get(TWIN).json()
    assert t["pending_follow_ups"][0]["overdue"] is True and t["attention_needed"] is True


def test_twin_building_baseline_and_low_quality(client):
    client.post(MEAS, json=hr("stable")[:5])
    assert domain(client.get(TWIN).json(), "cardiovascular")["state"] == "BUILDING_BASELINE"

    other = TestClient(create_app(clock=lambda: NOW, cors_origins=[]))
    other.post(MEAS, json=[m.model_dump(mode="json") for m in generate_series("heart_rate", "motion_artifact")])
    cardio = domain(other.get(TWIN).json(), "cardiovascular")
    assert cardio["state"] == "LOW_QUALITY_DATA" and cardio["open_alert_ids"] == []


def test_twin_completeness_freshness_and_self_report(client):
    client.post(MEAS, json=hr("stable"))
    for c in checkins("stable"):
        client.post(CHECKINS, json=c)
    t = client.get(TWIN).json()
    cardio, behav = domain(t, "cardiovascular"), domain(t, "behavioural")
    assert cardio["completeness_7d"] == 1.0 and cardio["freshness"] == "FRESH"
    assert set(behav["self_report_7d"]) == {"mood", "stress", "fatigue"}
    assert t["contains_simulated_data"] is True

    later = TestClient(create_app(clock=lambda: NOW + timedelta(days=5), cors_origins=[]))
    later.post(MEAS, json=hr("stable"))
    assert domain(later.get(TWIN).json(), "cardiovascular")["freshness"] == "STALE"


def test_dropout_lowers_completeness(client):
    client.post(MEAS, json=[m.model_dump(mode="json") for m in generate_series("heart_rate", "dropout")])
    assert domain(client.get(TWIN).json(), "cardiovascular")["completeness_7d"] < 1.0