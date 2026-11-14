ASTRA - automatic dataset download
===================================
Extract into your NASA project folder:
  Expand-Archive -Path "$HOME\Downloads\astra_download.zip" -DestinationPath . -Force

Then (needs internet):
  python -m pytest -q                         -> expect 140 passed
  python scripts\download_datasets.py         -> NASA DONKI + WESAD (about 2.5 GB)

Result:
  data\raw\nasa_radiation\SEP.json SEP.csv RBE.json RBE.csv CME.json CME.csv FLR.json FLR.csv
  data\raw\wesad\WESAD\S2\S2.pkl ... (15 subjects)
  data\metadata\download_log.json

Only one part:  --nasa   or   --wesad
If the WESAD link fails: download the ZIP by hand, then
  python scripts\download_datasets.py --wesad --wesad-zip "C:\path\to\WESAD.zip"
