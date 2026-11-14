"""PPG quality pipeline, tested on FAKE recordings that mimic the PhysioNet layout
(same 18 channel names, 500 Hz, ECG R-peak annotations). No real data needed."""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

from astra_ml.ppg_quality import (
    FEATURES, dominant_rate_bpm, ecg_hr_bpm, feature_matrix, label, windows_for_record,
)

FS = 500.0
NAMES = ["ecg", "pleth_1", "pleth_2", "pleth_3", "pleth_4", "pleth_5", "pleth_6", "lc_1", "lc_2",
         "temp_1", "temp_2", "temp_3", "a_x", "a_y", "a_z", "g_x", "g_y", "g_z"]
UNITS = ["mV"] + ["NU"] * 8 + ["C"] * 3 + ["g"] * 3 + ["deg/s"] * 3
# activity -> (heart rate bpm, step rate Hz, motion amplitude in PPG, accelerometer amplitude g)
ACTIVITY = {"sit": (68, 0.0, 0.0, 0.01), "walk": (92, 1.8, 0.6, 0.3), "run": (128, 2.6, 4.0, 1.2)}


def fake_record(subject: int, activity: str, seconds: float = 60.0, seed: int = 0):
    rng = np.random.default_rng(seed + subject * 10 + len(activity))
    hr, step_hz, ppg_motion, acc_amp = ACTIVITY[activity]
    hr += rng.normal(0, 3)
    t = np.arange(int(seconds * FS)) / FS
    beat_hz = hr / 60
    peaks = (np.arange(0, seconds, 1 / beat_hz) * FS).astype(int)
    sig = np.zeros((len(t), len(NAMES)))
    sig[peaks, 0] = 1.0  # ECG spikes at R-peaks
    pulse = np.sin(2 * np.pi * beat_hz * t) + 0.3 * np.sin(4 * np.pi * beat_hz * t)
    motion = np.sin(2 * np.pi * step_hz * t + rng.uniform(0, 6)) if step_hz else 0 * t
    for k in range(1, 7):
        sig[:, k] = pulse + ppg_motion * motion * rng.uniform(0.7, 1.3) + rng.normal(0, 0.1, len(t))
    sig[:, 7:12] = rng.normal(0, 0.01, (len(t), 5)) + 30
    for k in range(12, 15):
        sig[:, k] = (1.0 if k == 14 else 0.0) + acc_amp * motion + rng.normal(0, 0.01, len(t))
    for k in range(15, 18):
        sig[:, k] = 40 * acc_amp * motion + rng.normal(0, 0.5, len(t))
    return sig, peaks


def test_spectral_rate_recovers_a_clean_pulse():
    t = np.arange(int(10 * FS)) / FS
    rate, ratio = dominant_rate_bpm(np.sin(2 * np.pi * 1.25 * t), FS)
    assert abs(rate - 75) < 1.5 and ratio > 0.8


def test_ecg_rate_from_peaks_and_too_few_beats():
    peaks = (np.arange(0, 10, 0.8) * FS).astype(int)  # 75 bpm
    assert abs(ecg_hr_bpm(peaks, 0, int(10 * FS), FS) - 75) < 0.5
    assert np.isnan(ecg_hr_bpm(peaks[:2], 0, int(10 * FS), FS))


def test_motion_makes_ppg_unreliable_and_features_see_it():
    sig, peaks = fake_record(1, "sit")
    sit = windows_for_record("s1_sit", sig, NAMES, FS, peaks)
    sig, peaks = fake_record(1, "run")
    run = windows_for_record("s1_run", sig, NAMES, FS, peaks)
    assert len(sit) == 6 and len(run) == 6
    assert np.mean([w.error_bpm for w in sit]) < 5
    assert label(run).mean() > label(sit).mean()
    assert np.mean([w.features["acc_std"] for w in run]) > np.mean([w.features["acc_std"] for w in sit])
    assert run[0].subject == "s1" and run[0].activity == "run"
    X = feature_matrix(sit + run)
    assert X.shape == (12, len(FEATURES)) and np.all(np.isfinite(X))


def test_missing_channels_are_reported():
    sig, peaks = fake_record(1, "sit")
    with pytest.raises(ValueError, match="missing channels"):
        windows_for_record("s1_sit", sig[:, :12], NAMES[:12], FS, peaks)


def _load_trainer():
    path = Path(__file__).resolve().parents[1] / "eval" / "train_ppg_quality.py"
    spec = importlib.util.spec_from_file_location("train_ppg_quality", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["train_ppg_quality"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_end_to_end_on_fake_wfdb_files_with_person_wise_split(tmp_path):
    wfdb = pytest.importorskip("wfdb")
    pytest.importorskip("sklearn")
    names = []
    for s in range(1, 6):
        for act in ACTIVITY:
            rec = f"s{s}_{act}"
            sig, peaks = fake_record(s, act)
            wfdb.wrsamp(rec, fs=int(FS), units=UNITS, sig_name=NAMES, p_signal=sig,
                        fmt=["16"] * len(NAMES), write_dir=str(tmp_path))
            wfdb.wrann(rec, "atr", sample=peaks, symbol=["N"] * len(peaks), write_dir=str(tmp_path))
            names.append(rec)
    (tmp_path / "RECORDS").write_text("\n".join(names) + "\n")

    tr = _load_trainer()
    df = tr.build_table(tmp_path, "pleth_3", 10.0, None)
    assert df["subject"].nunique() == 5 and len(df) == 5 * 3 * 6
    y = (df["error_bpm"].to_numpy() > 10).astype(int)
    results = tr.cross_validate(df, y, folds=5)  # asserts no person overlap inside
    rf = tr.metrics(y, results["Random forest"]["pred"], results["Random forest"]["score"],
                    df["error_bpm"].to_numpy())
    assert rf["balanced_acc"] > 0.7
    assert rf["mae_kept"] < df["error_bpm"].mean()  # the gate lowers the error of what is kept
    report = tr.render(df, y, results, "pleth_3", 10, 10, 5, {f: 0.1 for f in FEATURES})
    assert "by person" in report and "not the wrist" in report and "Not astronauts" in report
