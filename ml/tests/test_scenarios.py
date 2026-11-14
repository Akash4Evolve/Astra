import pytest

from astra_ml.alerts import AlertLevel, analyze
from astra_ml.models import QualityStatus, SourceType
from astra_ml.scenarios import available_scenarios, generate_checkins, generate_series
from astra_ml.synthetic import START

WEARABLE = ["heart_rate", "skin_temperature"]
EXPECTED = {
    "stable": None,
    "gradual_deviation": AlertLevel.REVIEW,
    "single_noise": None,
    "repeated_deviation": AlertLevel.WATCH,
    "missing_data": None,
    "dropout": None,
    "stale_feed": None,
    "motion_artifact": None,
}


def level(records):
    alert = analyze(records).alert
    return alert.level if alert else None


@pytest.mark.parametrize("parameter", WEARABLE)
@pytest.mark.parametrize("scenario", list(EXPECTED))
def test_scenario_alert_outcome(parameter, scenario):
    assert level(generate_series(parameter, scenario)) == EXPECTED[scenario]


@pytest.mark.parametrize("parameter", WEARABLE)
def test_every_record_is_labelled_simulated(parameter):
    for scenario in available_scenarios(parameter):
        data = generate_series(parameter, scenario)
        assert data and all(m.is_simulated and m.source_type == SourceType.SIMULATED for m in data)


def test_same_seed_is_reproducible():
    a = [m.value for m in generate_series("heart_rate", "gradual_deviation", seed=7)]
    b = [m.value for m in generate_series("heart_rate", "gradual_deviation", seed=7)]
    c = [m.value for m in generate_series("heart_rate", "gradual_deviation", seed=8)]
    assert a == b and a != c


def test_dropout_leaves_a_three_day_gap():
    days = {(m.timestamp_utc - START).days for m in generate_series("heart_rate", "dropout")}
    assert len(days) == 18 and {16, 17, 18}.isdisjoint(days)


def test_stale_feed_stops_after_day_15():
    data = generate_series("heart_rate", "stale_feed")
    assert len(data) == 16 and max((m.timestamp_utc - START).days for m in data) == 15


def test_motion_is_flagged_and_the_quality_gate_is_what_prevents_the_alert():
    data = generate_series("heart_rate", "motion_artifact")
    flagged = [m for m in data if m.quality_status == QualityStatus.SUSPECT]
    assert len(flagged) == 6 and all(m.metadata.get("motion_detected") for m in flagged)
    assert analyze(data).alert is None
    ungated = [m.model_copy(update={"quality_status": QualityStatus.VALID}) for m in data]
    assert analyze(ungated).alert is not None  # proves the gate does the work


def test_missing_data_still_establishes_a_baseline():
    result = analyze(generate_series("heart_rate", "missing_data"))
    assert result.baseline.established and result.alert is None


def test_invalid_requests_raise():
    with pytest.raises(ValueError):
        generate_series("blood_pressure")
    with pytest.raises(ValueError):
        generate_series("heart_rate", "nope")
    with pytest.raises(ValueError):
        generate_series("heart_rate", n_days=10)
    with pytest.raises(ValueError):
        generate_series("sleep_hours")  # sleep comes from check-ins
    with pytest.raises(ValueError):
        generate_checkins("motion_artifact")  # device-only scenario
