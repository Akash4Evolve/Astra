"""One-command ASTRA demo: the full judge story, end to end.

    python scripts/demo.py                 # starts its own API server, runs the story, stops it
    python scripts/demo.py --keep-running  # leaves the server up afterwards for Swagger / the frontend
    python scripts/demo.py --url http://127.0.0.1:8000   # use a server you already started

Story (spec 18.1):
  1. CrewBand (simulated) streams daily readings + check-ins; a personal baseline forms
  2. The link drops; the device buffers readings
  3. The link returns; one sync batch arrives late; ASTRA raises an explainable alert
  4. The Digital Twin shows the change
  5. The astronaut acknowledges and records a follow-up action
  6. The Twin and the audit trail reflect it
  7. Latency is measured and saved to docs/latency.md

Output is ASCII only, so it works in every Windows console.
"""
from __future__ import annotations

import argparse
import os
import socket
import statistics
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from crewband_sim import HttpApi, build_days, run  # noqa: E402

ASTRO = "AST-001"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(port: int) -> subprocess.Popen:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "ml" / "src"), str(ROOT / "backend")])
    env.setdefault("ASTRA_REQUIRE_ROLES", "1")  # each step below uses the role that would do it
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port),
         "--log-level", "warning"],
        cwd=str(ROOT), env=env,
    )


def wait_ready(api: HttpApi, seconds: float = 20.0) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            status, _ = api.get("/alerts")
            if status == 200:
                return
        except OSError:
            pass
        time.sleep(0.3)
    raise RuntimeError("API server did not start. Run 'python -m pytest -q' to check the install.")


def banner(n: int, text: str) -> None:
    print(f"\n=== STEP {n}: {text} " + "=" * max(0, 60 - len(text)))


def show_twin(api: HttpApi, label: str) -> dict:
    _, t = api.get(f"/astronauts/{ASTRO}/twin")
    print(f"  Digital Twin ({label})  version={t['twin_version']}  attention_needed={t['attention_needed']}")
    for d in t["domains"]:
        extra = f"  7d complete={d['completeness_7d']}" if d["completeness_7d"] is not None else ""
        print(f"    - {d['label']:<24} {d['state']:<26}{extra}")
    for f in t["pending_follow_ups"]:
        print(f"    follow-up {f['action_id']} due {f['follow_up_at']} overdue={f['overdue']}")
    return t


def timed(fn, n: int) -> list[float]:
    out = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        out.append((time.perf_counter() - t0) * 1000)
    return out


def summarise(ms: list[float]) -> str:
    ms = sorted(ms)
    p95 = ms[min(len(ms) - 1, int(round(0.95 * (len(ms) - 1))))]
    return f"n={len(ms):3d}  median={statistics.median(ms):6.1f} ms  p95={p95:6.1f} ms  max={ms[-1]:6.1f} ms"


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the ASTRA end-to-end demo")
    ap.add_argument("--url", default=None, help="use an already running server instead of starting one")
    ap.add_argument("--port", type=int, default=None, help="port for the demo server (default: any free port)")
    ap.add_argument("--interval", type=float, default=0.25, help="seconds per simulated day")
    ap.add_argument("--offline-from", type=int, default=16, help="first day the device is offline")
    ap.add_argument("--keep-running", action="store_true", help="leave the server running at the end")
    args = ap.parse_args()

    server = None
    if args.url:
        url = args.url
    else:
        port = args.port or free_port()
        url = f"http://127.0.0.1:{port}"
        print(f"Starting ASTRA API on {url} (in-memory store, local only) ...")
        server = start_server(port)
    api = HttpApi(url)

    try:
        wait_ready(api)
        print("ASTRA DEMO - all data below is SIMULATED (CrewBand simulator). Not clinical data.")

        banner(1, "CrewBand streams daily readings and check-ins")
        days = build_days("gradual_deviation", checkin_scenario="stable", skin_scenario="stable")
        result = run(api, days[: args.offline_from], interval=args.interval)
        show_twin(api, "baseline formed")

        banner(2, f"Link lost from day {args.offline_from}: device buffers, then syncs late")
        late = run(api, days[args.offline_from:], offline_from=args.offline_from, interval=args.interval / 2,
                   log=lambda s: print(s) if ("OFFLINE" in s or "sync" in s or "link" in s) else None)
        entry = late.sync_entry or {}
        delay_h = (entry.get("max_delivery_delay_seconds") or 0) / 3600
        print(f"  oldest buffered reading arrived {delay_h:.1f} h late (simulated time); duplicates ignored: "
              f"{entry.get('measurements_duplicate', 0)}")

        _, alerts = api.get("/alerts", {"astronaut_id": ASTRO, "status": "OPEN"})
        if not alerts:
            print("  No alert was raised in this run (this can happen with some seeds).")
            return
        a = alerts[0]
        e = a["explanation"]
        banner(3, "ASTRA raises an explainable alert")
        print(f"  ALERT {a['alert_id']}  level={a['level']}  domain={a['domain']}")
        print(f"    {a['title']}")
        print(f"    observed:   {e['observed']}")
        print(f"    window:     {e['comparison_window']}")
        print(f"    quality:    {e['data_quality']}   model: {e['model']}")
        print(f"    evidence:   {len(e['evidence_record_ids'])} record IDs, e.g. {e['evidence_record_ids'][0]}")
        print(f"    next step:  {a['next_step']}")
        print(f"    diagnosis:  {a['diagnosis']}  (ASTRA never diagnoses)")

        banner(4, "Digital Twin shows the change")
        before = show_twin(api, "after sync")

        banner(5, "Astronaut acknowledges and records a follow-up")
        crew = api.as_role("astronaut")
        crew.post(f"/alerts/{a['alert_id']}/acknowledge", {})
        follow_up = (datetime.now(timezone.utc) + timedelta(days=1)).replace(microsecond=0)
        status, act = crew.post("/actions", {
            "alert_id": a["alert_id"], "action_type": "FOLLOW_UP_MEASUREMENT",
            "note": "Repeat resting heart rate after sleep, seated, before exercise",
            "follow_up_at": follow_up.isoformat().replace("+00:00", "Z"),
        })
        print(f"  acknowledged (means 'seen', not medical clearance); action {act['action_id']} recorded")

        banner(6, "Twin and audit trail after the action")
        after = show_twin(api, "after action")
        print(f"  twin_version changed: {before['twin_version']} -> {after['twin_version']}")
        _, audit = api.as_role("crew_medical_officer").get("/audit", {"limit": "1000"})
        counts: dict[str, int] = {}
        for ev in audit:
            counts[ev["event_type"]] = counts.get(ev["event_type"], 0) + 1
        for k in sorted(counts):
            print(f"    {k:<24} {counts[k]}")

        banner(7, "Latency (this laptop, in-memory store)")
        ingest = result.post_ms + late.post_ms
        dash = timed(lambda: api.get(f"/astronauts/{ASTRO}/dashboard"), 30)
        twin = timed(lambda: api.get(f"/astronauts/{ASTRO}/twin"), 30)
        lines = [
            f"POST /measurements (1 day)  {summarise(ingest)}",
            f"GET  dashboard              {summarise(dash)}",
            f"GET  twin                   {summarise(twin)}",
        ]
        for line in lines:
            print("  " + line)
        out = ROOT / "docs" / "latency.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            "# ASTRA latency (measured by scripts/demo.py)\n\n"
            f"- Measured: {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n"
            f"- Python {sys.version.split()[0]}, in-memory store, local HTTP on the same machine, "
            "21 simulated days of data\n"
            "- Round-trip time seen by the client, including HTTP. Numbers change from machine to machine.\n\n"
            "```\n" + "\n".join(lines) + "\n```\n",
            encoding="utf-8",
        )
        print(f"  saved to {out.relative_to(ROOT)}")
        print("\nDEMO COMPLETE.")
        if args.keep_running and server:
            print(f"Server still running: {url}/docs   (press Ctrl+C to stop)")
            server.wait()
    except KeyboardInterrupt:
        pass
    finally:
        if server and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()


if __name__ == "__main__":
    main()
