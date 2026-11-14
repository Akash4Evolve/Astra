"""WESAD loader for the PPG quality model.

WESAD (Schmidt & Reiss, 2018; UCI ML Repository, doi:10.24432/C57K5T): 15 people in a lab
stress study. Each subject folder holds SX/SX.pkl, a pickled dict:
    signal.wrist.BVP  (n, 1)  64 Hz   wrist PPG (Empatica E4)   <- the PPG we judge
    signal.wrist.ACC  (n, 3)  32 Hz   wrist accelerometer, raw units of 1/64 g
    signal.chest.ECG  (n, 1)  700 Hz  chest ECG (RespiBAN)       <- reference heart rate
    label             (n,)    700 Hz  0 transient, 1 baseline, 2 stress, 3 amusement, 4 meditation

Unlike PhysioNet, WESAD has no beat annotations, so R-peaks are detected here and windows
with irregular beat intervals are dropped. This makes the WESAD labels less exact.

Security note: .pkl files can run code when loaded. Only load the official WESAD files.
"""
from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np

from .ppg_quality import WINDOW_S, Window, common_features, detect_r_peaks, ecg_hr_clean

FS_BVP, FS_ACC, FS_ECG = 64.0, 32.0, 700.0
ACC_UNITS_PER_G = 64.0
CONDITIONS = {0: "transient", 1: "baseline", 2: "stress", 3: "amusement", 4: "meditation"}


def find_subjects(root: Path) -> list[Path]:
    """Return SX.pkl paths under root (accepts .../WESAD or its parent)."""
    root = Path(root)
    if (root / "WESAD").is_dir():
        root = root / "WESAD"
    pkls = sorted(root.glob("S*/S*.pkl"), key=lambda p: int(p.stem[1:]) if p.stem[1:].isdigit() else 999)
    return [p for p in pkls if p.parent.name == p.stem]


def load_subject(pkl: Path) -> dict:
    with open(pkl, "rb") as f:
        data = pickle.load(f, encoding="latin1")  # the files were written with Python 2
    try:
        return {
            "subject": pkl.stem,
            "bvp": np.asarray(data["signal"]["wrist"]["BVP"], dtype=float).ravel(),
            "acc": np.asarray(data["signal"]["wrist"]["ACC"], dtype=float),
            "ecg": np.asarray(data["signal"]["chest"]["ECG"], dtype=float).ravel(),
            "label": np.asarray(data["label"]).ravel(),
        }
    except (KeyError, TypeError) as e:
        raise ValueError(f"{pkl}: unexpected WESAD layout ({e})") from e


def windows_for_subject(d: dict, window_s: float = WINDOW_S) -> list[Window]:
    """Cut one WESAD subject into windows aligned in time across the three sampling rates."""
    duration = min(len(d["bvp"]) / FS_BVP, len(d["acc"]) / FS_ACC, len(d["ecg"]) / FS_ECG)
    r_peaks = detect_r_peaks(d["ecg"], FS_ECG)
    out: list[Window] = []
    t = 0.0
    while t + window_s <= duration:
        b0, b1 = int(t * FS_BVP), int((t + window_s) * FS_BVP)
        a0, a1 = int(t * FS_ACC), int((t + window_s) * FS_ACC)
        e0, e1 = int(t * FS_ECG), int((t + window_s) * FS_ECG)
        ref = ecg_hr_clean(r_peaks, e0, e1, FS_ECG)
        bvp = d["bvp"][b0:b1]
        if np.isfinite(ref) and np.all(np.isfinite(bvp)):
            hr, feats = common_features(bvp, FS_BVP, d["acc"][a0:a1] / ACC_UNITS_PER_G, FS_ACC)
            if np.isfinite(hr):
                labels = d["label"][e0:e1]
                code = int(np.bincount(labels.astype(int)).argmax()) if len(labels) else 0
                out.append(Window(
                    record=f"wesad_{d['subject']}", subject=f"wesad_{d['subject']}",
                    activity=CONDITIONS.get(code, "other"), start_s=t,
                    ecg_hr=ref, ppg_hr=hr, error_bpm=abs(hr - ref), features=feats,
                ))
        t += window_s
    return out
