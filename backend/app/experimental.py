"""Experimental: window-level PPG quality gate (batch 7).

POST /api/v1/experimental/ppg-quality   judge one raw 10 s PPG + accelerometer window
GET  /api/v1/experimental/ppg-quality   which model is loaded, and its limits

This is a SECONDARY signal. It never edits measurements, never creates or changes alerts,
and its output is a *suggested* quality status for the device or gateway to use. The model
and its evaluation are described in docs/model_card_ppg_quality.md.
"""
from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from .audit import AuditEventType
from astra_ml.ppg_gate import (
    DEFAULT_THRESHOLD, MIN_ACC_FS, MIN_PPG_FS, GateModel, WindowError, assess_window, load_gate_model,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = ROOT / "models" / "ppg_quality_combined_rf.joblib"
MAX_SAMPLES = 20_000  # 10 s at up to ~2 kHz; keeps one request small
NOTICE = (
    "EXPERIMENTAL secondary signal. Judges whether this window's PPG heart rate looks "
    "trustworthy; it says nothing about health and does not change stored data or alerts. "
    "Trained on healthy volunteers on Earth, not astronauts or CrewBand."
)


def default_model_path() -> Path:
    return Path(os.getenv("ASTRA_PPG_MODEL", str(DEFAULT_MODEL)))


class PpgWindowIn(BaseModel):
    astronaut_id: str | None = Field(default=None, min_length=1, max_length=40)
    device_id: str | None = Field(default=None, max_length=60)
    window_start_utc: datetime | None = None
    ppg: list[float] = Field(min_length=1, max_length=MAX_SAMPLES)
    ppg_fs: float = Field(gt=0, le=2000, description=f"Hz, at least {MIN_PPG_FS:g}")
    acc_g: list[tuple[float, float, float]] = Field(min_length=1, max_length=MAX_SAMPLES,
                                                    description="[x, y, z] in units of g")
    acc_fs: float = Field(gt=0, le=2000, description=f"Hz, at least {MIN_ACC_FS:g}")

    @field_validator("window_start_utc")
    @classmethod
    def _aware(cls, v: datetime | None) -> datetime | None:
        if v is not None and v.tzinfo is None:
            raise ValueError("window_start_utc must include a timezone, e.g. 2026-11-01T08:00:00Z")
        return v.astimezone(timezone.utc) if v else None


class PpgQualityOut(BaseModel):
    experimental: Literal[True] = True
    verdict: Literal["LIKELY_RELIABLE", "LIKELY_UNRELIABLE", "CANNOT_ASSESS"]
    p_unreliable: float | None
    threshold: float
    ppg_hr_bpm: float | None
    suggested_quality_status: Literal["VALID", "SUSPECT"]
    reason: str
    features: dict[str, float]
    model: str
    window_seconds: float
    astronaut_id: str | None = None
    window_start_utc: datetime | None = None
    notice: str = NOTICE


class PpgModelOut(BaseModel):
    experimental: Literal[True] = True
    loaded: bool
    model: str | None = None
    source_file: str | None = None
    features: list[str] = []
    window_seconds: float | None = None
    unreliable_means: str | None = None
    threshold: float = DEFAULT_THRESHOLD
    trained_on: list[str] = []
    model_card: str = "docs/model_card_ppg_quality.md"
    problem: str | None = None
    notice: str = NOTICE


class _LazyModel:
    """Loads the model on first use, so the API starts (and every other endpoint works)
    even when the model file or scikit-learn is missing."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._gate: GateModel | None = None
        self._error: str | None = None

    def get(self) -> tuple[GateModel | None, str | None]:
        with self._lock:
            if self._gate is None and self._error is None:
                try:
                    if not self.path.exists():
                        raise FileNotFoundError(
                            f"model file {self.path.name} not found; train it with "
                            "python ml/eval/train_ppg_quality.py --with-wesad"
                        )
                    self._gate = load_gate_model(self.path)
                except ImportError as e:
                    self._error = f"scikit-learn/joblib not installed ({e.name})"
                except (FileNotFoundError, ValueError, KeyError) as e:
                    self._error = str(e)
            return self._gate, self._error


def build_router(model_path: Path, audit: Callable[..., None]) -> APIRouter:
    router = APIRouter(prefix="/api/v1/experimental", tags=["experimental"])
    lazy = _LazyModel(model_path)

    @router.get("/ppg-quality", response_model=PpgModelOut)
    def model_info():
        gate, problem = lazy.get()
        if gate is None:
            return PpgModelOut(loaded=False, problem=problem)
        return PpgModelOut(
            loaded=True,
            model=gate.model_id,
            source_file=gate.source,
            features=list(gate.features),
            window_seconds=gate.window_s,
            unreliable_means=f"PPG heart rate more than {gate.error_bpm:g} bpm away from the ECG heart rate",
            trained_on=list(gate.datasets),
        )

    @router.post("/ppg-quality", response_model=PpgQualityOut)
    def assess(body: PpgWindowIn):
        gate, problem = lazy.get()
        if gate is None:
            raise HTTPException(status_code=503, detail=f"PPG quality model unavailable: {problem}")
        try:
            result = assess_window(gate, body.ppg, body.ppg_fs, body.acc_g, body.acc_fs)
        except WindowError as e:
            raise HTTPException(status_code=422, detail=str(e)) from None
        if body.astronaut_id:
            audit(
                AuditEventType.PPG_QUALITY_ASSESSED, "api_client", "ppg_window", body.device_id, body.astronaut_id,
                verdict=result.verdict, p_unreliable=result.p_unreliable, model=gate.model_id,
                window_start_utc=body.window_start_utc.isoformat() if body.window_start_utc else None,
            )
        return PpgQualityOut(
            verdict=result.verdict,
            p_unreliable=result.p_unreliable,
            threshold=DEFAULT_THRESHOLD,
            ppg_hr_bpm=result.ppg_hr_bpm,
            suggested_quality_status=result.suggested_quality_status,
            reason=result.reason,
            features=result.features,
            model=gate.model_id,
            window_seconds=gate.window_s,
            astronaut_id=body.astronaut_id,
            window_start_utc=body.window_start_utc,
        )

    return router
