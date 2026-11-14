from astra_ml.alerts import AlertLevel, analyze
from astra_ml.models import QualityStatus
from astra_ml.synthetic import BASELINE_DAYS, generate_heart_rate


def test_stable_gives_no_alert():
    assert analyze(generate_heart_rate("stable")).alert is None


def test_single_noise_gives_no_alert():
    assert analyze(generate_heart_rate("single_noise")).alert is None


def test_gradual_drift_gives_explainable_review():
    data = generate_heart_rate("gradual_deviation")
    alert = analyze(data).alert
    assert alert.level == AlertLevel.REVIEW
    assert alert.diagnosis is None
    assert alert.explanation.evidence_record_ids == [str(m.record_id) for m in data[-3:]]
    assert alert.explanation.model == "robust_baseline_v2+persistence_v1"


def test_shorter_drift_is_only_watch():
    data = generate_heart_rate("gradual_deviation")[: BASELINE_DAYS + 6]
    assert analyze(data).alert.level == AlertLevel.WATCH


def test_low_quality_readings_never_alert():
    data = generate_heart_rate("gradual_deviation")
    degraded = [
        m.model_copy(update={"quality_status": QualityStatus.SUSPECT}) if i >= BASELINE_DAYS else m
        for i, m in enumerate(data)
    ]
    assert analyze(degraded).alert is None


def test_no_alert_without_established_baseline():
    result = analyze(generate_heart_rate("gradual_deviation")[:8])
    assert not result.baseline.established and result.alert is None


def test_order_of_arrival_does_not_matter():
    data = generate_heart_rate("gradual_deviation")
    a, b = analyze(data).alert, analyze(list(reversed(data))).alert
    assert a.level == b.level
    assert a.explanation.evidence_record_ids == b.explanation.evidence_record_ids