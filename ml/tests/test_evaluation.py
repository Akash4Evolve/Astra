import statistics

import pytest

from astra_ml.evaluation import EXPECT_ALERT, by_scenario, evaluate, pooled, render_markdown

N = 40


@pytest.fixture(scope="module")
def stats():
    return evaluate(n_seeds=N)


def test_astra_has_no_false_alarms_without_a_real_deviation(stats):
    assert all(s.astra_alerts == 0 for s in stats if s.scenario not in EXPECT_ALERT)


def test_naive_baseline_raises_false_alarms(stats):
    merged = by_scenario(stats)
    assert merged["stable"].naive2_alerts > 0
    assert merged["single_noise"].naive2_alerts == merged["single_noise"].runs
    assert merged["motion_artifact"].naive3_alerts == merged["motion_artifact"].runs


def test_astra_detects_real_deviations(stats):
    result = pooled(stats)["ASTRA"]
    assert result["detection"] >= 0.8
    assert result["false_alarm"] == 0.0


def test_detection_delay_is_reasonable(stats):
    delays = by_scenario(stats)["gradual_deviation"].delays
    assert delays and 1 <= statistics.median(delays) <= 6


def test_report_states_its_limits(stats):
    report = render_markdown(stats, N, 0)
    assert "not clinical validation" in report and "| stable |" in report


def test_invalid_seed_count_rejected():
    with pytest.raises(ValueError):
        evaluate(n_seeds=0)
