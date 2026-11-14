"""Batch 7: experimental window-level PPG quality gate."""
import numpy as np
import pytest
from fastapi.testclient import TestClient
from joblib import dump
from sklearn.ensemble import RandomForestClassifier

from app.experimental import DEFAULT_MODEL
from app.main import create_app
from astra_ml.ppg_quality import COMMON_FEATURES, FEATURES

URL = "/api/v1/experimental/ppg-quality"
FS_PPG, FS_ACC, SECONDS = 64.0, 32.0, 10.0
rng = np.random.default_rng(0)
t = np.arange(int(FS_PPG * SECONDS)) / FS_PPG
ta = np.arange(int(FS_ACC * SECONDS)) / FS_ACC


def still_acc():
    return np.column_stack([0.01 * rng.normal(size=ta.size), 0.01 * rng.normal(size=ta.size),
                            1 + 0.01 * rng.normal(size=ta.size)])


def running_acc():
    step = np.sin(2 * np.pi * 2.6 * ta)
    return np.column_stack([0.6 * step, 0.3 * step, 1 + 0.8 * step])


def window(kind="clean", **extra):
    if kind == "clean":
        ppg, acc = np.sin(2 * np.pi * 1.2 * t) + 0.05 * rng.normal(size=t.size), still_acc()
    else:  # pulse swamped by arm motion at the step rate
        ppg = 0.3 * np.sin(2 * np.pi * 1.2 * t) + 1.5 * np.sin(2 * np.pi * 2.6 * t) + 0.4 * rng.normal(size=t.size)
        acc = running_acc()
    body = {"ppg": ppg.tolist(), "ppg_fs": FS_PPG, "acc_g": acc.tolist(), "acc_fs": FS_ACC}
    body.update(extra)
    return body


def stub_bundle(path, features=COMMON_FEATURES):
    """Tiny stand-in for the trained model: still + clean pulse -> reliable, motion-locked -> unreliable."""
    n = 40
    rows = {
        "acc_std": np.r_[np.full(n, 0.01), np.full(n, 0.5)],
        "ppg_peak_ratio": np.r_[np.full(n, 0.9), np.full(n, 0.85)],
        "ppg_skew": np.zeros(2 * n),
        "ppg_kurtosis": np.full(2 * n, -1.4),
        "ppg_vs_motion_bpm": np.r_[np.full(n, 130.0), np.zeros(n)],
        "gyro_std": np.zeros(2 * n),
        "ppg_channel_disagree_bpm": np.zeros(2 * n),
    }
    X = np.column_stack([rows[f] + rng.normal(0, 0.01, 2 * n) for f in features])
    y = np.r_[np.zeros(n), np.ones(n)].astype(int)
    model = RandomForestClassifier(n_estimators=20, random_state=0).fit(X, y)
    dump({"model": model, "features": tuple(features), "datasets": ["stub"], "ppg_channel": "pleth_3",
          "error_bpm": 10.0, "window_s": SECONDS}, path)
    return path


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(ppg_model_path=stub_bundle(tmp_path / "gate.joblib")))


def test_model_info_describes_the_loaded_model(client):
    info = client.get(URL).json()
    assert info["loaded"] and info["experimental"]
    assert info["features"] == list(COMMON_FEATURES)
    assert info["window_seconds"] == SECONDS and "10 bpm" in info["unreliable_means"]


def test_clean_window_is_reliable_and_motion_window_is_flagged(client):
    good = client.post(URL, json=window("clean")).json()
    assert good["verdict"] == "LIKELY_RELIABLE" and good["suggested_quality_status"] == "VALID"
    assert 65 < good["ppg_hr_bpm"] < 80  # 1.2 Hz pulse = 72 bpm
    bad = client.post(URL, json=window("motion")).json()
    assert bad["verdict"] == "LIKELY_UNRELIABLE" and bad["suggested_quality_status"] == "SUSPECT"
    assert bad["p_unreliable"] >= bad["threshold"]
    assert good["experimental"] is True and "EXPERIMENTAL" in good["notice"]


def test_gate_never_touches_measurements_or_alerts(client):
    client.post(URL, json=window("motion", astronaut_id="AST-001"))
    assert client.get("/api/v1/alerts").json() == []
    assert client.get("/api/v1/astronauts/AST-001/trends").json()["series"] == []


def test_assessment_is_audited_only_when_tied_to_an_astronaut(client):
    client.post(URL, json=window("clean"))
    assert client.get("/api/v1/audit", params={"event_type": "PPG_QUALITY_ASSESSED"}).json() == []
    client.post(URL, json=window("motion", astronaut_id="AST-001", device_id="CREWBAND-1",
                                 window_start_utc="2026-11-14T08:00:00Z"))
    [event] = client.get("/api/v1/audit", params={"event_type": "PPG_QUALITY_ASSESSED"}).json()
    assert event["astronaut_id"] == "AST-001" and event["entity_id"] == "CREWBAND-1"
    assert event["details"]["verdict"] == "LIKELY_UNRELIABLE"


def test_flat_signal_cannot_be_assessed(client):
    body = window("clean")
    body["ppg"] = [0.5] * len(body["ppg"])
    r = client.post(URL, json=body).json()
    assert r["verdict"] == "CANNOT_ASSESS" and r["p_unreliable"] is None
    assert r["suggested_quality_status"] == "SUSPECT"


@pytest.mark.parametrize("change, message", [
    ({"ppg_fs": 32.0}, "ppg covers 20.00 s"),                 # wrong length for the rate
    ({"acc_fs": 64.0}, "acc_g covers 5.00 s"),
    ({"ppg": [0.1] * 100, "ppg_fs": 10.0}, "below the 20 Hz minimum"),
])
def test_windows_that_do_not_match_the_model_are_rejected(client, change, message):
    r = client.post(URL, json=window("clean", **change))
    assert r.status_code == 422 and message in r.json()["error"]["message"]


def test_malformed_payload_gives_structured_validation_error(client):
    body = window("clean")
    body["acc_g"] = [[0.0, 1.0]] * len(body["acc_g"])
    r = client.post(URL, json=body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    r = client.post(URL, json=window("clean", window_start_utc="2026-11-14T08:00:00"))
    assert r.status_code == 422


def test_missing_model_disables_only_this_endpoint(tmp_path):
    client = TestClient(create_app(ppg_model_path=tmp_path / "nope.joblib"))
    info = client.get(URL).json()
    assert info["loaded"] is False and "not found" in info["problem"]
    r = client.post(URL, json=window("clean"))
    assert r.status_code == 503 and "unavailable" in r.json()["error"]["message"]
    assert client.get("/api/v1/alerts").status_code == 200


def test_finger_only_model_is_refused_for_wrist_windows(tmp_path):
    client = TestClient(create_app(ppg_model_path=stub_bundle(tmp_path / "finger.joblib", FEATURES)))
    info = client.get(URL).json()
    assert info["loaded"] is False and "gyro_std" in info["problem"]


@pytest.mark.skipif(not DEFAULT_MODEL.exists(), reason="trained model not present (models/ is not committed)")
def test_trained_combined_model_separates_clean_from_motion():
    client = TestClient(create_app(ppg_model_path=DEFAULT_MODEL))
    good = client.post(URL, json=window("clean")).json()
    bad = client.post(URL, json=window("motion")).json()
    assert good["verdict"] == "LIKELY_RELIABLE"
    assert bad["p_unreliable"] > good["p_unreliable"]
