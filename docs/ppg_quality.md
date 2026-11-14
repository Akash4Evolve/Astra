# PPG signal-quality model (real data)

**Question:** can we tell, from the optical pulse signal and motion sensors alone, when a PPG heart-rate reading is unreliable, so ASTRA's quality gate excludes it?

- Data: PhysioNet Pulse Transit Time PPG v1.1.0, 66 recordings, 22 people, activities: run, sit, walk
- Windows: 3207 x 10 s; PPG channel `pleth_3` (finger-mounted sensor); reference = ECG R-peak annotations
- Label: UNRELIABLE if |PPG HR - ECG HR| > 10 bpm (a stated assumption). 9.3% of windows are unreliable.
- Evaluation: 5-fold split **by person** (no person in both train and test)
- PPG HR here is a simple spectral estimate, deliberately basic.

## Results (out-of-fold, people the model never saw)

| Method | Balanced acc. | Unreliable caught (recall) | Precision | AUROC | Windows kept | HR error of kept windows |
|---|---|---|---|---|---|---|
| No gate | - | 0% | - | - | 100% | 4.9 bpm |
| Motion rule (baseline) | 0.65 | 95% | 13% | 0.60 | 33% | 1.6 bpm |
| Logistic regression | 0.81 | 79% | 33% | 0.90 | 78% | 2.2 bpm |
| Random forest | 0.90 | 90% | 48% | 0.95 | 83% | 1.6 bpm |

## By activity (random forest gate)

| Activity | Windows | Truly unreliable | Flagged by model | HR error, no gate | HR error, kept windows |
|---|---|---|---|---|---|
| run | 1072 | 6% | 16% | 3.6 bpm | 1.5 bpm |
| sit | 1068 | 1% | 2% | 1.6 bpm | 1.4 bpm |
| walk | 1067 | 21% | 34% | 9.4 bpm | 2.1 bpm |

## What the random forest relies on (importance, trained on all windows)

- `ppg_peak_ratio`: 0.39
- `ppg_vs_motion_bpm`: 0.22
- `ppg_kurtosis`: 0.19
- `gyro_std`: 0.09
- `acc_std`: 0.08
- `ppg_channel_disagree_bpm`: 0.02
- `ppg_skew`: 0.02

## Limits
- 22 healthy volunteers in a lab (sit / walk / run). Not astronauts, not microgravity, not the CrewBand device. The PPG sensor is on the finger, not the wrist. Results say the method works on this dataset only.
- The 10 bpm label threshold and 10 s window are choices; changing them changes the numbers.
- Small dataset: treat differences of a few percentage points as noise.
- This model judges signal reliability only. It says nothing about health.

Dataset: Mehrgardt, P., Khushi, M., Poon, S., & Withana, A. (2022). Pulse Transit Time PPG Dataset (version 1.1.0). PhysioNet. RRID:SCR_007345. https://doi.org/10.13026/jpan-6n92

# Adding WESAD (wrist PPG, different device and people)

- WESAD: 15 people, 8630 windows; wrist PPG (Empatica E4, 64 Hz), reference HR from chest ECG (700 Hz) with an automatic beat detector (no expert annotations)
- Conditions: amusement, baseline, meditation, other, stress, transient. Mostly seated or standing still: little motion.
- 30.5% of WESAD windows are unreliable (> 10 bpm off)
- Shared features only (WESAD has no gyroscope, one PPG channel): acc_std, ppg_peak_ratio, ppg_skew, ppg_kurtosis, ppg_vs_motion_bpm

## A. Cross-dataset test: trained on PhysioNet (finger), tested on WESAD (wrist)

The hardest and most honest test: new device, new body site, new people, never seen in training.

| Method | Balanced acc. | Unreliable caught (recall) | Precision | AUROC | Windows kept | HR error of kept windows |
|---|---|---|---|---|---|---|
| No gate | - | 0% | - | - | 100% | 11.6 bpm |
| Motion rule (baseline) | 0.51 | 1% | 80% | 0.80 | 99% | 11.4 bpm |
| Logistic regression | 0.76 | 97% | 49% | 0.81 | 39% | 2.2 bpm |
| Random forest | 0.81 | 88% | 59% | 0.87 | 54% | 3.6 bpm |

## B. Within WESAD (split by person)

| Method | Balanced acc. | Unreliable caught (recall) | Precision | AUROC | Windows kept | HR error of kept windows |
|---|---|---|---|---|---|---|
| No gate | - | 0% | - | - | 100% | 11.6 bpm |
| Motion rule (baseline) | 0.73 | 75% | 53% | 0.80 | 57% | 5.5 bpm |
| Logistic regression | 0.81 | 85% | 61% | 0.88 | 58% | 4.0 bpm |
| Random forest | 0.81 | 91% | 58% | 0.88 | 52% | 3.1 bpm |

## C. Combined PhysioNet + WESAD (split by person across both)

37 people, 11837 windows. The saved combined model is trained on all of these.

| Method | Balanced acc. | Unreliable caught (recall) | Precision | AUROC | Windows kept | HR error of kept windows |
|---|---|---|---|---|---|---|
| No gate | - | 0% | - | - | 100% | 9.7 bpm |
| Motion rule (baseline) | 0.65 | 70% | 37% | 0.64 | 53% | 5.7 bpm |
| Logistic regression | 0.82 | 86% | 56% | 0.88 | 62% | 3.4 bpm |
| Random forest | 0.84 | 91% | 57% | 0.90 | 60% | 2.5 bpm |

## Limits of the WESAD part
- Reference heart rate comes from an automatic ECG beat detector, so some labels may be wrong.
- WESAD is mostly seated or standing still, so it tests the quiet case far more than motion.
- Still healthy volunteers on Earth: not astronauts, not CrewBand.

Dataset: Schmidt, P. & Reiss, A. (2018). WESAD (Wearable Stress and Affect Detection) [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C57K5T
