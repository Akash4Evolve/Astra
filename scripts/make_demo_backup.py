"""Record backup demo material, in case the live demo fails on the day.

    python scripts/make_demo_backup.py

Writes to demo_backup/ (all data SIMULATED, no internet needed):
  demo_transcript.txt     full output of scripts/demo.py (the judge story, steps 1-7)
  crew_api_snapshot.json  API responses for the crew dataset as the frontend sees it:
                          alerts, and per crew member the dashboard, twin and trends
  README.md               what each file is and how to fall back

The other fallback needs nothing at all: the Astra frontend without VITE_API_URL runs in
demo mode on its bundled dataset (npm run app, then open http://localhost:4173).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "demo_backup"
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "ml" / "src"), str(ROOT / "backend")]

CREW = ("CDR-01", "FE-02", "MS-03")
DEVICE = {"X-ASTRA-Role": "device"}


def transcript() -> str:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    run = subprocess.run([sys.executable, str(ROOT / "scripts" / "demo.py"), "--interval", "0"],
                         cwd=str(ROOT), env=env, capture_output=True, text=True, encoding="utf-8", timeout=300)
    if run.returncode != 0:
        raise SystemExit(f"demo.py failed:\n{run.stdout}\n{run.stderr}")
    return run.stdout


def crew_snapshot(through_day: int = 143) -> dict:
    from fastapi.testclient import TestClient

    from app.main import create_app
    from serve_crew import load_days, CSV_PATH

    client = TestClient(create_app(cors_origins=[], require_roles=True))
    days = load_days(CSV_PATH, through_day)
    for day in sorted(days):
        r = client.post("/api/v1/measurements", json=days[day], headers=DEVICE)
        r.raise_for_status()
    snap: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": "SIMULATED crew dataset (Astra/src/data), days 1-%d, as served by scripts/serve_crew.py" % through_day,
        "alerts": client.get("/api/v1/alerts").json(),
        "crew": {},
    }
    for cid in CREW:
        snap["crew"][cid] = {
            "dashboard": client.get(f"/api/v1/astronauts/{cid}/dashboard").json(),
            "twin": client.get(f"/api/v1/astronauts/{cid}/twin").json(),
            "trends": client.get(f"/api/v1/astronauts/{cid}/trends",
                                 params={"parameter": ["heart_rate", "sleep_hours"]}).json(),
        }
    return snap


README = """# Backup demo material (all data SIMULATED)

Made by `python scripts/make_demo_backup.py` on {when}. Re-run it after code changes.

| File | Use it when |
|---|---|
| `demo_transcript.txt` | `python scripts/demo.py` won't run: walk through this output instead (steps 1-7 of the judge story). |
| `crew_api_snapshot.json` | The API won't start: these are the real responses for the crew dataset (alerts, dashboard, twin, trends per crew member). |

Zero-dependency fallback: the Astra frontend runs without any backend. In `Astra/`, remove `.env.local`
(or leave `VITE_API_URL` unset) and run `npm run app`, then open http://localhost:4173. It uses the bundled
crew dataset and its own alert rules, and every value is tagged Simulated.

Order of fallbacks on the day: live backend + frontend -> frontend alone (demo mode) -> this transcript and
snapshot -> the recorded video.
"""


def main() -> None:
    OUT.mkdir(exist_ok=True)
    print("Running scripts/demo.py ...")
    (OUT / "demo_transcript.txt").write_text(transcript(), encoding="utf-8")
    print("Snapshotting the crew API state ...")
    snap = crew_snapshot()
    (OUT / "crew_api_snapshot.json").write_text(json.dumps(snap, indent=1), encoding="utf-8")
    (OUT / "README.md").write_text(README.format(when=snap["generated_at"]), encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)}/: demo_transcript.txt, crew_api_snapshot.json "
          f"({len(snap['alerts'])} alerts), README.md")


if __name__ == "__main__":
    main()
