"""Batch 8: declared roles and request logging."""
import logging
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from astra_ml.synthetic import generate_heart_rate

NOW = datetime(2026, 11, 30, 12, 0, tzinfo=timezone.utc)
DEVICE, CREW, CMO, GROUND = ({"X-ASTRA-Role": r} for r in ("device", "astronaut", "crew_medical_officer", "ground"))


def readings():
    return [m.model_dump(mode="json") for m in generate_heart_rate("gradual_deviation")]


def alert_id(client):
    client.post("/api/v1/measurements", json=readings(), headers=DEVICE)
    [a] = client.get("/api/v1/alerts").json()
    return a["alert_id"]


@pytest.fixture
def strict():
    return TestClient(create_app(clock=lambda: NOW, cors_origins=["http://localhost:5173"], require_roles=True))


def test_roles_are_optional_by_default_but_recorded():
    client = TestClient(create_app(clock=lambda: NOW, require_roles=False))
    client.post("/api/v1/measurements", json=readings())  # no role: allowed
    aid = client.get("/api/v1/alerts").json()[0]["alert_id"]
    client.post(f"/api/v1/alerts/{aid}/acknowledge", headers=CREW)
    [ack] = client.get("/api/v1/audit", params={"event_type": "ALERT_ACKNOWLEDGED"}).json()
    [ingest] = client.get("/api/v1/audit", params={"event_type": "MEASUREMENTS_INGESTED"}).json()
    assert ack["role"] == "astronaut" and ingest["role"] is None


def test_unknown_role_is_rejected_even_when_not_enforced():
    client = TestClient(create_app(require_roles=False))
    r = client.get("/api/v1/alerts", headers={"X-ASTRA-Role": "admin"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "UNKNOWN_ROLE"


def test_enforced_writes_need_the_right_role(strict):
    r = strict.post("/api/v1/measurements", json=readings())
    assert r.status_code == 403 and r.json()["error"]["code"] == "ROLE_REQUIRED"
    r = strict.post("/api/v1/measurements", json=readings(), headers=CREW)
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN_FOR_ROLE"
    aid = alert_id(strict)
    assert strict.post(f"/api/v1/alerts/{aid}/acknowledge", headers=GROUND).status_code == 403
    assert strict.post(f"/api/v1/alerts/{aid}/acknowledge", headers=DEVICE).status_code == 403
    assert strict.post(f"/api/v1/alerts/{aid}/acknowledge", headers=CMO).status_code == 200
    body = {"alert_id": aid, "action_type": "NOTE", "note": "Rested, will re-measure"}
    assert strict.post("/api/v1/actions", json=body, headers=GROUND).status_code == 403
    assert strict.post("/api/v1/actions", json=body, headers=CREW).status_code == 201


def test_enforced_reads_stay_open_except_the_audit_trail(strict):
    alert_id(strict)
    assert strict.get("/api/v1/alerts").status_code == 200
    assert strict.get("/api/v1/astronauts/AST-001/dashboard").status_code == 200
    assert strict.get("/api/v1/audit").status_code == 403
    assert strict.get("/api/v1/audit", headers=CREW).status_code == 403
    assert strict.get("/api/v1/audit", headers=GROUND).status_code == 200


def test_refusal_still_carries_cors_headers_for_the_browser(strict):
    r = strict.post("/api/v1/actions", json={}, headers={**GROUND, "Origin": "http://localhost:5173"})
    assert r.status_code == 403
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    pre = strict.options("/api/v1/actions", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-astra-role"})
    assert pre.status_code == 200 and "x-astra-role" in pre.headers["access-control-allow-headers"].lower()


def test_every_response_has_a_request_id_and_one_log_line(caplog):
    client = TestClient(create_app(require_roles=False))
    with caplog.at_level(logging.INFO, logger="astra"):
        logging.getLogger("astra").propagate = True  # let caplog see it
        r = client.get("/api/v1/alerts", headers={"X-Request-ID": "demo-123", **GROUND})
        bad = client.get("/api/v1/alerts/ALT-NOPE")
    assert r.headers["X-Request-ID"] == "demo-123" and bad.headers["X-Request-ID"]
    lines = [rec.getMessage() for rec in caplog.records]
    assert any("rid=demo-123 GET /api/v1/alerts -> 200" in s and "role=ground" in s for s in lines)
    assert any("/api/v1/alerts/ALT-NOPE -> 404" in s for s in lines)


def test_logs_never_contain_health_values(caplog):
    client = TestClient(create_app(require_roles=False))
    body = readings()
    with caplog.at_level(logging.INFO, logger="astra"):
        logging.getLogger("astra").propagate = True
        client.post("/api/v1/measurements", json=body, headers=DEVICE)
    text = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "audit MEASUREMENTS_INGESTED" in text
    assert not any(f"{m['value']:.3f}"[:6] in text for m in body)


def test_root_says_what_the_server_is_even_when_roles_are_enforced(strict):
    r = strict.get("/")  # no role header: a browser opening the API URL
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "ASTRA API"
    assert body["version"] == strict.app.version
    assert strict.get(body["docs"]).status_code == 200
    assert strict.get(body["openapi"]).status_code == 200
