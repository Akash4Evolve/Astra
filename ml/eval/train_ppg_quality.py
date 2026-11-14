"""Train and evaluate the PPG signal-quality model on PhysioNet Pulse Transit Time PPG v1.1.0.

    python ml/eval/train_ppg_quality.py                       # full run (all 66 records)
    python ml/eval/train_ppg_quality.py --limit 6             # quick smoke test
    python ml/eval/train_ppg_quality.py --ppg pleth_1         # try another PPG channel (red)
    python ml/eval/train_ppg_quality.py --with-wesad          # add WESAD: cross-dataset + combined model

Outputs:
    data/processed/ppg_windows_<channel>.csv   feature table (cached; delete it to rebuild)
    docs/ppg_quality.md                        evaluation report for the slides
    models/ppg_quality_rf.joblib               random forest trained on all PhysioNet windows
    models/ppg_quality_combined_rf.joblib      (--with-wesad) trained on PhysioNet + WESAD

Evaluation is split BY PERSON (GroupKFold): nobody's windows appear in both train and test.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml" / "src"))

from astra_ml.ppg_quality import (  # noqa: E402
    COMMON_FEATURES, DEFAULT_ERROR_BPM, FEATURES, WINDOW_S, windows_for_record,
)

DEFAULT_DATA = ROOT / "data" / "raw" / "physionet" / "pulse_transit_time_ppg"
DEFAULT_WESAD = ROOT / "data" / "raw" / "wesad"
WESAD_CITATION = (
    "Schmidt, P. & Reiss, A. (2018). WESAD (Wearable Stress and Affect Detection) [Dataset]. "
    "UCI Machine Learning Repository. https://doi.org/10.24432/C57K5T"
)
CITATION = (
    "Mehrgardt, P., Khushi, M., Poon, S., & Withana, A. (2022). Pulse Transit Time PPG Dataset "
    "(version 1.1.0). PhysioNet. RRID:SCR_007345. https://doi.org/10.13026/jpan-6n92"
)


# ------------------------------------------------------------------ data
def build_table(data_dir: Path, ppg: str, window_s: float, limit: int | None) -> pd.DataFrame:
    import wfdb  # imported here so the rest of the module works without it

    records_file = data_dir / "RECORDS"
    if not records_file.exists():
        raise SystemExit(f"RECORDS not found in {data_dir}. Is the download complete?")
    records = [r.strip() for r in records_file.read_text().splitlines() if r.strip()]
    if limit:
        records = records[:limit]

    rows = []
    t0 = time.time()
    for i, rec in enumerate(records, 1):
        path = str(data_dir / rec)
        r = wfdb.rdrecord(path)
        ann = wfdb.rdann(path, "atr")
        wins = windows_for_record(rec, r.p_signal, list(r.sig_name), float(r.fs),
                                  np.asarray(ann.sample), ppg_channel=ppg, window_s=window_s)
        for w in wins:
            rows.append({"record": w.record, "subject": w.subject, "activity": w.activity,
                         "start_s": w.start_s, "ecg_hr": w.ecg_hr, "ppg_hr": w.ppg_hr,
                         "error_bpm": w.error_bpm, **w.features})
        print(f"  [{i:2d}/{len(records)}] {rec:<10} {len(wins):3d} windows  ({time.time() - t0:5.1f} s)")
    if not rows:
        raise SystemExit("No usable windows were produced.")
    return pd.DataFrame(rows)


def build_wesad_table(wesad_dir: Path, window_s: float, limit: int | None) -> pd.DataFrame:
    from astra_ml.wesad import find_subjects, load_subject, windows_for_subject

    pkls = find_subjects(wesad_dir)
    if not pkls:
        raise SystemExit(f"No WESAD subjects found under {wesad_dir} (expected .../WESAD/S2/S2.pkl).")
    if limit:
        pkls = pkls[:limit]
    rows = []
    t0 = time.time()
    for i, pkl in enumerate(pkls, 1):
        wins = windows_for_subject(load_subject(pkl), window_s)
        for w in wins:
            rows.append({"record": w.record, "subject": w.subject, "activity": w.activity,
                         "start_s": w.start_s, "ecg_hr": w.ecg_hr, "ppg_hr": w.ppg_hr,
                         "error_bpm": w.error_bpm, **w.features})
        print(f"  [{i:2d}/{len(pkls)}] {pkl.stem:<4} {len(wins):4d} windows  ({time.time() - t0:5.1f} s)")
    if not rows:
        raise SystemExit("No usable WESAD windows were produced.")
    return pd.DataFrame(rows)


def cached(path: Path, rebuild: bool, build) -> pd.DataFrame:
    if path.exists() and not rebuild:
        print(f"Using cached features: {path}")
        return pd.read_csv(path)
    df = build()
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return df


# ------------------------------------------------------------------ models
def rule_threshold(acc_std: np.ndarray, y: np.ndarray) -> float:
    """Simple baseline: 'unreliable if motion > t', t chosen on the TRAINING fold only."""
    from sklearn.metrics import balanced_accuracy_score

    best_t, best = float(np.median(acc_std)), -1.0
    for t in np.unique(np.quantile(acc_std, np.linspace(0.02, 0.98, 49))):
        score = balanced_accuracy_score(y, (acc_std > t).astype(int))
        if score > best:
            best_t, best = float(t), score
    return best_t


def make_models():
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    return {
        "Logistic regression": make_pipeline(
            StandardScaler(), LogisticRegression(class_weight="balanced", max_iter=2000)),
        "Random forest": RandomForestClassifier(
            n_estimators=300, max_depth=6, min_samples_leaf=5, class_weight="balanced",
            random_state=0, n_jobs=-1),
    }


def cross_validate(df: pd.DataFrame, y: np.ndarray, folds: int,
                   features: tuple[str, ...] = FEATURES) -> dict[str, dict[str, np.ndarray]]:
    from sklearn.model_selection import GroupKFold

    X = df[list(features)].to_numpy(float)
    groups = df["subject"].to_numpy()
    n_folds = min(folds, len(np.unique(groups)))
    if n_folds < 2:
        raise SystemExit("Need at least 2 different people for a person-wise split.")

    out = {name: {"pred": np.zeros(len(y), int), "score": np.zeros(len(y))}
           for name in ["Motion rule (baseline)", *make_models()]}
    for train, test in GroupKFold(n_splits=n_folds).split(X, y, groups):
        assert not set(groups[train]) & set(groups[test])  # person-wise split
        acc_i = features.index("acc_std")
        t = rule_threshold(X[train, acc_i], y[train])
        out["Motion rule (baseline)"]["pred"][test] = (X[test, acc_i] > t).astype(int)
        out["Motion rule (baseline)"]["score"][test] = X[test, acc_i]
        for name, model in make_models().items():
            if len(np.unique(y[train])) < 2:
                out[name]["pred"][test] = y[train][0]
                out[name]["score"][test] = float(y[train][0])
                continue
            model.fit(X[train], y[train])
            out[name]["pred"][test] = model.predict(X[test])
            out[name]["score"][test] = model.predict_proba(X[test])[:, 1]
    return out


def transfer(train: pd.DataFrame, y_train: np.ndarray, test: pd.DataFrame,
             features: tuple[str, ...] = COMMON_FEATURES) -> dict[str, dict[str, np.ndarray]]:
    """Train on one dataset, test on another (different device, body site and people)."""
    Xtr, Xte = train[list(features)].to_numpy(float), test[list(features)].to_numpy(float)
    acc_i = features.index("acc_std")
    t = rule_threshold(Xtr[:, acc_i], y_train)
    out = {"Motion rule (baseline)": {"pred": (Xte[:, acc_i] > t).astype(int), "score": Xte[:, acc_i]}}
    for name, model in make_models().items():
        model.fit(Xtr, y_train)
        out[name] = {"pred": model.predict(Xte), "score": model.predict_proba(Xte)[:, 1]}
    return out


def metrics(y: np.ndarray, pred: np.ndarray, score: np.ndarray, err: np.ndarray) -> dict[str, float]:
    from sklearn.metrics import balanced_accuracy_score, precision_score, recall_score, roc_auc_score

    kept = pred == 0
    return {
        "balanced_acc": balanced_accuracy_score(y, pred),
        "recall": recall_score(y, pred, zero_division=0),      # unreliable windows caught
        "precision": precision_score(y, pred, zero_division=0),
        "auroc": roc_auc_score(y, score) if len(np.unique(y)) == 2 else float("nan"),
        "kept_share": kept.mean(),
        "mae_kept": float(np.mean(err[kept])) if kept.any() else float("nan"),
    }


# ------------------------------------------------------------------ report
def render(df: pd.DataFrame, y: np.ndarray, results: dict, ppg: str, error_bpm: float,
           window_s: float, folds: int, importances: dict[str, float]) -> str:
    err = df["error_bpm"].to_numpy()
    n_subj = df["subject"].nunique()
    L = [
        "# PPG signal-quality model (real data)",
        "",
        "**Question:** can we tell, from the optical pulse signal and motion sensors alone, when a PPG heart-rate reading is "
        "unreliable, so ASTRA's quality gate excludes it?",
        "",
        f"- Data: PhysioNet Pulse Transit Time PPG v1.1.0, {df['record'].nunique()} recordings, "
        f"{n_subj} people, activities: {', '.join(sorted(df['activity'].unique()))}",
        f"- Windows: {len(df)} x {window_s:g} s; PPG channel `{ppg}` (finger-mounted sensor); "
        "reference = ECG R-peak annotations",
        f"- Label: UNRELIABLE if |PPG HR - ECG HR| > {error_bpm:g} bpm (a stated assumption). "
        f"{y.mean():.1%} of windows are unreliable.",
        f"- Evaluation: {min(folds, n_subj)}-fold split **by person** (no person in both train and test)",
        "- PPG HR here is a simple spectral estimate, deliberately basic.",
        "",
        "## Results (out-of-fold, people the model never saw)",
        "",
        "| Method | Balanced acc. | Unreliable caught (recall) | Precision | AUROC | Windows kept | HR error of kept windows |",
        "|---|---|---|---|---|---|---|",
        f"| No gate | - | 0% | - | - | 100% | {np.mean(err):.1f} bpm |",
    ]
    for name, r in results.items():
        m = metrics(y, r["pred"], r["score"], err)
        L.append(f"| {name} | {m['balanced_acc']:.2f} | {m['recall']:.0%} | {m['precision']:.0%} | "
                 f"{m['auroc']:.2f} | {m['kept_share']:.0%} | {m['mae_kept']:.1f} bpm |")

    rf = results["Random forest"]["pred"]
    L += ["", "## By activity (random forest gate)", "",
          "| Activity | Windows | Truly unreliable | Flagged by model | HR error, no gate | HR error, kept windows |",
          "|---|---|---|---|---|---|"]
    for act in sorted(df["activity"].unique()):
        m = (df["activity"] == act).to_numpy()
        kept = m & (rf == 0)
        kept_err = f"{err[kept].mean():.1f} bpm" if kept.any() else "n/a (all flagged)"
        L.append(f"| {act} | {m.sum()} | {y[m].mean():.0%} | {rf[m].mean():.0%} | "
                 f"{err[m].mean():.1f} bpm | {kept_err} |")

    L += ["", "## What the random forest relies on (importance, trained on all windows)", ""]
    for f, v in sorted(importances.items(), key=lambda kv: -kv[1]):
        L.append(f"- `{f}`: {v:.2f}")

    L += [
        "",
        "## Limits",
        f"- {n_subj} healthy volunteers in a lab (sit / walk / run). Not astronauts, not microgravity, "
        "not the CrewBand device. The PPG sensor is on the finger, not the wrist. "
        "Results say the method works on this dataset only.",
        "- The 10 bpm label threshold and 10 s window are choices; changing them changes the numbers.",
        "- Small dataset: treat differences of a few percentage points as noise.",
        "- This model judges signal reliability only. It says nothing about health.",
        "",
        f"Dataset: {CITATION}",
        "",
    ]
    return "\n".join(L)


def results_table(y: np.ndarray, results: dict, err: np.ndarray) -> list[str]:
    L = ["| Method | Balanced acc. | Unreliable caught (recall) | Precision | AUROC | Windows kept | HR error of kept windows |",
         "|---|---|---|---|---|---|---|",
         f"| No gate | - | 0% | - | - | 100% | {np.mean(err):.1f} bpm |"]
    for name, r in results.items():
        m = metrics(y, r["pred"], r["score"], err)
        L.append(f"| {name} | {m['balanced_acc']:.2f} | {m['recall']:.0%} | {m['precision']:.0%} | "
                 f"{m['auroc']:.2f} | {m['kept_share']:.0%} | {m['mae_kept']:.1f} bpm |")
    return L


def render_wesad(phys: pd.DataFrame, wes: pd.DataFrame, y_wes: np.ndarray, cross: dict,
                 within: dict | None, both: pd.DataFrame, y_both: np.ndarray, combined: dict,
                 error_bpm: float) -> str:
    L = [
        "",
        "# Adding WESAD (wrist PPG, different device and people)",
        "",
        f"- WESAD: {wes['subject'].nunique()} people, {len(wes)} windows; wrist PPG (Empatica E4, 64 Hz), "
        "reference HR from chest ECG (700 Hz) with an automatic beat detector (no expert annotations)",
        f"- Conditions: {', '.join(sorted(wes['activity'].unique()))}. Mostly seated or standing still: little motion.",
        f"- {y_wes.mean():.1%} of WESAD windows are unreliable (> {error_bpm:g} bpm off)",
        f"- Shared features only (WESAD has no gyroscope, one PPG channel): {', '.join(COMMON_FEATURES)}",
        "",
        "## A. Cross-dataset test: trained on PhysioNet (finger), tested on WESAD (wrist)",
        "",
        "The hardest and most honest test: new device, new body site, new people, never seen in training.",
        "",
        *results_table(y_wes, cross, wes["error_bpm"].to_numpy()),
    ]
    if within is not None:
        L += ["", "## B. Within WESAD (split by person)", "",
              *results_table(y_wes, within, wes["error_bpm"].to_numpy())]
    L += [
        "", "## C. Combined PhysioNet + WESAD (split by person across both)", "",
        f"{both['subject'].nunique()} people, {len(both)} windows. "
        "The saved combined model is trained on all of these.", "",
        *results_table(y_both, combined, both["error_bpm"].to_numpy()),
        "",
        "## Limits of the WESAD part",
        "- Reference heart rate comes from an automatic ECG beat detector, so some labels may be wrong.",
        "- WESAD is mostly seated or standing still, so it tests the quiet case far more than motion.",
        "- Still healthy volunteers on Earth: not astronauts, not CrewBand.",
        "",
        f"Dataset: {WESAD_CITATION}",
        "",
    ]
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    ap.add_argument("--ppg", default="pleth_3",
                    help="PPG channel. pleth_1/2/3 = red/infrared/green at fingertip, 4/5/6 = same at finger base. "
                         "Default green (pleth_3), the colour most wristbands use.")
    ap.add_argument("--error-bpm", type=float, default=DEFAULT_ERROR_BPM)
    ap.add_argument("--window", type=float, default=WINDOW_S)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--limit", type=int, default=None, help="only the first N records (smoke test)")
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "ppg_quality.md")
    ap.add_argument("--rebuild", action="store_true", help="ignore the cached feature tables")
    ap.add_argument("--with-wesad", action="store_true", help="add WESAD: cross-dataset test + combined model")
    ap.add_argument("--wesad-dir", type=Path, default=DEFAULT_WESAD)
    ap.add_argument("--wesad-limit", type=int, default=None, help="only the first N WESAD subjects")
    args = ap.parse_args()

    cache = ROOT / "data" / "processed" / f"ppg_windows_{args.ppg}_{args.window:g}s_{args.limit or 'all'}.csv"
    print(f"PhysioNet: {args.data_dir}")
    df = cached(cache, args.rebuild, lambda: build_table(args.data_dir, args.ppg, args.window, args.limit))

    y = (df["error_bpm"].to_numpy() > args.error_bpm).astype(int)
    if len(np.unique(y)) < 2:
        raise SystemExit(f"All windows have the same label at {args.error_bpm} bpm; try another --error-bpm.")

    print(f"\nTraining with a person-wise split ({df['subject'].nunique()} people, {len(df)} windows) ...")
    results = cross_validate(df, y, args.folds)

    from joblib import dump
    rf = make_models()["Random forest"].fit(df[list(FEATURES)].to_numpy(float), y)
    importances = dict(zip(FEATURES, rf.feature_importances_))
    model_path = ROOT / "models" / "ppg_quality_rf.joblib"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    dump({"model": rf, "features": FEATURES, "ppg_channel": args.ppg, "error_bpm": args.error_bpm,
          "window_s": args.window}, model_path)

    report = render(df, y, results, args.ppg, args.error_bpm, args.window, args.folds, importances)

    if args.with_wesad:
        wcache = ROOT / "data" / "processed" / f"wesad_windows_{args.window:g}s_{args.wesad_limit or 'all'}.csv"
        print(f"\nWESAD: {args.wesad_dir}")
        wes = cached(wcache, args.rebuild, lambda: build_wesad_table(args.wesad_dir, args.window, args.wesad_limit))
        y_wes = (wes["error_bpm"].to_numpy() > args.error_bpm).astype(int)
        if len(np.unique(y_wes)) < 2:
            print("WESAD windows all have the same label; skipping WESAD-only metrics.")
        print("Cross-dataset test (train PhysioNet -> test WESAD) ...")
        cross = transfer(df, y, wes)
        within = cross_validate(wes, y_wes, args.folds, COMMON_FEATURES) if len(np.unique(y_wes)) == 2 else None
        both = pd.concat([df, wes], ignore_index=True)
        y_both = (both["error_bpm"].to_numpy() > args.error_bpm).astype(int)
        print("Combined person-wise evaluation ...")
        combined = cross_validate(both, y_both, args.folds, COMMON_FEATURES)
        rf_all = make_models()["Random forest"].fit(both[list(COMMON_FEATURES)].to_numpy(float), y_both)
        dump({"model": rf_all, "features": COMMON_FEATURES, "datasets": ["physionet_ptt", "wesad"],
              "ppg_channel": args.ppg, "error_bpm": args.error_bpm, "window_s": args.window},
             ROOT / "models" / "ppg_quality_combined_rf.joblib")
        report += render_wesad(df, wes, y_wes, cross, within, both, y_both, combined, args.error_bpm)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    print("\n" + report)
    print(f"Saved report -> {args.out}\nSaved model  -> {model_path}")
    if args.with_wesad:
        print(f"Saved model  -> {ROOT / 'models' / 'ppg_quality_combined_rf.joblib'}")


if __name__ == "__main__":
    main()
