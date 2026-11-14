"""Bounded Digital Health Twin summary (FR-10, T-12).

"Bounded" means: the twin is a structured, per-domain summary of what the data shows
against the astronaut's OWN baseline, plus open alerts and pending follow-ups.
It does not simulate physiology, predict outcomes or diagnose anything.
Domains without a data source stay NOT_CONNECTED and are never filled in.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from statistics import fmean
from typing import Literal

from pydantic import BaseModel

from astra_ml.alerts import RuleConfig, analyze
from astra_ml.models import QualityStatus

from .store import InMemoryStore
from .views import LABELS, LEVEL_ORDER, MEASURED_DOMAINS, NOT_CONNECTED_DOMAINS, SCORE_PARAMETERS, _indicator

TWIN_MODEL = "bounded_twin_v1"
COMPLETENESS_DAYS = 7

TwinState = Literal[
    "CHANGE_FROM_BASELINE",   # an OPEN alert exists in this domain
    "CHANGE_ACKNOWLEDGED",    # alert acknowledged, but the difference is still present
    "WITHIN_PERSONAL_BASELINE",
    "LOW_QUALITY_DATA",       # latest reading flagged, not used for alerts
    "BUILDING_BASELINE",      # data exists but not enough for a personal baseline yet
    "NO_DATA",
    "NOT_CONNECTED",          # no source exists for this domain in ASTRA
]


class TwinDomain(BaseModel):
    domain: str
    label: str
    state: TwinState
    summary: str
    last_data_at: datetime | None = None
    freshness: Literal["FRESH", "STALE"] | None = None
    completeness_7d: float | None = None  # share of the last 7 days with >= 1 valid reading
    open_alert_ids: list[str] = []
    highest_open_level: str | None = None
    self_report_7d: dict[str, float] | None = None  # mean 1-5 scores, behavioural domain only


class PendingFollowUp(BaseModel):
    action_id: str
    alert_id: str
    follow_up_at: datetime
    overdue: bool


class TwinOut(BaseModel):
    astronaut_id: str
    generated_at: datetime
    model: str = TWIN_MODEL
    twin_version: str  # changes whenever data, alerts or actions change
    data_through: datetime | None
    attention_needed: bool  # True if any domain has an OPEN alert or a follow-up is overdue
    domains: list[TwinDomain]
    pending_follow_ups: list[PendingFollowUp]
    contains_simulated_data: bool
    notice: str = (
        "Bounded summary against this astronaut's own baseline. It does not diagnose, "
        "predict or simulate physiology. Values marked simulated are demo data."
    )


def _readings(store: InMemoryStore, astronaut_id: str, parameter: str) -> list:
    return store.series(astronaut_id, parameter)


def _completeness(readings: list, data_through: datetime) -> float:
    start = data_through - timedelta(days=COMPLETENESS_DAYS)
    days = {
        m.timestamp_utc.date()
        for m in readings
        if m.quality_status == QualityStatus.VALID and start < m.timestamp_utc <= data_through
    }
    return round(min(len(days), COMPLETENESS_DAYS) / COMPLETENESS_DAYS, 2)


def _version(store: InMemoryStore, astronaut_id: str, params: list[str]) -> str:
    parts: list[str] = []
    for p in params:
        parts += sorted(str(m.record_id) for m in _readings(store, astronaut_id, p))
    parts += sorted(str(c.checkin_id) for c in store.checkins(astronaut_id))
    parts += sorted(f"{a.alert_id}:{a.status}:{a.level.value}" for a in store.list_alerts(astronaut_id=astronaut_id))
    parts += sorted(a.action_id for a in store.list_actions(astronaut_id=astronaut_id))
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:12]


def build_twin(
    store: InMemoryStore,
    astronaut_id: str,
    now: datetime,
    fresh_within: timedelta = timedelta(hours=36),
) -> TwinOut:
    config = RuleConfig()
    alerts = store.list_alerts(astronaut_id=astronaut_id)
    measured_params = [p for _, _, ps in MEASURED_DOMAINS for p in ps if p not in SCORE_PARAMETERS]

    all_readings = [m for p in measured_params for m in _readings(store, astronaut_id, p)]
    data_through = max((m.timestamp_utc for m in all_readings), default=None)
    simulated = any(m.is_simulated for m in all_readings)

    domains: list[TwinDomain] = []
    for key, label, params in MEASURED_DOMAINS:
        base_params = [p for p in params if p not in SCORE_PARAMETERS]
        readings = [m for p in base_params for m in _readings(store, astronaut_id, p)]
        open_alerts = [a for a in alerts if a.domain == key and a.status == "OPEN"]
        acked = [a for a in alerts if a.domain == key and a.status == "ACKNOWLEDGED"]
        highest = max((a.level.value for a in open_alerts), key=lambda lv: LEVEL_ORDER.get(lv, 0), default=None)

        if not readings:
            domains.append(TwinDomain(domain=key, label=label, state="NO_DATA", summary="No data received yet."))
            continue

        indicators = [_indicator(store, astronaut_id, p, config) for p in base_params]
        latest = max(readings, key=lambda m: m.timestamp_utc)
        last_seen = max(m.received_at for m in readings)
        still_deviating = any(analyze(_readings(store, astronaut_id, p)).alert is not None for p in base_params)
        names = ", ".join(LABELS[p].lower() for p in base_params)

        if open_alerts:
            state = "CHANGE_FROM_BASELINE"
            summary = (f"{open_alerts[0].explanation.observed} for {names}. "
                       f"Open {highest} alert: {open_alerts[0].next_step}")
        elif acked and still_deviating:
            state = "CHANGE_ACKNOWLEDGED"
            summary = f"Difference from personal baseline in {names} continues; the alert was acknowledged."
        elif all(i.data_status == "INSUFFICIENT_DATA" for i in indicators):
            state = "BUILDING_BASELINE"
            valid = sum(1 for m in readings if m.quality_status == QualityStatus.VALID)
            summary = (f"Collecting data for a personal baseline ({valid} valid readings so far, "
                       f"{config.min_baseline_samples} needed).")
        elif latest.quality_status != QualityStatus.VALID:
            state = "LOW_QUALITY_DATA"
            summary = "Latest reading is flagged low quality and is not used for alerts. Repeat when still."
        else:
            state = "WITHIN_PERSONAL_BASELINE"
            summary = f"Latest {names} is within the personal baseline band."

        self_report = None
        if any(p in SCORE_PARAMETERS for p in params):
            recent = [c for c in store.checkins(astronaut_id)
                      if latest.timestamp_utc - timedelta(days=COMPLETENESS_DAYS) < c.timestamp_utc]
            if recent:
                self_report = {s: round(fmean(getattr(c, s) for c in recent), 2) for s in SCORE_PARAMETERS}

        domains.append(TwinDomain(
            domain=key, label=label, state=state, summary=summary,
            last_data_at=latest.timestamp_utc,
            freshness="FRESH" if now - last_seen <= fresh_within else "STALE",
            completeness_7d=_completeness(readings, latest.timestamp_utc),
            open_alert_ids=[a.alert_id for a in open_alerts],
            highest_open_level=highest,
            self_report_7d=self_report,
        ))

    for key, label, note in NOT_CONNECTED_DOMAINS:
        domains.append(TwinDomain(domain=key, label=label, state="NOT_CONNECTED", summary=note))

    pending = [
        PendingFollowUp(action_id=a.action_id, alert_id=a.alert_id, follow_up_at=a.follow_up_at,
                        overdue=a.follow_up_at < now)
        for a in store.list_actions(astronaut_id=astronaut_id)
        if a.action_type.value == "FOLLOW_UP_MEASUREMENT" and a.outcome == "PENDING" and a.follow_up_at
    ]
    attention = any(d.state == "CHANGE_FROM_BASELINE" for d in domains) or any(p.overdue for p in pending)

    return TwinOut(
        astronaut_id=astronaut_id,
        generated_at=now,
        twin_version=_version(store, astronaut_id, measured_params),
        data_through=data_through,
        attention_needed=attention,
        domains=domains,
        pending_follow_ups=sorted(pending, key=lambda p: p.follow_up_at),
        contains_simulated_data=simulated,
    )
