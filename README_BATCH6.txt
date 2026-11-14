ASTRA - Batch 6: CrewBand simulator + one-command demo
======================================================
Extract into your NASA project folder (the one with backend\ and ml\):

  Expand-Archive -Path "$HOME\Downloads\astra_batch6.zip" -DestinationPath . -Force

New files only (nothing of yours is replaced):
  scripts\crewband_sim.py         simulator that streams SIMULATED data to the API
  scripts\demo.py                 the whole judge story in one command
  backend\tests\test_simulator.py 5 tests

Then:
  python -m pytest -q             -> expect 119 passed
  python scripts\demo.py          -> full demo, writes docs\latency.md
You can delete this README after reading it.
