from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from .models import Measurement, QualityStatus

MODEL_VERSION = "robust_baseline_v2"
MAD_SCALE = 1.4826  # makes MAD comparable to a standard deviation for normal data

# Smallest spread a baseline may have, per parameter (in its own unit). Two weeks of
# rounded readings (heart rate comes in whole bpm) often give a MAD far below the real
# day-to-day variation, which makes the band too narrow and alerts on ordinary days.
# On the simulated crew dataset (Astra/src/data), v1 raised 32 alerts over 180 days, 25 of
# them on days with nothing planted; with these floors it raises 4, 3 on planted events.
# Lower floors let the false alerts back in; higher ones hide the CO2-fault sleep loss.
# Demo assumptions about normal day-to-day variation, NOT clinical limits.
MIN_DISPERSION: dict[str, float] = {
    "heart_rate": 2.0,        # bpm
    "sleep_hours": 0.4,       # h
    "skin_temperature": 0.2,  # degC
}


@dataclass(frozen=True)
class Baseline:
    astronaut_id: str
    parameter: str
    window_start: datetime
    window_end: datetime
    centre: float
    dispersion: float
    sample_count: int
    model_version: str = MODEL_VERSION


@dataclass(frozen=True)
class BaselineResult:
    established: bool
    reason: str
    baseline: Baseline | None = None


def compute_baseline(measurements: list[Measurement], min_samples: int = 10) -> BaselineResult:
    if not measurements:
        return BaselineResult(False, "baseline not established: no measurements provided")

    if len({m.astronaut_id for m in measurements}) > 1 or len({m.parameter for m in measurements}) > 1:
        raise ValueError("a baseline is per astronaut and per parameter; got mixed input")

    unique = {m.record_id: m for m in measurements}  # dedupe so duplicates aren't double counted
    valid = sorted(
        (m for m in unique.values() if m.quality_status == QualityStatus.VALID),
        key=lambda m: m.timestamp_utc,
    )
    if len(valid) < min_samples:
        return BaselineResult(
            False, f"baseline not established: {len(valid)} valid samples, need {min_samples}"
        )

    values = np.array([m.value for m in valid])
    centre = float(np.median(values))
    dispersion = float(MAD_SCALE * np.median(np.abs(values - centre)))
    if dispersion == 0.0:
        return BaselineResult(False, "baseline not established: zero dispersion in window")
    dispersion = max(dispersion, MIN_DISPERSION.get(valid[0].parameter, 0.0))

    return BaselineResult(
        True,
        "ok",
        Baseline(
            astronaut_id=valid[0].astronaut_id,
            parameter=valid[0].parameter,
            window_start=valid[0].timestamp_utc,
            window_end=valid[-1].timestamp_utc,
            centre=centre,
            dispersion=dispersion,
            sample_count=len(valid),
        ),
    )


def robust_z(value: float, baseline: Baseline) -> float:
    return (value - baseline.centre) / baseline.dispersion