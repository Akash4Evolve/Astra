"""Window-level PPG quality gate: the experimental secondary signal (batch 7).

Takes one raw window of wrist PPG plus accelerometer, computes the same features the model
was trained on (ppg_quality.common_features), and returns the trained model's probability
that the heart rate from this window is UNRELIABLE (off from ECG by more than error_bpm).

It is a SECONDARY, EXPERIMENTAL signal:
- it only says whether a reading looks trustworthy; it says nothing about health;
- it never changes stored measurements or alerts; it returns a suggested quality status;
- it was trained on healthy volunteers on Earth (PhysioNet PTT finger PPG + WESAD wrist PPG),
  not on astronauts or on CrewBand. See docs/model_card_ppg_quality.md.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np

from .ppg_quality import COMMON_FEATURES, common_features

DEFAULT_THRESHOLD = 0.5
MIN_PPG_FS = 20.0   # the 0.5-4 Hz pulse band filter needs well above 8 Hz
MIN_ACC_FS = 10.0
DURATION_TOLERANCE = 0.05  # a window may be up to 5% shorter or longer than the model's
MODEL_ID_PREFIX = "ppg_quality_rf"

Verdict = Literal["LIKELY_RELIABLE", "LIKELY_UNRELIABLE", "CANNOT_ASSESS"]


class WindowError(ValueError):
    """The window cannot be assessed as sent (wrong length, rate or shape)."""


@dataclass(frozen=True)
class GateModel:
    model: Any
    features: tuple[str, ...]
    window_s: float
    error_bpm: float
    datasets: tuple[str, ...]
    source: str

    @property
    def model_id(self) -> str:
        return f"{MODEL_ID_PREFIX}[{'+'.join(self.datasets)}]"


@dataclass(frozen=True)
class GateResult:
    verdict: Verdict
    p_unreliable: float | None
    ppg_hr_bpm: float | None
    suggested_quality_status: Literal["VALID", "SUSPECT"]
    reason: str
    features: dict[str, float] = field(default_factory=dict)


def load_gate_model(path: Path) -> GateModel:
    """Load a bundle saved by ml/eval/train_ppg_quality.py.

    joblib files are pickles and can run code when loaded: only load model files this
    project produced. Only bundles that use the wrist-compatible features (one PPG
    channel + accelerometer, i.e. COMMON_FEATURES) are accepted.
    """
    from joblib import load

    bundle = load(path)
    features = tuple(bundle["features"])
    extra = [f for f in features if f not in COMMON_FEATURES]
    if extra:
        raise ValueError(
            f"{path.name} needs {extra}, which a single-channel wristband cannot provide; "
            "use the combined model (models/ppg_quality_combined_rf.joblib)"
        )
    model = bundle["model"]
    if 1 not in list(model.classes_):
        raise ValueError(f"{path.name}: model has no 'unreliable' class")
    return GateModel(
        model=model,
        features=features,
        window_s=float(bundle["window_s"]),
        error_bpm=float(bundle["error_bpm"]),
        datasets=tuple(bundle.get("datasets", ["physionet_ptt"])),
        source=path.name,
    )


def _check(n: int, fs: float, window_s: float, name: str, min_fs: float) -> None:
    if fs < min_fs:
        raise WindowError(f"{name} sampling rate {fs:g} Hz is below the {min_fs:g} Hz minimum")
    seconds = n / fs
    if abs(seconds - window_s) > DURATION_TOLERANCE * window_s:
        raise WindowError(
            f"{name} covers {seconds:.2f} s; the model was trained on {window_s:g} s windows "
            f"(+/- {DURATION_TOLERANCE:.0%})"
        )


def assess_window(
    gate: GateModel,
    ppg: np.ndarray,
    ppg_fs: float,
    acc_g: np.ndarray,
    acc_fs: float,
    threshold: float = DEFAULT_THRESHOLD,
) -> GateResult:
    """Judge one window. acc_g is (n, 3) in units of g."""
    ppg = np.asarray(ppg, dtype=float)
    acc_g = np.asarray(acc_g, dtype=float)
    if ppg.ndim != 1:
        raise WindowError("ppg must be a flat list of samples")
    if acc_g.ndim != 2 or acc_g.shape[1] != 3:
        raise WindowError("acc_g must be a list of [x, y, z] samples")
    _check(len(ppg), ppg_fs, gate.window_s, "ppg", MIN_PPG_FS)
    _check(len(acc_g), acc_fs, gate.window_s, "acc_g", MIN_ACC_FS)
    if not (np.all(np.isfinite(ppg)) and np.all(np.isfinite(acc_g))):
        raise WindowError("window contains NaN or infinite samples")

    if np.ptp(ppg) == 0:
        return GateResult("CANNOT_ASSESS", None, None, "SUSPECT", "flat PPG signal (sensor off or saturated)")

    hr, feats = common_features(ppg, ppg_fs, acc_g, acc_fs)
    row = [feats[f] for f in gate.features]
    clean = {k: round(float(v), 4) for k, v in feats.items() if k in gate.features}
    if not math.isfinite(hr) or not all(math.isfinite(v) for v in row):
        return GateResult("CANNOT_ASSESS", None, None, "SUSPECT", "no pulse rate found in the 36-210 bpm band", clean)

    proba = gate.model.predict_proba(np.array([row]))[0]
    p = float(proba[list(gate.model.classes_).index(1)])
    unreliable = p >= threshold
    return GateResult(
        verdict="LIKELY_UNRELIABLE" if unreliable else "LIKELY_RELIABLE",
        p_unreliable=round(p, 4),
        ppg_hr_bpm=round(float(hr), 1),
        suggested_quality_status="SUSPECT" if unreliable else "VALID",
        reason=(
            f"model estimates P(heart rate off by > {gate.error_bpm:g} bpm) = {p:.2f} "
            f"({'at or above' if unreliable else 'below'} the {threshold:g} threshold)"
        ),
        features=clean,
    )
