import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from astra_ml.synthetic import generate_heart_rate

MEAS = "/api/v1/measurements"
ALERTS = "/api/v1/alerts"


@pytest.fixture
def client():
    return TestClient(create_app())


def payload(scenario):
    return [m.model_dump(mode="json") for m in generate_heart_rate(scenario)]


def test_ingest_and_duplicates_not_double_counted(client):  # T-06
    body = payload("stable")[:3]
    assert client.post(MEAS, json=body).json()["accepted"] == 3
    again = client.post(MEAS, json=body).json()
    assert again["accepted"] == 0 and again["duplicates"] == 3


def test_invalid_unit_gives_structured_error(client):  # T-05
    body = payload("stable")[:1]
    body[0]["unit"] = "mmHg"
    r = client.post(MEAS, json=body)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_stable_series_raises_no_alert(client):  # T-01
    client.post(MEAS, json=payload("stable"))
    assert client.get(ALERTS).json() == []


def test_drift_creates_one_explainable_alert_that_can_be_acknowledged(client):  # T-02, T-08
    r = client.post(MEAS, json=payload("gradual_deviation"))
    assert len(r.json()["alerts"]) == 1
    alerts = client.get(ALERTS).json()
    assert len(alerts) == 1 and alerts[0]["level"] == "REVIEW" and alerts[0]["diagnosis"] is None

    ack = client.post(f"{ALERTS}/{alerts[0]['alert_id']}/acknowledge").json()
    assert ack["status"] == "ACKNOWLEDGED" and ack["acknowledged_at"] is not None

    client.post(MEAS, json=payload("gradual_deviation"))  # same data again
    assert len(client.get(ALERTS).json()) == 1


def test_incremental_arrival_updates_one_alert_instead_of_spamming(client):
    for item in payload("gradual_deviation"):  # one reading at a time
        client.post(MEAS, json=[item])
    alerts = client.get(ALERTS).json()
    assert len(alerts) == 1 and alerts[0]["level"] == "REVIEW"


def test_unknown_alert_returns_404_error_shape(client):
    r = client.post(f"{ALERTS}/ALT-NOPE/acknowledge")
    assert r.status_code == 404 and r.json()["error"]["code"] == "HTTP_404"