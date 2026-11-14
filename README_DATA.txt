ASTRA - WESAD training + GOES/DONKI fetch
==========================================
Extract into your NASA project folder:

  Expand-Archive -Path "$HOME\Downloads\astra_wesad_spaceweather.zip" -DestinationPath . -Force

Replaced (same results for PhysioNet, more options):
  ml\src\astra_ml\ppg_quality.py, ml\eval\train_ppg_quality.py
New:
  ml\src\astra_ml\wesad.py, scripts\fetch_space_weather.py,
  ml\tests\test_wesad.py, backend\tests\test_space_weather.py

1) python -m pytest -q                                   -> expect 133 passed
2) WESAD must be at data\raw\wesad\WESAD\S2\S2.pkl (S3, S4, ...)
   python ml\eval\train_ppg_quality.py --with-wesad --wesad-limit 2   (quick check)
   python ml\eval\train_ppg_quality.py --with-wesad                   (full)
3) python scripts\fetch_space_weather.py                 (needs internet)
   optional: $env:NASA_API_KEY = "your key from api.nasa.gov"
