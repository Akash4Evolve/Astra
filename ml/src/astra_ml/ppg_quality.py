"""PPG signal-quality features and labels (real-data ML for the quality gate).

Task: for a short window of PPG (optical pulse signal), predict whether the heart rate it gives
is RELIABLE (close to the ECG heart rate) or UNRELIABLE (e.g. corrupted by motion).

- Label source: ECG R-peak annotations give a reference heart rate. A window is
  UNRELIABLE if |PPG HR - ECG HR| > error_bpm (default 10 bpm, a stated assumption).
- In the PhysioNet dataset the PPG sensors sit on the left index finger, not the wrist,
  so results transfer to a wristband only partly.
- This is NOT a health model. It only decides whether a reading is trustworthy enough
  to be used, which is what ASTRA's quality gate needs.

Pure numpy/scipy, no file I/O here (that lives in ml/eval/train_ppg_quality.py).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import butter, sosfiltfilt, welch
from scipy.stats import kurtosis, skew

HR_BAND_HZ = (0.6, 3.5)  # 36-210 bpm
WINDOW_S = 10.0
DEFAULT_ERROR_BPM = 10.0
FEATURES = (
    "acc_std",            # motion intensity (accelerometer magnitude, g)
    "gyro_std",           # rotation intensity (deg/s)
    "ppg_peak_ratio",     # how concentrated the PPG spectrum is at one rate (clean pulse -> high)
    "ppg_skew",           # pulse shape statistic, a known PPG quality index
    "ppg_kurtosis",
    "ppg_channel_disagree_bpm",  # HR disagreement between two PPG channels
    "ppg_vs_motion_bpm",  # distance between PPG rate and step/motion rate (small -> locked onto motion)
)
# Features every dataset can provide (WESAD has no gyroscope and only one PPG channel).
# Used for the combined and cross-dataset models.
COMMON_FEATURES = ("acc_std", "ppg_peak_ratio", "ppg_skew", "ppg_kurtosis", "ppg_vs_motion_bpm")


@dataclass(frozen=True)
class Window:
    record: str
    subject: str
    activity: str
    start_s: float
    ecg_hr: float
    ppg_hr: float
    error_bpm: float
    features: dict[str, float]


def bandpass(x: np.ndarray, fs: float, lo: float = 0.5, hi: float = 4.0) -> np.ndarray:
    sos = butter(2, [lo, hi], btype="band", fs=fs, output="sos")
    return sosfiltfilt(sos, x - np.mean(x))


def dominant_rate_bpm(x: np.ndarray, fs: float, band: tuple[float, float] = HR_BAND_HZ) -> tuple[float, float]:
    """Spectral peak inside `band`. Returns (rate in bpm, share of band power at the peak +/- 0.1 Hz)."""
    nfft = 1 << int(np.ceil(np.log2(max(len(x), 1) * 4)))
    f, p = welch(x, fs=fs, nperseg=len(x), nfft=nfft, detrend="constant")
    m = (f >= band[0]) & (f <= band[1])
    if not m.any() or p[m].sum() <= 0:
        return float("nan"), 0.0
    fb, pb = f[m], p[m]
    peak = fb[int(np.argmax(pb))]
    near = np.abs(fb - peak) <= 0.1
    return float(peak * 60.0), float(pb[near].sum() / pb.sum())


def ecg_hr_bpm(r_peaks: np.ndarray, start: int, stop: int, fs: float) -> float:
    """Reference HR from annotated R-peaks inside [start, stop). NaN if too few beats."""
    inside = r_peaks[(r_peaks >= start) & (r_peaks < stop)]
    rr = np.diff(inside) / fs
    rr = rr[(rr > 0.27) & (rr < 2.0)]  # 30-220 bpm, drops missed/double detections
    if len(rr) < 3:
        return float("nan")
    return float(60.0 / np.median(rr))


def common_features(
    ppg: np.ndarray, fs_ppg: float, acc_g: np.ndarray, fs_acc: float
) -> tuple[float, dict[str, float]]:
    """Features shared by all datasets. Signals may have different sampling rates.
    acc_g is (n, 3) in units of g. Returns (PPG heart rate in bpm, features)."""
    p = bandpass(ppg, fs_ppg)
    hr, ratio = dominant_rate_bpm(p, fs_ppg)
    acc_mag = np.linalg.norm(acc_g, axis=1)
    motion_rate, _ = dominant_rate_bpm(bandpass(acc_mag, fs_acc), fs_acc)
    return hr, {
        "acc_std": float(np.std(acc_mag)),
        "ppg_peak_ratio": ratio,
        "ppg_skew": float(skew(p)),
        "ppg_kurtosis": float(kurtosis(p)),
        "ppg_vs_motion_bpm": float(abs(hr - motion_rate)) if np.isfinite(motion_rate) else 200.0,
    }


def window_features(
    ppg: np.ndarray, ppg_other: np.ndarray, acc: np.ndarray, gyro: np.ndarray, fs: float
) -> tuple[float, dict[str, float]]:
    """PhysioNet: all signals at one rate. acc (g) and gyro are (n, 3).
    Returns (PPG heart rate in bpm, feature dict with all FEATURES)."""
    hr, feats = common_features(ppg, fs, acc, fs)
    hr_other, _ = dominant_rate_bpm(bandpass(ppg_other, fs), fs)
    feats["gyro_std"] = float(np.std(np.linalg.norm(gyro, axis=1)))
    feats["ppg_channel_disagree_bpm"] = float(abs(hr - hr_other))
    return hr, {f: feats[f] for f in FEATURES}


def windows_for_record(
    record: str,
    signals: np.ndarray,
    names: list[str],
    fs: float,
    r_peaks: np.ndarray,
    ppg_channel: str = "pleth_3",
    other_channel: str | None = None,
    window_s: float = WINDOW_S,
) -> list[Window]:
    """Cut one recording into non-overlapping windows with reference HR, PPG HR and features."""
    idx = {n: i for i, n in enumerate(names)}
    missing = [c for c in (ppg_channel, "a_x", "a_y", "a_z", "g_x", "g_y", "g_z") if c not in idx]
    if missing:
        raise ValueError(f"{record}: missing channels {missing}; found {names}")
    # Same colour, other finger segment: pleth_1<->4 (red), 2<->5 (infrared), 3<->6 (green)
    pairs = {"pleth_1": "pleth_4", "pleth_2": "pleth_5", "pleth_3": "pleth_6",
             "pleth_4": "pleth_1", "pleth_5": "pleth_2", "pleth_6": "pleth_3"}
    other_channel = other_channel or pairs.get(ppg_channel, "pleth_6")
    subject, _, activity = record.partition("_")

    n = int(window_s * fs)
    acc_cols = [idx["a_x"], idx["a_y"], idx["a_z"]]
    gyro_cols = [idx["g_x"], idx["g_y"], idx["g_z"]]
    out: list[Window] = []
    for start in range(0, signals.shape[0] - n + 1, n):
        stop = start + n
        ref = ecg_hr_bpm(r_peaks, start, stop, fs)
        seg = signals[start:stop]
        if not np.isfinite(ref) or not np.all(np.isfinite(seg[:, idx[ppg_channel]])):
            continue
        hr, feats = window_features(seg[:, idx[ppg_channel]], seg[:, idx[other_channel]],
                                    seg[:, acc_cols], seg[:, gyro_cols], fs)
        if not np.isfinite(hr):
            continue
        out.append(Window(record, subject, activity, start / fs, ref, hr, abs(hr - ref), feats))
    return out


def label(windows: list[Window], error_bpm: float = DEFAULT_ERROR_BPM) -> np.ndarray:
    """1 = UNRELIABLE (PPG HR off by more than error_bpm), 0 = reliable."""
    return np.array([int(w.error_bpm > error_bpm) for w in windows])


def feature_matrix(windows: list[Window], features: tuple[str, ...] = FEATURES) -> np.ndarray:
    return np.array([[w.features[f] for f in features] for w in windows], dtype=float)


def detect_r_peaks(ecg: np.ndarray, fs: float) -> np.ndarray:
    """Simple R-peak detector for datasets without beat annotations (e.g. WESAD).
    Band-pass 5-20 Hz, square, then peaks at least 0.27 s apart above an adaptive height.
    Polarity is chosen per recording. Less exact than expert annotations."""
    from scipy.signal import find_peaks

    sos = butter(2, [5.0, 20.0], btype="band", fs=fs, output="sos")
    x = sosfiltfilt(sos, ecg - np.median(ecg))
    if np.percentile(x, 99.5) < -np.percentile(x, 0.5):  # mostly negative QRS
        x = -x
    energy = np.clip(x, 0, None) ** 2
    out = []
    block = int(30 * fs)  # adaptive height per 30 s block
    for start in range(0, len(energy), block):
        seg = energy[start : start + block]
        if len(seg) < fs:
            continue
        height = 0.3 * np.percentile(seg, 99)
        peaks, _ = find_peaks(seg, height=height, distance=int(0.27 * fs))
        out.append(peaks + start)
    return np.concatenate(out) if out else np.array([], dtype=int)


def ecg_hr_clean(r_peaks: np.ndarray, start: int, stop: int, fs: float, max_cv: float = 0.25) -> float:
    """Like ecg_hr_bpm, but returns NaN when beat intervals are too irregular to trust
    (protects against detector errors when there are no expert annotations)."""
    inside = r_peaks[(r_peaks >= start) & (r_peaks < stop)]
    rr = np.diff(inside) / fs
    rr = rr[(rr > 0.27) & (rr < 2.0)]
    if len(rr) < 3 or np.std(rr) / np.mean(rr) > max_cv:
        return float("nan")
    return float(60.0 / np.median(rr))
