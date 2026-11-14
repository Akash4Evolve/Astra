from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import timedelta

from .alerts import RULE_VERSION, RuleConfig, analyze
from .baseline import MODEL_VERSION
from .checkins import checkin_to_measurement
from .models import Measurement
from .scenarios import available_scenarios, generate_checkins, generate_series
from .signals import BASELINE_DAYS
from .synthetic import START

PARAMETERS = ("heart_rate", "skin_temperature", "sleep_hours")
ONSET = {"gradual_deviation": 14, "repeated_deviation": 15}  # first deviating day index
EXPECT_ALERT = frozenset(ONSET)
SCENARIO_ORDER = (
    "stable", "gradual_deviation", "single_noise", "repeated_deviation",
    "missing_data", "dropout", "stale_feed", "motion_artifact",
)
METHODS = ("ASTRA", "Naive +/- 2 SD", "Naive +/- 3 SD")


@dataclass
class ScenarioStats:
    parameter: str
    scenario: str
    runs: int = 0
    astra_alerts: int = 0
    astra_review: int = 0
    no_baseline: int = 0
    naive2_alerts: int = 0
    naive3_alerts: int = 0
    delays: list[int] = field(default_factory=list)

    def alerts(self, method: str) -> int:
        return {
            "ASTRA": self.astra_alerts,
            "Naive +/- 2 SD": self.naive2_alerts,
            "Naive +/- 3 SD": self.naive3_alerts,
        }[method]


def _make_records(parameter: str, scenario: str, seed: int) -> list[Measurement]:
    if parameter == "sleep_hours":
        return [checkin_to_measurement(c) for c in generate_checkins(scenario, seed=seed)]
    return generate_series(parameter, scenario, seed=seed)


def _day(m: Measurement) -> int:
    return (m.timestamp_utc - START).days


def _naive_alert(records: list[Measurement], k: float) -> bool:
    """Alert if any reading after the baseline window is outside mean +/- k*SD of that window.
    Deliberately simple (spec 9.5) and blind to quality flags."""
    if not records:
        return False
    ordered = sorted(records, key=lambda m: m.timestamp_utc)
    cutoff = ordered[0].timestamp_utc + timedelta(days=BASELINE_DAYS)
    base = [m.value for m in ordered if m.timestamp_utc < cutoff]
    if len(base) < 3:
        return False
    mean, sd = statistics.fmean(base), statistics.stdev(base)
    return any(abs(m.value - mean) > k * sd for m in ordered if m.timestamp_utc >= cutoff)


def _first_alert_day(records: list[Measurement]) -> int | None:
    ordered = sorted(records, key=lambda m: m.timestamp_utc)
    for k in range(2, len(ordered) + 1):
        if analyze(ordered[:k]).alert is not None:
            return _day(ordered[k - 1])
    return None


def evaluate(
    n_seeds: int = 200,
    seed_start: int = 0,
    parameters: tuple[str, ...] = PARAMETERS,
) -> list[ScenarioStats]:
    if n_seeds < 1:
        raise ValueError("n_seeds must be at least 1")
    out: list[ScenarioStats] = []
    for parameter in parameters:
        for scenario in available_scenarios(parameter):
            st = ScenarioStats(parameter, scenario)
            for seed in range(seed_start, seed_start + n_seeds):
                records = _make_records(parameter, scenario, seed)
                result = analyze(records)
                st.runs += 1
                st.no_baseline += 0 if result.baseline.established else 1
                if result.alert is not None:
                    st.astra_alerts += 1
                    st.astra_review += int(result.alert.level.value == "REVIEW")
                st.naive2_alerts += int(_naive_alert(records, 2.0))
                st.naive3_alerts += int(_naive_alert(records, 3.0))
                if scenario in ONSET:
                    day = _first_alert_day(records)
                    if day is not None:
                        st.delays.append(day - ONSET[scenario])
            out.append(st)
    return out


def by_scenario(stats: list[ScenarioStats]) -> dict[str, ScenarioStats]:
    merged: dict[str, ScenarioStats] = {}
    for s in stats:
        m = merged.setdefault(s.scenario, ScenarioStats("all", s.scenario))
        m.runs += s.runs
        m.astra_alerts += s.astra_alerts
        m.astra_review += s.astra_review
        m.no_baseline += s.no_baseline
        m.naive2_alerts += s.naive2_alerts
        m.naive3_alerts += s.naive3_alerts
        m.delays.extend(s.delays)
    return merged


def pooled(stats: list[ScenarioStats]) -> dict[str, dict[str, float]]:
    pos = [s for s in stats if s.scenario in EXPECT_ALERT]
    neg = [s for s in stats if s.scenario not in EXPECT_ALERT]
    pos_runs, neg_runs = sum(s.runs for s in pos), sum(s.runs for s in neg)
    out: dict[str, dict[str, float]] = {}
    for method in METHODS:
        tp = sum(s.alerts(method) for s in pos)
        fp = sum(s.alerts(method) for s in neg)
        out[method] = {
            "detection": tp / pos_runs if pos_runs else float("nan"),
            "false_alarm": fp / neg_runs if neg_runs else float("nan"),
            "precision": tp / (tp + fp) if (tp + fp) else float("nan"),
        }
    return out


def _pct(a: float, b: float) -> str:
    return f"{100 * a / b:.1f}%" if b else "n/a"


def render_markdown(stats: list[ScenarioStats], n_seeds: int, seed_start: int) -> str:
    merged = by_scenario(stats)
    cfg = RuleConfig()
    lines = [
        "# ASTRA detector evaluation (synthetic scenarios)",
        "",
        f"- Seeds per scenario and parameter: {n_seeds} (seeds {seed_start} to {seed_start + n_seeds - 1})",
        f"- Parameters: {', '.join(PARAMETERS)}; 21-day series, baseline = first {cfg.baseline_days} days",
        f"- ASTRA: {MODEL_VERSION} + {RULE_VERSION}; |robust z| > {cfg.z_threshold} on "
        f"{cfg.watch_persistence}+ consecutive valid readings; low-quality readings never count",
        "- Naive baseline: alert if ANY reading after the baseline window is outside mean +/- k SD "
        "of that window (k = 2 and 3); it ignores quality flags",
        "- Data is synthetic and labelled. This is not clinical validation.",
        "",
        "## Alert rate per scenario",
        "",
        "| Scenario | Alert expected | ASTRA | Naive +/- 2 SD | Naive +/- 3 SD | Runs |",
        "|---|---|---|---|---|---|",
    ]
    for name in SCENARIO_ORDER:
        s = merged.get(name)
        if s is None:
            continue
        expected = "yes" if name in EXPECT_ALERT else "no"
        lines.append(
            f"| {name} | {expected} | {_pct(s.astra_alerts, s.runs)} | "
            f"{_pct(s.naive2_alerts, s.runs)} | {_pct(s.naive3_alerts, s.runs)} | {s.runs} |"
        )

    lines += [
        "",
        "## Pooled over all scenarios",
        "",
        "| Method | Detection rate | False-alarm rate | Precision |",
        "|---|---|---|---|",
    ]
    for method, m in pooled(stats).items():
        lines.append(
            f"| {method} | {100 * m['detection']:.1f}% | {100 * m['false_alarm']:.1f}% | "
            f"{100 * m['precision']:.1f}% |"
        )
    lines.append("")
    lines.append(
        "Detection rate = alerts on scenarios that contain a real deviation. False-alarm rate = alerts on "
        "scenarios that should not alert. Precision depends on the scenario mix (6 negative vs 2 positive types)."
    )

    lines += [
        "",
        "## Detection delay (days after deviation onset)",
        "",
        "| Scenario | Runs that alerted | Median | Min | Max |",
        "|---|---|---|---|---|",
    ]
    for name in ONSET:
        s = merged.get(name)
        if s is None or not s.delays:
            lines.append(f"| {name} | 0 | n/a | n/a | n/a |")
            continue
        lines.append(
            f"| {name} | {len(s.delays)}/{s.runs} | {statistics.median(s.delays):g} | "
            f"{min(s.delays)} | {max(s.delays)} |"
        )

    gaps = [(n, s) for n, s in merged.items() if s.no_baseline]
    if gaps:
        lines += ["", "## Baseline not established"]
        for name, s in gaps:
            lines.append(f"- {name}: {_pct(s.no_baseline, s.runs)} of runs had too few valid baseline "
                         "samples; alerts are withheld there by design.")

    lines += [
        "",
        "## Limits of this evaluation",
        "- heart_rate and skin_temperature use the same noise shape with different units, so their "
        "results are identical by construction. They are not independent confirmations.",
        "- Fixed 14-day baseline and 21-day series. Slow drifts need more days to reach REVIEW.",
        "- The naive rule is deliberately simple (spec 9.5). Thresholds in both methods are demo assumptions.",
        "- Synthetic data generated by the team: results show the logic behaves as designed, "
        "not that it works on real astronaut data.",
        "",
    ]
    return "\n".join(lines)
