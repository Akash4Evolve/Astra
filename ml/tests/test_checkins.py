import pytest
from pydantic import ValidationError

from astra_ml.alerts import AlertLevel, analyze
from astra_ml.checkins import CheckIn, checkin_to_measurement
from astra_ml.models import SourceType
from astra_ml.scenarios import generate_checkins

GOOD = {
    "astronaut_id": "AST-001",
    "timestamp_utc": "2026-11-01T20:00:00Z",
    "sleep_hours": 6.5,
    "mood": 4,
    "stress": 2,
    "fatigue": 2,
    "symptoms": ["mild headache"],
}


def mean(xs):
    return sum(xs) / len(xs)


def test_valid_checkin_defaults_to_manual_source():
    c = CheckIn(**GOOD)
    assert c.source_type == SourceType.MANUAL and c.is_simulated is False


@pytest.mark.parametrize(
    "change",
    [
        {"mood": 6},
        {"fatigue": 0},
        {"stress": 1.5},
        {"sleep_hours": 25},
        {"timestamp_utc": "2026-11-01T20:00:00"},  # no timezone
        {"source_type": "SIMULATED"},  # is_simulated stays False
        {"symptoms": [""]},
        {"symptoms": ["x"] * 21},
        {"note": "n" * 501},
    ],
)
def test_invalid_checkins_rejected(change):
    with pytest.raises(ValidationError):
        CheckIn(**{**GOOD, **change})


def test_converter_preserves_provenance():
    c = generate_checkins("stable")[0]
    m = checkin_to_measurement(c)
    assert m.record_id == c.checkin_id and m.parameter == "sleep_hours"
    assert m.is_simulated and m.source_type == SourceType.SIMULATED


def test_missing_data_drops_some_days():
    assert len(generate_checkins("missing_data")) == 18


def test_fatigue_and_mood_move_with_sleep_loss():
    cs = generate_checkins("gradual_deviation")
    early, late = cs[:14], cs[-3:]
    assert mean([c.fatigue for c in late]) > mean([c.fatigue for c in early]) + 1
    assert mean([c.mood for c in late]) < mean([c.mood for c in early])


def test_sleep_decline_alerts_through_the_check_in_pipeline():
    cs = generate_checkins("gradual_deviation")
    alert = analyze([checkin_to_measurement(c) for c in cs]).alert
    assert alert.level == AlertLevel.REVIEW and alert.domain == "behavioural"
    assert "below" in alert.explanation.observed
    ids = alert.explanation.evidence_record_ids
    assert ids[-1] == str(cs[-1].checkin_id)
    assert set(ids) <= {str(c.checkin_id) for c in cs}
