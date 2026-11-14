"""Run the ASTRA API for the Astra frontend, preloaded with the simulated crew dataset.

The frontend (Astra/) and the backend read the same CSV
(Astra/src/data/astronaut_health_simulated.csv), so both show the same crew and days.
The backend's analytics cover resting heart rate and sleep duration, so only those two
columns are sent; every record is labelled SIMULATED. Readings keep the CSV's own dates
(mission day 1 = 2027-03-01), so a mission day means the same thing on both sides.

Days are sent one at a time, so the backend's alert engine sees the data arrive in order
and raises alerts at the point they would have happened.

    python scripts/serve_crew.py                    # API on :8000, crew data through day 143
    python scripts/serve_crew.py --through-day 180  # the whole mission
    python scripts/serve_crew.py --seed-only --url http://127.0.0.1:8000   # seed a running server

The store is in memory: restart this script and the data (and any check-ins or actions
sent from the frontend) start over.
"""
from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import time
import uuid
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from crewband_sim import HttpApi  # noqa: E402

CSV_PATH = ROOT / "Astra" / "src" / "data" / "astronaut_health_simulated.csv"
FRONTEND_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173"
# Same reading times the frontend uses for these columns (UTC hour, minute).
COLUMNS = {
    "heart_rate": ("heart_rate_rest_bpm", "bpm", "07:10"),
    "sleep_hours": ("sleep_hours", "h", "06:10"),
}
NS = uuid.UUID("6f1d3a52-7c1e-4b8e-9a51-2f0c6a7d9e10")


def load_days(path: Path, through_day: int) -> dict[int, list[dict]]:
    by_day: dict[int, list[dict]] = defaultdict(list)
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            day = int(row["mission_day"])
            if day > through_day:
                continue
            for parameter, (col, unit, hhmm) in COLUMNS.items():
                if row.get(col) in (None, ""):
                    continue
                key = f"{row['astronaut_id']}:{day}:{parameter}"
                by_day[day].append({
                    # Fixed IDs, so seeding twice never stores a reading twice.
                    "record_id": str(uuid.uuid5(NS, key)),
                    "astronaut_id": row["astronaut_id"],
                    "device_id": f"CREWBAND-{row['astronaut_id']}",
                    "timestamp_utc": f"{row['date']}T{hhmm}:00Z",
                    "parameter": parameter,
                    "value": float(row[col]),
                    "unit": unit,
                    "source_type": "SIMULATED",
                    "is_simulated": True,
                    "metadata": {"mission_day": day, "origin": "astronaut_health_simulated.csv"},
                })
    return by_day


def seed(api: HttpApi, through_day: int) -> None:
    days = load_days(CSV_PATH, through_day)
    total = 0
    for day in sorted(days):
        status, body = api.post("/measurements", days[day])
        if status != 200:
            raise RuntimeError(f"day {day}: POST /measurements returned {status}: {body}")
        total += body["accepted"]
    _, alerts = api.get("/alerts")
    print(f"Seeded {total} simulated readings (days 1-{max(days)}), {len(alerts)} alert(s) raised:")
    for a in sorted(alerts, key=lambda a: (a["astronaut_id"], a["parameter"])):
        print(f"  {a['alert_id']}  {a['astronaut_id']:<7} {a['parameter']:<12} {a['level']:<7} {a['title']}")


def wait_ready(api: HttpApi, server: subprocess.Popen | None, seconds: float = 30.0) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if server is not None and server.poll() is not None:
            raise RuntimeError("API server exited during start-up (is the port already in use?)")
        try:
            if api.get("/alerts")[0] == 200:
                return
        except OSError:
            pass
        time.sleep(0.3)
    raise RuntimeError("API server did not start")


def main() -> None:
    ap = argparse.ArgumentParser(description="Serve the ASTRA API with the simulated crew dataset")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--through-day", type=int, default=143, help="last mission day to load (1-180)")
    ap.add_argument("--seed-only", action="store_true", help="seed an already running server and exit")
    ap.add_argument("--url", default=None, help="server to seed with --seed-only")
    args = ap.parse_args()

    url = args.url or f"http://{args.host}:{args.port}"
    api = HttpApi(url)
    if args.seed_only:
        wait_ready(api, None)
        seed(api, args.through_day)
        return

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "ml" / "src"), str(ROOT / "backend")])
    env.setdefault("ASTRA_CORS_ORIGINS", FRONTEND_ORIGINS)
    env.setdefault("ASTRA_REQUIRE_ROLES", "1")  # the frontend sends X-ASTRA-Role: astronaut
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", args.host, "--port", str(args.port),
         "--log-level", "warning"],
        cwd=str(ROOT), env=env,
    )
    try:
        wait_ready(api, server)
        seed(api, args.through_day)
        print(f"\nASTRA API running at {url}  (Swagger: {url}/docs). Press Ctrl+C to stop.")
        print(f"Frontend: set VITE_API_URL={url} in Astra/.env.local, then npm run dev in Astra/.")
        server.wait()
    except KeyboardInterrupt:
        pass
    finally:
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()


if __name__ == "__main__":
    main()
