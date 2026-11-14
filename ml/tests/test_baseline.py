import pytest

from astra_ml.baseline import compute_baseline, robust_z
from astra_ml.models import QualityStatus
from astra_ml.sources import SimulatorSource
from astra_ml.synthetic import BASELINE_DAYS, generate_heart_rate


def split(scenario):
    data = generate_heart_rate(scenario)
    return data[:BASELINE_DAYS], data[BASELINE_DAYS:]


def post_z(scenario):
    train, test = split(scenario)
    result = compute_baseline(train)
    assert result.established
    return [robust_z(m.value, result.baseline) for m in test]


def test_stable_series_has_no_large_deviation():
    assert all(abs(z) < 3 for z in post_z("stable"))


def test_gradual_drift_is_sustained():
    assert all(z > 3 for z in post_z("gradual_deviation")[-3:])


def test_single_noise_is_isolated():
    assert sum(abs(z) > 3 for z in post_z("single_noise")) == 1


def test_insufficient_history_gives_no_baseline():
    train, _ = split("stable")
    result = compute_baseline(train[:5])
    assert not result.established and result.baseline is None


def test_suspect_readings_are_excluded():
    train, _ = split("stable")
    degraded = [m.model_copy(update={"quality_status": QualityStatus.SUSPECT}) if i < 6 else m
                for i, m in enumerate(train)]
    assert not compute_baseline(degraded).established  # only 8 valid left


def test_duplicates_not_double_counted():
    train, _ = split("stable")
    result = compute_baseline(train + train)
    assert result.baseline.sample_count == BASELINE_DAYS


def test_mixed_parameters_rejected():
    train, _ = split("stable")
    mixed = train[:-1] + [train[-1].model_copy(update={"parameter": "skin_temperature"})]
    with pytest.raises(ValueError):
        compute_baseline(mixed)


def test_simulator_source_labels_everything_simulated():
    batch = SimulatorSource("stable").read_batch()
    assert batch and all(m.is_simulated for m in batch)