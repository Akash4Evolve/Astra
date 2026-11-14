ASTRA - PPG signal-quality model (trained on real PhysioNet data)
==================================================================
Extract into your NASA project folder:

  Expand-Archive -Path "$HOME\Downloads\astra_ppg_quality.zip" -DestinationPath . -Force

New files only (nothing replaced):
  ml\src\astra_ml\ppg_quality.py     windows, labels, features
  ml\eval\train_ppg_quality.py       training + person-wise evaluation + report
  ml\tests\test_ppg_quality.py       5 tests on fake recordings

Then:
  python -m pytest -q                              -> expect 124 passed
  python ml\eval\train_ppg_quality.py --limit 6    -> quick check (about 10 s)
  python ml\eval\train_ppg_quality.py              -> full training (a few minutes)

Outputs: docs\ppg_quality.md (report), models\ppg_quality_rf.joblib (model),
         data\processed\ppg_windows_*.csv (feature cache)
Add data/processed/ and models/ to .gitignore.
