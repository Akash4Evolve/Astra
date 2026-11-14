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
ASTRO = "AST-001"
DASH = f"/api/v1/astronauts/{ASTRO}/dashboard"
TRENDS = f"/api/v1/astronauts/{ASTRO}/trends"
NOW = START + timedelta(days=20, minutes=10)


@pytest.fixture
def client():
    return TestClient(create_app(clock=lambda: NOW, cors_origins=["http://localhost:5173"]))


def hr(scenario):
    return [m.model_dump(mode="json") for m in generate_series("heart_rate", scenario)]


def checkins(scenario):
    return [c.model_dump(mode="json") for c in generate_checkins(scenario)]


def first_alert_id(client):
    return client.get(ALERTS).json()[0]["alert_id"]


# ---------- check-ins ----------
def test_checkin_is_created_and_idempotent(client):  # T-07
    body = checkins("stable")[0]
    first = client.post(CHECKINS, json=body)
    assert first.status_code == 201 and first.json()["duplicate"] is False
    again = client.post(CHECKINS, json=body)
    assert again.status_code == 200 and again.json()["duplicate"] is True


def test_checkin_must_be_self_report_or_simulated(client):
    body = {**checkins("stable")[0], "source_type": "DEVICE", "is_simulated": False}
    r = client.post(CHECKINS, json=body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "HTTP_422"


def test_invalid_checkin_gives_structured_error(client):
    body = {**checkins("stable")[0], "mood": 9}
    r = client.post(CHECKINS, json=body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_sleep_decline_from_check_ins_creates_one_behavioural_alert(client):
    for c in checkins("gradual_deviation"):
        assert client.post(CHECKINS, json=c).status_code == 201
    alerts = client.get(ALERTS).json()
    assert len(alerts) == 1
    assert alerts[0]["domain"] == "behavioural" and alerts[0]["level"] == "REVIEW"


# ---------- actions ----------
def test_action_flow_is_recorded_in_history(client):  # T-08
    client.post(MEAS, json=hr("gradual_deviation"))
    alert_id = first_alert_id(client)
    client.post(f"{ALERTS}/{alert_id}/acknowledge")
    r = client.post(ACTIONS, json={
        "alert_id": alert_id,
        "action_type": "FOLLOW_UP_MEASUREMENT",
        "note": "Repeat resting heart rate tomorrow",
        "follow_up_at": "2026-11-25T08:00:00Z",
    })
    assert r.status_code == 201
    body = r.json()
    assert body["astronaut_id"] == ASTRO and body["outcome"] == "PENDING"
    assert body["timestamp_utc"].startswith("2026-11-21T08:10")  # server time, not client-supplied
    history = client.get(ACTIONS, params={"alert_id": alert_id}).json()
    assert [a["action_id"] for a in history] == [body["action_id"]]


def test_action_validation_and_missing_alert(client):
    client.post(MEAS, json=hr("gradual_deviation"))
    alert_id = first_alert_id(client)
    bad = [
        {"alert_id": alert_id, "action_type": "NOTE"},  # note text required
        {"alert_id": alert_id, "action_type": "FOLLOW_UP_MEASUREMENT"},  # needs follow_up_at
        {"alert_id": alert_id, "action_type": "NOTE", "note": "x", "follow_up_at": "2026-11-25T08:00:00"},
        {"alert_id": alert_id, "action_type": "DIAGNOSE", "note": "x"},
    ]
    for body in bad:
        r = client.post(ACTIONS, json=body)
        assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    missing = client.post(ACTIONS, json={"alert_id": "ALT-NOPE", "action_type": "NOTE", "note": "x"})
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "HTTP_404"


# ---------- dashboard ----------
def test_dashboard_without_data_is_honest_about_coverage(client):
    d = client.get(DASH).json()
    status = {x["domain"]: x["data_status"] for x in d["domains"]}
    assert status["cardiovascular"] == "NO_DATA" and status["behavioural"] == "NO_DATA"
    assert status["radiation"] == "NOT_CONNECTED" and status["cabin_environment"] == "NOT_CONNECTED"
    assert d["devices"] == [] and d["contains_simulated_data"] is False


def test_dashboard_with_drift_shows_flag_then_clears_after_acknowledge(client):
    client.post(MEAS, json=hr("gradual_deviation"))
    d = client.get(DASH).json()
    cardio = next(x for x in d["domains"] if x["domain"] == "cardiovascular")
    assert cardio["data_status"] == "AVAILABLE"
    assert cardio["highest_open_level"] == "REVIEW" and cardio["open_alert_count"] == 1
    assert cardio["indicators"][0]["position_vs_baseline"] == "above_baseline"
    assert d["contains_simulated_data"] is True and len(d["open_alerts"]) == 1
    assert d["devices"][0]["device_id"] == "ASTRA-SIM-001"

    client.post(f"{ALERTS}/{first_alert_id(client)}/acknowledge")
    after = client.get(DASH).json()
    assert after["open_alerts"] == []
    cardio_after = next(x for x in after["domains"] if x["domain"] == "cardiovascular")
    assert cardio_after["highest_open_level"] is None


def test_dashboard_behavioural_domain_uses_check_ins(client):
    for c in checkins("stable"):
        client.post(CHECKINS, json=c)
    d = client.get(DASH).json()
    behav = next(x for x in d["domains"] if x["domain"] == "behavioural")
    assert behav["data_status"] == "AVAILABLE"
    assert {i["parameter"]: i["data_status"] for i in behav["indicators"]} == {
        "sleep_hours": "AVAILABLE", "mood": "AVAILABLE", "stress": "AVAILABLE", "fatigue": "AVAILABLE",
    }


# ---------- trends ----------
def test_trends_return_points_baseline_and_time_window(client):
    client.post(MEAS, json=hr("stable"))
    full = client.get(TRENDS, params={"parameter": "heart_rate"}).json()["series"][0]
    assert full["total_points"] == 21 and full["baseline"]["established"] is True

    windowed = client.get(
        TRENDS, params={"parameter": "heart_rate", "start": "2026-11-15T08:00:00Z"}
    ).json()["series"][0]
    assert windowed["total_points"] == 7
    assert windowed["baseline"]["centre"] == full["baseline"]["centre"]  # not recomputed from the window


def test_trends_are_paginated(client):
    client.post(MEAS, json=hr("stable"))
    page = client.get(TRENDS, params={"parameter": "heart_rate", "limit": 5}).json()["series"][0]
    assert len(page["points"]) == 5 and page["total_points"] == 21
    last = client.get(TRENDS, params={"parameter": "heart_rate", "offset": 20}).json()["series"][0]
    assert len(last["points"]) == 1


def test_trends_for_check_in_scores_have_no_baseline(client):
    for c in checkins("stable"):
        client.post(CHECKINS, json=c)
    s = client.get(TRENDS, params={"parameter": "fatigue"}).json()["series"][0]
    assert s["unit"] == "score 1-5" and len(s["points"]) == 21 and s["baseline"]["established"] is False


def test_trends_reject_bad_requests(client):
    assert client.get(TRENDS, params={"parameter": "blood_pressure"}).status_code == 422
    assert client.get(TRENDS, params={"start": "2026-11-15T08:00:00"}).status_code == 422  # no timezone
    bad_range = {"start": "2026-11-20T08:00:00Z", "end": "2026-11-10T08:00:00Z"}
    assert client.get(TRENDS, params=bad_range).status_code == 422


# ---------- device status ----------
def test_device_connected_then_stale(client):  # T-04
    client.post(MEAS, json=hr("stable"))
    ok = client.get("/api/v1/devices/ASTRA-SIM-001/status").json()
    assert ok["state"] == "CONNECTED" and ok["battery_percent"] is None

    stale_client = TestClient(create_app(clock=lambda: START + timedelta(days=25)))
    stale_client.post(MEAS, json=hr("stable"))
    stale = stale_client.get("/api/v1/devices/ASTRA-SIM-001/status").json()
    assert stale["state"] == "STALE" and stale["seconds_since_last_seen"] > stale["stale_after_seconds"]


def test_device_reports_recent_quality(client):  # T-03
    client.post(MEAS, json=generate_motion())
    status = client.get("/api/v1/devices/ASTRA-SIM-001/status").json()
    assert status["recent_quality"].get("SUSPECT") == 6
    assert status["contains_simulated_data"] is True


def generate_motion():
    return [m.model_dump(mode="json") for m in generate_series("heart_rate", "motion_artifact")]


def test_unknown_device_returns_404(client):
    r = client.get("/api/v1/devices/NOPE/status")
    assert r.status_code == 404 and r.json()["error"]["code"] == "HTTP_404"


# ---------- CORS ----------
def test_cors_allows_only_configured_origins(client):
    ok = client.get(ALERTS, headers={"Origin": "http://localhost:5173"})
    bad = client.get(ALERTS, headers={"Origin": "http://evil.example"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in bad.headers


def test_wildcard_cors_is_rejected():
    with pytest.raises(ValueError):
        create_app(cors_origins=["*"])