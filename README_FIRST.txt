Fix pack: replaces three files with the correct versions.
  ml\src\astra_ml\models.py   (adds sleep_hours + PUBLIC_RESEARCH)
  ml\src\astra_ml\alerts.py   (adds sleep_hours label/domain)
  backend\app\store.py        (adds check-ins, actions, device methods)
Unzip into the repo root with -Force, delete ml\src\astra_ml\evalution.py, then run: python -m pytest -v
