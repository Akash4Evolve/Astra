from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from astra_ml.alerts import RuleConfig, analyze
from astra_ml.baseline import BaselineResult, robust_z
from astra_ml.models import PARAMETERS, QualityStatus

from .schemas import (
    AlertSummary, BaselineOut, DashboardOut, DeviceStatusOut, DomainOut, IndicatorOut,
    LatestValue, TrendPoint, TrendSeries, TrendsOut,
)
from .store import InMemoryStore

SCORE_PARAMETERS = ("mood", "stress", "fatigue")
SCORE_UNIT = "score 1-5"
SUPPORTED_PARAMETERS = tuple(PARAMETERS) + SCORE_PARAMETERS
LABELS = {
    "heart_rate": "Resting heart rate",
    "skin_temperature": "Skin temperature",
    "sleep_hours": "Sleep duration",
    "mood": "Mood",
    "stress": "Stress",
    "fatigue": "Fatigue",
}

# (domain key, label, parameters). Keys match the alert domains in astra_ml.alerts.
MEASURED_DOMAINS = (
    ("cardiovascular", "Cardiovascular", ("heart_rate",)),
    ("physiological", "Skin temperature", ("skin_temperature",)),
    ("behavioural", "Sleep and self-report", ("sleep_hours", "mood", "stress", "fatigue")),
)
# Domains with no source in this system. Shown honestly, never filled with made-up values.
NOT_CONNECTED_DOMAINS = (
    ("musculoskeletal", "Bone and muscle", "Not measured: needs clinical instruments, not a wrist wearable."),
    ("immune", "Immune function", "Not measured: needs laboratory results."),
    ("radiation", "Radiation exposure", "Not measured by CrewBand: needs a dedicated dosimeter."),
    ("cabin_environment", "Cabin environment", "Not connected: needs spacecraft environmental telemetry."),
)
LEVEL_ORDER = {"WATCH": 1, "REVIEW": 2}
NOTICE = (
    "ASTRA shows changes against a personal baseline. It does not diagnose. "
    "Values marked simulated are demo data."
)


def _baseline_out(result: BaselineResult) -> BaselineOut:
    b = result.baseline
    return BaselineOut(
        established=result.established,
        reason=result.reason,
        centre=b.centre if b else None,
        dispersion=b.dispersion if b else None,
        window_start=b.window_start if b else None,
        window_end=b.window_end if b else None,
        sample_count=b.sample_count if b else None,
        model_version=b.model_version if b else None,
    )


def _has_data(store: InMemoryStore, astronaut_id: str, parameter: str) -> bool:
    if parameter in SCORE_PARAMETERS:
        return bool(store.checkins(astronaut_id))
    return bool(store.series(astronaut_id, parameter))


def _series_for(store: InMemoryStore, astronaut_id: str, parameter: str):
    if parameter in SCORE_PARAMETERS:
        items = sorted(store.checkins(astronaut_id), key=lambda c: c.timestamp_utc)
        points = [
            TrendPoint(
                record_id=str(c.checkin_id),
                timestamp_utc=c.timestamp_utc,
                value=float(getattr(c, parameter)),
                quality_status="VALID",
                is_simulated=c.is_simulated,
            )
            for c in items
        ]
        baseline = BaselineOut(
            established=False,
            reason="scores use a 1-5 scale and are shown without a statistical baseline",
        )
        return SCORE_UNIT, points, baseline

    series = sorted(store.series(astronaut_id, parameter), key=lambda m: m.timestamp_utc)
    points = [
        TrendPoint(
            record_id=str(m.record_id),
            timestamp_utc=m.timestamp_utc,
            value=m.value,
            quality_status=m.quality_status.value,
            is_simulated=m.is_simulated,
        )
        for m in series
    ]
    # Baseline is computed from the full series, never from the requested time window.
    return PARAMETERS[parameter][0], points, _baseline_out(analyze(series).baseline)


def build_trends(
    store: InMemoryStore,
    astronaut_id: str,
    parameters: list[str] | None,
    start: datetime | None,
    end: datetime | None,
    limit: int,
    offset: int,
) -> TrendsOut:
    chosen = parameters or [p for p in SUPPORTED_PARAMETERS if _has_data(store, astronaut_id, p)]
    out: list[TrendSeries] = []
    for parameter in chosen:
        unit, points, baseline = _series_for(store, astronaut_id, parameter)
        points = [
            p for p in points
            if (start is None or p.timestamp_utc >= start) and (end is None or p.timestamp_utc <= end)
        ]
        out.append(
            TrendSeries(
                parameter=parameter,
                unit=unit,
                points=points[offset : offset + limit],
                total_points=len(points),
                limit=limit,
                offset=offset,
                baseline=baseline,
            )
        )
    return TrendsOut(astronaut_id=astronaut_id, start=start, end=end, series=out)


def _indicator(store: InMemoryStore, astronaut_id: str, parameter: str, config: RuleConfig) -> IndicatorOut:
    label = LABELS[parameter]
    if parameter in SCORE_PARAMETERS:
        items = sorted(store.checkins(astronaut_id), key=lambda c: c.timestamp_utc)
        if not items:
            return IndicatorOut(parameter=parameter, label=label, unit=SCORE_UNIT, data_status="NO_DATA")
        c = items[-1]
        return IndicatorOut(
            parameter=parameter,
            label=label,
            unit=SCORE_UNIT,
            data_status="AVAILABLE",
            latest=LatestValue(
                value=float(getattr(c, parameter)),
                unit=SCORE_UNIT,
                timestamp_utc=c.timestamp_utc,
                quality_status="VALID",
                source_type=c.source_type.value,
                is_simulated=c.is_simulated,
            ),
            position_vs_baseline="not_baselined",
        )

    unit = PARAMETERS[parameter][0]
    series = store.series(astronaut_id, parameter)
    if not series:
        return IndicatorOut(parameter=parameter, label=label, unit=unit, data_status="NO_DATA")

    result = analyze(series)
    latest = max(series, key=lambda m: m.timestamp_utc)
    baseline = result.baseline.baseline
    z = None
    if baseline is None:
        status, position = "INSUFFICIENT_DATA", "baseline_not_established"
    else:
        status = "AVAILABLE"
        if latest.quality_status != QualityStatus.VALID:
            position = "low_quality_reading"
        else:
            z = robust_z(latest.value, baseline)
            position = (
                "above_baseline" if z > config.z_threshold
                else "below_baseline" if z < -config.z_threshold
                else "within_baseline_band"
            )
    return IndicatorOut(
        parameter=parameter,
        label=label,
        unit=unit,
        data_status=status,
        latest=LatestValue(
            value=latest.value,
            unit=unit,
            timestamp_utc=latest.timestamp_utc,
            quality_status=latest.quality_status.value,
            source_type=latest.source_type.value,
            is_simulated=latest.is_simulated,
        ),
        position_vs_baseline=position,
        robust_z=z,
    )


def build_device_status(
    store: InMemoryStore, device_id: str, now: datetime, stale_after: timedelta
) -> DeviceStatusOut | None:
    series = store.device_series(device_id)
    if not series:
        return None
    last_seen = max(m.received_at for m in series)
    last_reading = max(m.timestamp_utc for m in series)
    recent = sorted(series, key=lambda m: m.timestamp_utc)[-20:]
    age = (now - last_seen).total_seconds()
    return DeviceStatusOut(
        device_id=device_id,
        state="STALE" if age > stale_after.total_seconds() else "CONNECTED",
        last_seen_at=last_seen,
        last_reading_at=last_reading,
        seconds_since_last_seen=int(age),
        stale_after_seconds=int(stale_after.total_seconds()),
        recent_quality=dict(Counter(m.quality_status.value for m in recent)),
        source_types=sorted({m.source_type.value for m in series}),
        contains_simulated_data=any(m.is_simulated for m in series),
    )


def build_dashboard(
    store: InMemoryStore, astronaut_id: str, now: datetime, stale_after: timedelta
) -> DashboardOut:
    config = RuleConfig()
    open_alerts = store.list_alerts(status="OPEN", astronaut_id=astronaut_id)
    domains: list[DomainOut] = []
    sources: set[str] = set()
    simulated = False

    for key, label, parameters in MEASURED_DOMAINS:
        indicators = [_indicator(store, astronaut_id, p, config) for p in parameters]
        statuses = {i.data_status for i in indicators}
        if "AVAILABLE" in statuses:
            status = "AVAILABLE"
        elif "INSUFFICIENT_DATA" in statuses:
            status = "INSUFFICIENT_DATA"
        else:
            status = "NO_DATA"
        flagged = [a for a in open_alerts if a.domain == key]
        highest = max(
            (a.level.value for a in flagged), key=lambda lv: LEVEL_ORDER.get(lv, 0), default=None
        )
        domains.append(
            DomainOut(
                domain=key,
                label=label,
                data_status=status,
                indicators=indicators,
                open_alert_count=len(flagged),
                highest_open_level=highest,
            )
        )
        for i in indicators:
            if i.latest:
                sources.add(i.latest.source_type)
                simulated = simulated or i.latest.is_simulated

    for key, label, note in NOT_CONNECTED_DOMAINS:
        domains.append(DomainOut(domain=key, label=label, data_status="NOT_CONNECTED", note=note))

    devices = [
        d for d in (build_device_status(store, did, now, stale_after) for did in store.device_ids(astronaut_id))
        if d is not None
    ]
    return DashboardOut(
        astronaut_id=astronaut_id,
        generated_at=now,
        domains=domains,
        open_alerts=[
            AlertSummary(
                alert_id=a.alert_id, level=a.level.value, title=a.title,
                domain=a.domain, created_at=a.created_at, status=a.status,
            )
            for a in open_alerts
        ],
        devices=devices,
        data_sources=sorted(sources),
        contains_simulated_data=simulated,
        notice=NOTICE,
    )