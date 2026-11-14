from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from .baseline import MODEL_VERSION, Baseline, BaselineResult, compute_baseline, robust_z
from .models import Measurement, QualityStatus

RULE_VERSION = "persistence_v1"
LABELS = {"heart_rate": "Resting heart-rate", "skin_temperature": "Skin-temperature", "sleep_hours": "Sleep-duration"}
DOMAINS = {"heart_rate": "cardiovascular", "skin_temperature": "physiological", "sleep_hours": "behavioural"}


class AlertLevel(str, Enum):
    INFO = "INFO"
    WATCH = "WATCH"
    REVIEW = "REVIEW"
    # MISSION ESCALATION is deliberately absent: it is reserved for an
    # authorised mission protocol and we must not invent criteria (spec 9.4).


@dataclass(frozen=True)
class RuleConfig:
    z_threshold: float = 3.0  # demo assumption, configurable, NOT a clinical limit
    watch_persistence: int = 2
    review_persistence: int = 3
    baseline_days: int = 14
    min_baseline_samples: int = 10


class AlertExplanation(BaseModel):
    observed: str
    comparison_window: str
    data_quality: str
    evidence_record_ids: list[str]
    model: str
    baseline_centre: float
    baseline_dispersion: float
    latest_robust_z: float
    persistence_count: int
    z_threshold: float


class Alert(BaseModel):
    alert_id: str = Field(default_factory=lambda: f"ALT-{uuid4().hex[:8].upper()}")
    astronaut_id: str
    parameter: str
    domain: str
    level: AlertLevel
    title: str
    created_at: datetime
    status: Literal["OPEN", "ACKNOWLEDGED"] = "OPEN"
    acknowledged_at: datetime | None = None
    explanation: AlertExplanation
    next_step: str
    diagnosis: None = None  # always null: ASTRA never diagnoses


@dataclass(frozen=True)
class AnalysisResult:
    baseline: BaselineResult
    alert: Alert | None


def evaluate(
    measurements: list[Measurement],
    baseline: Baseline,
    config: RuleConfig = RuleConfig(),
    now: datetime | None = None,
) -> Alert | None:
    after = sorted(
        {
            m.record_id: m
            for m in measurements
            if m.astronaut_id == baseline.astronaut_id
            and m.parameter == baseline.parameter
            and m.timestamp_utc > baseline.window_end
        }.values(),
        key=lambda m: m.timestamp_utc,
    )

    # Walk back from the newest reading: count consecutive valid readings that
    # deviate in the same direction. Any non-valid or in-band reading ends the run,
    # so noisy/stale data can never build up into a confident alert.
    run: list[tuple[Measurement, float]] = []
    sign = 0
    for m in reversed(after):
        if m.quality_status != QualityStatus.VALID:
            break
        z = robust_z(m.value, baseline)
        if abs(z) <= config.z_threshold:
            break
        s = 1 if z > 0 else -1
        if sign and s != sign:
            break
        sign = s
        run.append((m, z))
    run.reverse()

    n = len(run)
    if n < config.watch_persistence:
        return None
    level = AlertLevel.REVIEW if n >= config.review_persistence else AlertLevel.WATCH

    excluded = sum(1 for m in after if m.quality_status != QualityStatus.VALID)
    direction = "above" if sign > 0 else "below"
    label = LABELS.get(baseline.parameter, baseline.parameter)
    if level == AlertLevel.REVIEW:
        next_step = (
            "Repeat the measurement under the approved measurement conditions and "
            "follow the applicable onboard medical protocol."
        )
    else:
        next_step = (
            "Keep observing; repeat the measurement under the approved measurement "
            "conditions if the difference continues."
        )

    return Alert(
        astronaut_id=baseline.astronaut_id,
        parameter=baseline.parameter,
        domain=DOMAINS.get(baseline.parameter, "general"),
        level=level,
        title=f"{label} trend differs from personal baseline",
        created_at=now or datetime.now(timezone.utc),
        explanation=AlertExplanation(
            observed=(
                f"{n} consecutive readings {direction} the personal baseline band "
                f"(|robust z| > {config.z_threshold})"
            ),
            comparison_window=(
                f"baseline {baseline.window_start.date()} to {baseline.window_end.date()} "
                f"({baseline.sample_count} valid samples)"
            ),
            data_quality="VALID" if excluded == 0 else f"VALID_WITH_{excluded}_EXCLUDED_READINGS",
            evidence_record_ids=[str(m.record_id) for m, _ in run],
            model=f"{MODEL_VERSION}+{RULE_VERSION}",
            baseline_centre=baseline.centre,
            baseline_dispersion=baseline.dispersion,
            latest_robust_z=run[-1][1],
            persistence_count=n,
            z_threshold=config.z_threshold,
        ),
        next_step=next_step,
    )


def analyze(
    measurements: list[Measurement],
    config: RuleConfig = RuleConfig(),
    now: datetime | None = None,
) -> AnalysisResult:
    """Baseline from the first `baseline_days`, then evaluate everything after it.
    Input must be one astronaut and one parameter. Order does not matter."""
    if not measurements:
        return AnalysisResult(compute_baseline([]), None)
    start = min(m.timestamp_utc for m in measurements)
    cutoff = start + timedelta(days=config.baseline_days)
    result = compute_baseline(
        [m for m in measurements if m.timestamp_utc < cutoff], config.min_baseline_samples
    )
    if not result.established:
        return AnalysisResult(result, None)
    return AnalysisResult(result, evaluate(measurements, result.baseline, config, now))
