"""WESAD loader + cross-dataset training, tested on FAKE WESAD-shaped pickles (no real data needed)."""
import importlib.util
import pickle
import sys
from pathlib import Path

import numpy as np
import pytest

from astra_ml.ppg_quality import COMMON_FEATURES, detect_r_peaks, ecg_hr_clean
from astra_ml.wesad import FS_ACC, FS_BVP, FS_ECG, find_subjects, load_subject, windows_for_subject


def fake_ecg(seconds: float, hr: float, rng, invert: bool = False) -> tuple[np.ndarray, np.ndarray]:
    t = np.arange(int(seconds * FS_ECG)) / FS_ECG
    beats = np.arange(0.3, seconds, 60 / hr)
    ecg = 0.2 * np.sin(2 * np.pi * 0.2 * t) + rng.normal(0, 0.02, len(t))  # baseline wander + noise
    for b in beats:
        ecg += 1.2 * np.exp(-0.5 * ((t - b) / 0.012) ** 2)  # QRS spike
    return (-ecg if invert else ecg), (beats * FS_ECG).astype(int)


def fake_subject(n: int, seconds: float = 120.0, motion_from: float = 60.0) -> dict:
    """First half seated and clean; second half with arm motion that corrupts the wrist PPG."""
    rng = np.random.default_rng(n)
    hr = 70 + n
    ecg, _ = fake_ecg(seconds, hr, rng, invert=(n % 2 == 0))
    tb = np.arange(int(seconds * FS_BVP)) / FS_BVP
    ta = np.arange(int(seconds * FS_ACC)) / FS_ACC
    step = 2.2  # Hz
    moving_b, moving_a = tb >= motion_from, ta >= motion_from
    bvp = np.sin(2 * np.pi * hr / 60 * tb) + 4.0 * moving_b * np.sin(2 * np.pi * step * tb) + rng.normal(0, 0.1, len(tb))
    acc = np.zeros((len(ta), 3))
    acc[:, 2] = 64.0
    acc += 64.0 * 0.6 * (moving_a * np.sin(2 * np.pi * step * ta))[:, None] + rng.normal(0, 0.3, (len(ta), 3))
    label = np.where(np.arange(len(ecg)) / FS_ECG < seconds / 2, 1, 2)
    return {"subject": f"S{n}",
            "signal": {"chest": {"ECG": ecg[:, None], "ACC": np.zeros((len(ecg), 3))},
                       "wrist": {"BVP": bvp[:, None], "ACC": acc, "EDA": np.zeros((4, 1)), "TEMP": np.zeros((4, 1))}},
            "label": label}


def write_fake_wesad(root: Path, subjects=(2, 3, 4, 5, 6)) -> Path:
    base = root / "WESAD"
    for n in subjects:
        folder = base / f"S{n}"
        folder.mkdir(parents=True)
        with open(folder / f"S{n}.pkl", "wb") as f:
            pickle.dump(fake_subject(n), f)
    return root


def test_r_peak_detector_handles_both_polarities():
    rng = np.random.default_rng(0)
    for invert in (False, True):
        ecg, truth = fake_ecg(30, 75, rng, invert)
        found = detect_r_peaks(ecg, FS_ECG)
        assert abs(len(found) - len(truth)) <= 1
        assert abs(ecg_hr_clean(found, 0, len(ecg), FS_ECG) - 75) < 1.0


def test_irregular_beats_are_rejected():
    peaks = (np.array([0, 0.8, 1.1, 2.6, 2.9, 4.5]) * FS_ECG).astype(int)
    assert np.isnan(ecg_hr_clean(peaks, 0, int(5 * FS_ECG), FS_ECG))


def test_loader_finds_subjects_and_windows_are_aligned(tmp_path):
    root = write_fake_wesad(tmp_path, subjects=(10, 2, 3))
    pkls = find_subjects(root)
    assert [p.stem for p in pkls] == ["S2", "S3", "S10"]  # numeric order, works with or without /WESAD
    assert find_subjects(root / "WESAD") == pkls
    wins = windows_for_subject(load_subject(pkls[0]))
    assert len(wins) == 12 and wins[0].subject == "wesad_S2"
    assert {w.activity for w in wins} == {"baseline", "stress"}
    clean, moving = wins[:5], wins[7:]
    assert np.mean([w.error_bpm for w in clean]) < 3
    assert np.mean([w.error_bpm for w in moving]) > 10
    assert np.mean([w.features["acc_std"] for w in moving]) > 10 * np.mean([w.features["acc_std"] for w in clean])
    assert set(wins[0].features) == set(COMMON_FEATURES)


def test_bad_layout_is_reported(tmp_path):
    folder = tmp_path / "WESAD" / "S2"
    folder.mkdir(parents=True)
    with open(folder / "S2.pkl", "wb") as f:
        pickle.dump({"signal": {}}, f)
    with pytest.raises(ValueError, match="unexpected WESAD layout"):
        load_subject(folder / "S2.pkl")


def test_cross_dataset_and_combined_training(tmp_path):
    pytest.importorskip("sklearn")
    path = Path(__file__).resolve().parents[1] / "eval" / "train_ppg_quality.py"
    spec = importlib.util.spec_from_file_location("train_ppg_quality_w", path)
    tr = importlib.util.module_from_spec(spec)
    sys.modules["train_ppg_quality_w"] = tr
    spec.loader.exec_module(tr)

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_ppg_quality import NAMES, FS, fake_record
    import pandas as pd
    from astra_ml.ppg_quality import windows_for_record

    rows = []
    for s in range(1, 6):
        for act in ("sit", "walk", "run"):
            sig, peaks = fake_record(s, act)
            for w in windows_for_record(f"s{s}_{act}", sig, NAMES, FS, peaks):
                rows.append({"subject": w.subject, "activity": w.activity, "error_bpm": w.error_bpm, **w.features})
    phys = pd.DataFrame(rows)
    y_phys = (phys["error_bpm"] > 10).astype(int).to_numpy()

    wes = tr.build_wesad_table(write_fake_wesad(tmp_path), 10.0, None)
    y_wes = (wes["error_bpm"] > 10).astype(int).to_numpy()
    assert wes["subject"].nunique() == 5 and 0 < y_wes.mean() < 1

    cross = tr.transfer(phys, y_phys, wes)
    rf = tr.metrics(y_wes, cross["Random forest"]["pred"], cross["Random forest"]["score"], wes["error_bpm"].to_numpy())
    assert rf["mae_kept"] < wes["error_bpm"].mean()

    both = pd.concat([phys, wes], ignore_index=True)
    y_both = (both["error_bpm"] > 10).astype(int).to_numpy()
    combined = tr.cross_validate(both, y_both, 5, COMMON_FEATURES)  # asserts no person overlap
    report = tr.render_wesad(phys, wes, y_wes, cross, None, both, y_both, combined, 10)
    assert "Cross-dataset test" in report and "10.24432/C57K5T" in report and "automatic ECG beat detector" in report
