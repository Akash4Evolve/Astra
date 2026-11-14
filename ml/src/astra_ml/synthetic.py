from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

from .models import Measurement, QualityStatus, SourceType

SCENARIOS = {"stable", "gradual_deviation", "single_noise"}
BASELINE_DAYS = 14
MIN_DAYS = 21
START = datetime(2026, 11, 1, 8, 0, tzinfo=timezone.utc)


def generate_heart_rate(
    scenario: str = "stable",
    n_days: int = MIN_DAYS,
    seed: int = 42,
    astronaut_id: str = "AST-001",
    device_id: str = "ASTRA-SIM-001",
    base: float = 62.0,
    noise_sd: float = 1.5,
) -> list[Measurement]:
    """Daily resting heart-rate summaries. Demo data only, not real physiology."""
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario '{scenario}', choose from {sorted(SCENARIOS)}")
    if n_days < MIN_DAYS:
        raise ValueError(f"n_days must be at least {MIN_DAYS}")

    rng = np.random.default_rng(seed)  # fixed seed -> reproducible demo
    values = base + rng.normal(0, noise_sd, n_days)
    day = np.arange(n_days)

    if scenario == "gradual_deviation":
        values = values + np.where(day >= BASELINE_DAYS, (day - (BASELINE_DAYS - 1)) * 1.2, 0.0)
    elif scenario == "single_noise":
        values[17] += 15.0  # one isolated spike inside the evaluation window

    return [
        Measurement(
            astronaut_id=astronaut_id,
            device_id=device_id,
            timestamp_utc=START + timedelta(days=int(d)),
            received_at=START + timedelta(days=int(d)),
            parameter="heart_rate",
            value=float(v),
            unit="bpm",
            source_type=SourceType.SIMULATED,
            quality_status=QualityStatus.VALID,
            is_simulated=True,
            metadata={"scenario": scenario, "aggregation": "daily_resting_summary"},
        )
        for d, v in zip(day, values)
    ]