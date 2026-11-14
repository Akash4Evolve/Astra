from __future__ import annotations

from datetime import timedelta

import numpy as np

from .checkins import CheckIn
from .models import Measurement, QualityStatus, SourceType
from .signals import MIN_DAYS, PROFILES, Profile, plan_scenario, scenarios_for
from .synthetic import START


def _profile(parameter: str) -> Profile:
    profile = PROFILES.get(parameter)
    if profile is None:
        raise ValueError(f"unknown parameter '{parameter}', choose from {sorted(PROFILES)}")
    return profile


def available_scenarios(parameter: str) -> tuple[str, ...]:
    return scenarios_for(_profile(parameter))


def generate_series(
    parameter: str,
    scenario: str = "stable",
    n_days: int = MIN_DAYS,
    seed: int = 42,
    astronaut_id: str = "AST-001",
    device_id: str = "ASTRA-SIM-001",
) -> list[Measurement]:
    """Daily resting-summary readings from a simulated wearable. Demo data only."""
    profile = _profile(parameter)
    if not profile.wearable:
        raise ValueError(f"{parameter} comes from check-ins; use generate_checkins()")
    plan = plan_scenario(profile, scenario, n_days, seed)

    records: list[Measurement] = []
    for d in range(n_days):
        if not plan.keep[d]:
            continue
        ts = START + timedelta(days=d)
        flagged = bool(plan.suspect[d])
        metadata = {"scenario": scenario, "aggregation": "daily_resting_summary"}
        if flagged:
            metadata["motion_detected"] = True
        records.append(
            Measurement(
                astronaut_id=astronaut_id,
                device_id=device_id,
                timestamp_utc=ts,
                received_at=ts,
                parameter=parameter,
                value=float(plan.values[d]),
                unit=profile.unit,
                source_type=SourceType.SIMULATED,
                quality_status=QualityStatus.SUSPECT if flagged else QualityStatus.VALID,
                is_simulated=True,
                metadata=metadata,
            )
        )
    return records


def generate_checkins(
    scenario: str = "stable",
    n_days: int = MIN_DAYS,
    seed: int = 42,
    astronaut_id: str = "AST-001",
) -> list[CheckIn]:
    """Synthetic daily check-ins. Fatigue and stress rise and mood falls with sleep loss."""
    profile = PROFILES["sleep_hours"]
    plan = plan_scenario(profile, scenario, n_days, seed)
    rng = np.random.default_rng(seed + 2)

    def score(centre: float, slope: float, deficit: float) -> int:
        return int(np.clip(np.rint(centre + slope * deficit + rng.normal(0.0, 0.4)), 1, 5))

    out: list[CheckIn] = []
    for d in range(n_days):
        if not plan.keep[d]:
            continue
        sleep = float(plan.values[d])
        deficit = max(0.0, (profile.base - sleep) / profile.noise_sd)
        ts = START + timedelta(days=d, hours=12)  # 20:00 UTC
        out.append(
            CheckIn(
                astronaut_id=astronaut_id,
                timestamp_utc=ts,
                received_at=ts,
                sleep_hours=sleep,
                fatigue=score(2.0, 0.5, deficit),
                stress=score(2.0, 0.4, deficit),
                mood=score(4.0, -0.4, deficit),
                source_type=SourceType.SIMULATED,
                is_simulated=True,
            )
        )
    return out
