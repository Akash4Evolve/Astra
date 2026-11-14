import pytest
from pydantic import ValidationError

from astra_ml.models import Measurement

GOOD = {
    "astronaut_id": "AST-001",
    "device_id": "ASTRA-SIM-001",
    "timestamp_utc": "2026-11-01T10:30:00Z",
    "parameter": "heart_rate",
    "value": 82.0,
    "unit": "bpm",
    "source_type": "SIMULATED",
    "quality_status": "VALID",
    "is_simulated": True,
}


def test_spec_example_parses():
    m = Measurement(**GOOD)
    assert m.timestamp_utc.tzinfo is not None


@pytest.mark.parametrize(
    "change",
    [
        {"unit": "mmHg"},
        {"timestamp_utc": "2026-11-01T10:30:00"},  # no timezone
        {"is_simulated": False},  # SIMULATED source but flag false
        {"parameter": "blood_pressure"},
        {"value": 900.0},
        {"value": float("nan")},
    ],
)
def test_invalid_payloads_rejected(change):
    with pytest.raises(ValidationError):
        Measurement(**{**GOOD, **change})