# Model card: PPG signal-quality gate (experimental)

| | |
|---|---|
| Model | `ppg_quality_rf[physionet_ptt+wesad]`, file `models/ppg_quality_combined_rf.joblib` |
| Type | Random forest classifier (scikit-learn), 5 hand-built features per 10 s window |
| Status | **Experimental, secondary signal.** Off the alert path. |
| Built by | ASTRA team, NASA Space Apps 2026 |
| Code | `ml/src/astra_ml/ppg_quality.py` (features), `ml/src/astra_ml/ppg_gate.py` (window path), `backend/app/experimental.py` (API), `ml/eval/train_ppg_quality.py` (training and evaluation) |
| Full results | `docs/ppg_quality.md` |

## What it does

A wrist pulse sensor (PPG) gives a heart rate, but motion and poor skin contact can make that number wrong. For one **10-second window** of PPG plus accelerometer data, the model estimates the probability that the PPG heart rate is **more than 10 bpm away from the true (ECG) heart rate**. At or above 0.5 the window is called `LIKELY_UNRELIABLE` and the suggested quality status is `SUSPECT`; below that it is `LIKELY_RELIABLE` / `VALID`.

**It judges the reading, not the person.** It says nothing about health, stress or fitness.

## Intended use

- A device or gateway sends a raw window to `POST /api/v1/experimental/ppg-quality` and uses the suggested status when it builds the heart-rate measurement it sends to `POST /api/v1/measurements`. ASTRA's alert engine already ignores any reading not marked `VALID`, so this is how the model would keep motion-corrupted readings out of the personal baseline.
- Demos and research on how much a learned gate improves on a simple motion rule.

## Out of scope

- Any health decision, diagnosis or alert. The endpoint never edits stored measurements and never creates or changes alerts; the tests check this.
- Devices, body sites or populations unlike the training data (see Limits), unless re-evaluated there.
- Windows that are not about 10 s long, or sampled below 20 Hz (PPG) / 10 Hz (accelerometer); the API rejects these.

## Inputs

| Input | Detail |
|---|---|
| `ppg` | One PPG channel, any units (all features are scale-free) |
| `ppg_fs` | Sampling rate in Hz, at least 20 |
| `acc_g` | Accelerometer `[x, y, z]` samples **in g** (divide m/s² by 9.80665) |
| `acc_fs` | Sampling rate in Hz, at least 10; may differ from `ppg_fs` |

Features (shared by both training datasets): accelerometer magnitude spread (`acc_std`), how concentrated the PPG spectrum is at one rate (`ppg_peak_ratio`), PPG skewness and kurtosis, and the distance between the PPG rate and the motion rate (`ppg_vs_motion_bpm`). The finger-only model (`ppg_quality_rf.joblib`) also needs a gyroscope and a second PPG channel, so the API refuses to load it for wrist windows.

## Training data

| Dataset | People | Windows | Sensor | Reference heart rate | Activities |
|---|---|---|---|---|---|
| PhysioNet Pulse Transit Time PPG v1.1.0 | 22 | 3207 | Finger PPG (green, `pleth_3`), 500 Hz | Expert ECG beat annotations | Sit, walk, run |
| WESAD (UCI) | 15 | 8630 | Wrist PPG (Empatica E4), 64 Hz | Chest ECG, automatic beat detector | Mostly seated: baseline, stress, amusement, meditation |

Label: unreliable if |PPG HR − ECG HR| > 10 bpm. 9.3% of PhysioNet windows and 30.5% of WESAD windows are unreliable.

## Evaluation (split by person: nobody appears in both training and test)

From `docs/ppg_quality.md`, out-of-fold:

| Setting | Balanced acc. | Bad windows caught | Precision | AUROC | Windows kept | HR error of kept windows (no gate) |
|---|---|---|---|---|---|---|
| Combined, 37 people (this model's setting) | 0.84 | 91% | 57% | 0.90 | 60% | 2.5 bpm (9.7) |
| Motion-rule baseline, same split | 0.65 | 70% | 37% | 0.64 | 53% | 5.7 bpm (9.7) |
| Trained on PhysioNet finger, tested on WESAD wrist | 0.81 | 88% | 59% | 0.87 | 54% | 3.6 bpm (11.6) |

How to read it: the gate catches about 9 in 10 bad windows, but about 4 in 10 windows it flags were actually fine, so it throws away usable data. The cross-dataset row (new device, body site and people) is the closest guide to how it might do on a new wristband, and it is weaker.

## Window-path check on real recordings

Run through `assess_window` (the same code path as the API) on five PhysioNet recordings, CSV export, accelerometer converted to g. These recordings **were in the training data**, so this checks the API path, not accuracy:

| Recording | Windows | Truly bad | Flagged | Bad caught | HR error before → after gate |
|---|---|---|---|---|---|
| s5_sit | 49 | 0% | 0% | – | 1.1 → 1.1 bpm |
| s5_walk | 49 | 0% | 2% | – | 1.3 → 1.3 bpm |
| s5_run | 55 | 7% | 7% | 4/4 | 3.9 → 1.1 bpm |
| s20_walk | 48 | 19% | 56% | 9/9 | 11.6 → 1.1 bpm |
| s12_walk | 48 | 81% | 58% | 20/39 | 36.2 → 41.9 bpm |

**Known failure mode (s12_walk):** when the PPG locks cleanly onto a wrong rate that is not the step rate, the signal looks like a good pulse, and the gate keeps it. A gate built only on signal shape cannot detect this; it needs a second opinion (a second PPG channel, or agreement with recent readings).

## Limits

- Healthy volunteers on Earth, 37 people. Not astronauts, not microgravity, not the CrewBand device. Fluid shifts in microgravity change the pulse waveform; that is untested.
- The PhysioNet sensor is on the finger, not the wrist. WESAD is wrist-worn but mostly still, so the "wrist + heavy motion" case is barely covered.
- WESAD labels come from an automatic ECG beat detector, so some are wrong.
- The 10 bpm label, 10 s window and 0.5 threshold are choices; changing them changes every number above.
- Small dataset: treat differences of a few percentage points as noise.
- `joblib` model files are pickles and can run code when loaded. Only load model files this project produced.

## Operating it

- Model file: `models/ppg_quality_combined_rf.joblib`, or set `ASTRA_PPG_MODEL` to another path. If the file or scikit-learn is missing, only this endpoint is disabled (`GET` reports why, `POST` returns 503); the rest of ASTRA works.
- `GET /api/v1/experimental/ppg-quality` reports the loaded model, its features and its limits.
- Every assessment tied to an `astronaut_id` is written to the audit trail as `PPG_QUALITY_ASSESSED`, with the verdict and model ID.
- Retrain: `python ml/eval/train_ppg_quality.py --with-wesad` (needs the raw datasets; see `README_DATA.txt`). This rewrites `docs/ppg_quality.md` and both model files; update this card's numbers afterwards.

## Citations

- Mehrgardt, P., Khushi, M., Poon, S., & Withana, A. (2022). Pulse Transit Time PPG Dataset (version 1.1.0). PhysioNet. https://doi.org/10.13026/jpan-6n92
- Schmidt, P. & Reiss, A. (2018). WESAD (Wearable Stress and Affect Detection). UCI Machine Learning Repository. https://doi.org/10.24432/C57K5T
