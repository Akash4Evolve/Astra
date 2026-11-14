"""Batch 6: CrewBand simulator drives the real API end to end (in-process, no server needed)."""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from app.main import create_app  # noqa: E402
from crewband_sim import build_days, run  # noqa: E402


class TestApi:
    """Same interface as crewband_sim.HttpApi, but calls the app in-process."""

    __test__ = False  # not a pytest test class

    def __init__(self, client: TestClient) -> None:
        self.c = client

    def post(self, path, body):
        r = self.c.post("/api/v1" + path, json=body)
        return r.status_code, r.json()

    def get(self, path, params=None):
        r = self.c.get("/api/v1" + path, params=params)
        return r.status_code, r.json()


@pytest.fixture
def api():
    return TestApi(TestClient(create_app(cors_origins=[])))


def quiet(_):
    pass


def test_days_are_simulated_shifted_to_now_and_complete():
    now = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
    days = build_days(now=now)
    assert len(days) == 21
    records = [m for p in days for m in p.measurements]
    assert all(m["source_type"] == "SIMULATED" and m["is_simulated"] for m in records)
    assert {m["parameter"] for m in records} == {"heart_rate", "skin_temperature"}
    last = max(datetime.fromisoformat(m["timestamp_utc"].replace("Z", "+00:00")) for m in records)
    assert last <= now and (now - last).total_seconds() == 12 * 3600
    assert sum(len(p.checkins) for p in days) == 21


def test_live_stream_of_drift_raises_one_review_alert(api):
    res = run(api, build_days(), log=quiet, sleep=lambda s: None)
    assert res.sent_live == 21 * 2 + 21 and len(res.alerts) == 1
    _, alerts = api.get("/alerts")
    assert len(alerts) == 1 and alerts[0]["level"] == "REVIEW" and alerts[0]["domain"] == "cardiovascular"
    _, device = api.get("/devices/CREWBAND-SIM-001/status")
    assert device["state"] == "CONNECTED" and device["contains_simulated_data"] is True


def test_offline_days_arrive_through_one_sync_batch(api):
    days = build_days()
    res = run(api, days, offline_from=16, log=quiet, sleep=lambda s: None)
    assert res.sync_entry["status"] == "APPLIED"
    assert res.sent_synced == 5 * 2 + 5 and res.sent_live == 16 * 2 + 16
    assert res.sync_entry["alerts"] and res.alerts == res.sync_entry["alerts"]
    assert res.sync_entry["max_delivery_delay_seconds"] > 4 * 24 * 3600
    _, status = api.get("/sync/status")
    assert status["batches_applied"] == 1


def test_stable_stream_raises_nothing(api):
    res = run(api, build_days("stable"), log=quiet, sleep=lambda s: None)
    assert res.alerts == []
    _, twin = api.get("/astronauts/AST-001/twin")
    assert twin["attention_needed"] is False


def test_rerunning_the_same_days_only_creates_duplicates(api):
    days = build_days()
    run(api, days, log=quiet, sleep=lambda s: None)
    again = run(api, days, log=quiet, sleep=lambda s: None)
    assert again.sent_live == 0
    _, alerts = api.get("/alerts")
    assert len(alerts) == 1
