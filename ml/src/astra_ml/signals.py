from __future__ import annotations

from dataclasses import dataclass

import numpy as np

BASELINE_DAYS = 14
MIN_DAYS = 21


@dataclass(frozen=True)
class Profile:
    parameter: str
    unit: str
    base: float
    noise_sd: float
    drift_step: float      # signed change per day after the baseline window
    spike: float           # signed size of a single isolated outlier
    wearable: bool         # True: device-style scenarios (dropout, stale, motion) apply


PROFILES: dict[str, Profile] = {
    "heart_rate": Profile("heart_rate", "bpm", 62.0, 1.5, 1.2, 15.0, True),
    "skin_temperature": Profile("skin_temperature", "degC", 33.5, 0.25, 0.2, 2.5, True),
    "sleep_hours": Profile("sleep_hours", "h", 7.2, 0.4, -0.35, -3.0, False),
}

COMMON_SCENARIOS = ("stable", "gradual_deviation", "single_noise", "repeated_deviation", "missing_data")
WEARABLE_ONLY_SCENARIOS = ("dropout", "stale_feed", "motion_artifact")


@dataclass(frozen=True)
class SignalPlan:
    values: np.ndarray    # one value per day
    keep: np.ndarray      # False -> no record exists for that day
    suspect: np.ndarray   # True -> record exists but is low quality (motion)


def scenarios_for(profile: Profile) -> tuple[str, ...]:
    return COMMON_SCENARIOS + (WEARABLE_ONLY_SCENARIOS if profile.wearable else ())


def plan_scenario(profile: Profile, scenario: str, n_days: int = MIN_DAYS, seed: int = 42) -> SignalPlan:
    if scenario not in scenarios_for(profile):
        raise ValueError(
            f"scenario '{scenario}' is not available for {profile.parameter}; "
            f"choose from {list(scenarios_for(profile))}"
        )
    if n_days < MIN_DAYS:
        raise ValueError(f"n_days must be at least {MIN_DAYS}")

    rng = np.random.default_rng(seed)
    values = profile.base + rng.normal(0.0, profile.noise_sd, n_days)
    day = np.arange(n_days)
    keep = np.ones(n_days, dtype=bool)
    suspect = np.zeros(n_days, dtype=bool)
    direction = 1.0 if profile.drift_step > 0 else -1.0

    if scenario == "gradual_deviation":
        values = values + np.where(day >= BASELINE_DAYS, (day - (BASELINE_DAYS - 1)) * profile.drift_step, 0.0)
    elif scenario == "single_noise":
        values[17] += profile.spike
    elif scenario == "repeated_deviation":
        # A run of 3 high days, one normal day, then a run of 2 again.
        for d in (15, 16, 17, 19, 20):
            values[d] += direction * 6.0 * profile.noise_sd
    elif scenario == "missing_data":
        keep = np.random.default_rng(seed + 1).random(n_days) >= 0.2
    elif scenario == "dropout":
        keep[16:19] = False                      # 3-day gap, then data resumes
    elif scenario == "stale_feed":
        keep[16:] = False                        # feed stops after day 15
    elif scenario == "motion_artifact":
        values[15:21] += 8.0 * profile.noise_sd  # would look like a deviation...
        suspect[15:21] = True                    # ...but flagged as low quality
    return SignalPlan(values=values, keep=keep, suspect=suspect)
