"""Show what the trained PPG quality model outputs, window by window, for one recording.

    python ml/eval/predict_ppg_quality.py s5_walk
    python ml/eval/predict_ppg_quality.py s5_walk --rows 15

For each 10 s window it prints the ECG (reference) heart rate, the PPG heart rate, the
model's probability that the PPG reading is unreliable, and the gate decision.
Run train_ppg_quality.py first; it saves models/ppg_quality_rf.joblib.
Note: if this recording was in the training data, the model has seen it before.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml" / "src"))

from astra_ml.ppg_quality import feature_matrix, windows_for_record  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Per-window output of the PPG quality model")
    ap.add_argument("record", help="e.g. s5_walk")
    ap.add_argument("--data-dir", type=Path, default=ROOT / "data" / "raw" / "physionet" / "pulse_transit_time_ppg")
    ap.add_argument("--model", type=Path, default=ROOT / "models" / "ppg_quality_rf.joblib")
    ap.add_argument("--rows", type=int, default=20, help="windows to print")
    args = ap.parse_args()

    import wfdb
    from joblib import load

    if not args.model.exists():
        raise SystemExit("No trained model found. Run: python ml/eval/train_ppg_quality.py")
    bundle = load(args.model)
    path = str(args.data_dir / args.record)
    r = wfdb.rdrecord(path)
    ann = wfdb.rdann(path, "atr")
    wins = windows_for_record(args.record, r.p_signal, list(r.sig_name), float(r.fs), np.asarray(ann.sample),
                              ppg_channel=bundle["ppg_channel"], window_s=bundle["window_s"])
    proba = bundle["model"].predict_proba(feature_matrix(wins))[:, 1]
    limit = bundle["error_bpm"]

    print(f"{args.record}: {len(wins)} windows, channel {bundle['ppg_channel']}, "
          f"'truly bad' = PPG off by > {limit:g} bpm\n")
    print(" time   ECG HR   PPG HR   error   P(unreliable)  gate decision         truth")
    for w, p in list(zip(wins, proba))[: args.rows]:
        decision = "EXCLUDE (SUSPECT)" if p >= 0.5 else "use (VALID)"
        truth = "bad" if w.error_bpm > limit else "ok"
        mark = "" if (p >= 0.5) == (truth == "bad") else "  <- model wrong"
        print(f"{w.start_s:5.0f}s  {w.ecg_hr:6.1f}  {w.ppg_hr:7.1f}  {w.error_bpm:6.1f}      "
              f"{p:5.2f}       {decision:<20}  {truth}{mark}")

    kept = proba < 0.5
    err = np.array([w.error_bpm for w in wins])
    print(f"\nwhole recording: {kept.mean():.0%} of windows kept; average error "
          f"{err.mean():.1f} bpm before the gate, {err[kept].mean() if kept.any() else float('nan'):.1f} bpm after")


if __name__ == "__main__":
    main()
