"""CrewBand simulator: streams SIMULATED readings and check-ins to a running ASTRA API.

It stands in for the future wristband + gateway, through the same API a real device
would use (POST /measurements live, POST /sync for data buffered while offline).
Every record it sends is labelled SIMULATED.

Time is compressed: one simulated day is sent every --interval seconds. Timestamps
are shifted so the last simulated day ends "now", so freshness and device status
look realistic during a live demo.

Examples (from the project folder, server already running on port 8000):
    python scripts/crewband_sim.py
    python scripts/crewband_sim.py --scenario stable --interval 0.2
    python scripts/crewband_sim.py --offline-from 16      # days 16+ buffered, then synced
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Protocol
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ml" / "src"))

from astra_ml.scenarios import generate_checkins, generate_series  # noqa: E402
from astra_ml.signals import MIN_DAYS  # noqa: E402
from astra_ml.synthetic import START  # noqa: E402


# ---------------------------------------------------------------- transport
class Api(Protocol):
    def post(self, path: str, body: Any) -> tuple[int, Any]: ...
    def get(self, path: str, params: dict | None = None) -> tuple[int, Any]: ...


class HttpApi:
    """Tiny stdlib HTTP client, so the simulator needs no extra packages."""

    def __init__(self, base_url: str, timeout: float = 10.0, role: str = "device") -> None:
        self.base = base_url.rstrip("/") + "/api/v1"
        self.timeout = timeout
        self.role = role  # sent as X-ASTRA-Role (declared, not authenticated)

    def as_role(self, role: str) -> "HttpApi":
        return HttpApi(self.base[: -len("/api/v1")], self.timeout, role)

    def _send(self, req: urllib.request.Request) -> tuple[int, Any]:
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null")

    def post(self, path: str, body: Any) -> tuple[int, Any]:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(self.base + path, data=data, method="POST",
                                     headers={"Content-Type": "application/json", "X-ASTRA-Role": self.role})
        return self._send(req)

    def get(self, path: str, params: dict | None = None) -> tuple[int, Any]:
        query = ("?" + "&".join(f"{k}={v}" for k, v in params.items())) if params else ""
        return self._send(urllib.request.Request(self.base + path + query, headers={"X-ASTRA-Role": self.role}))


# ---------------------------------------------------------------- plan
@dataclass
class DayPacket:
    day: int
    measurements: list[dict] = field(default_factory=list)
    checkins: list[dict] = field(default_factory=list)


def build_days(
    scenario: str = "gradual_deviation",
    checkin_scenario: str | None = "stable",
    skin_scenario: str | None = "stable",
    seed: int = 42,
    astronaut_id: str = "AST-001",
    device_id: str = "CREWBAND-SIM-001",
    now: datetime | None = None,
) -> list[DayPacket]:
    """One packet per simulated day, timestamps shifted so the last day ends at `now`."""
    now = now or datetime.now(timezone.utc)
    shift = now - (START + timedelta(days=MIN_DAYS - 1, hours=12))
    days = [DayPacket(d) for d in range(MIN_DAYS)]

    streams = [("heart_rate", scenario)] + ([("skin_temperature", skin_scenario)] if skin_scenario else [])
    for parameter, scen in streams:
        for m in generate_series(parameter, scen, seed=seed, astronaut_id=astronaut_id, device_id=device_id):
            d = (m.timestamp_utc - START).days
            ts = m.timestamp_utc + shift
            days[d].measurements.append(
                m.model_copy(update={"timestamp_utc": ts, "received_at": ts}).model_dump(mode="json")
            )
    if checkin_scenario:
        for c in generate_checkins(checkin_scenario, seed=seed, astronaut_id=astronaut_id):
            d = (c.timestamp_utc - START).days
            ts = c.timestamp_utc + shift
            days[d].checkins.append(
                c.model_copy(update={"timestamp_utc": ts, "received_at": ts}).model_dump(mode="json")
            )
    return days


def _stamp_received(items: list[dict], when: datetime) -> list[dict]:
    """received_at = when the API actually gets it (the source timestamp is never changed)."""
    iso = when.isoformat().replace("+00:00", "Z")
    return [{**x, "received_at": iso} for x in items]


# ---------------------------------------------------------------- run
@dataclass
class RunResult:
    sent_live: int = 0
    sent_synced: int = 0
    alerts: list[str] = field(default_factory=list)
    sync_entry: dict | None = None
    post_ms: list[float] = field(default_factory=list)


def run(
    api: Api,
    days: list[DayPacket],
    offline_from: int | None = None,
    interval: float = 0.0,
    log: Callable[[str], None] = print,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    sleep: Callable[[float], None] = time.sleep,
) -> RunResult:
    """Send days live; from `offline_from` on, buffer them and deliver one /sync batch."""
    res = RunResult()
    buffered = DayPacket(-1)

    for p in days:
        hr = next((m for m in p.measurements if m["parameter"] == "heart_rate"), None)
        hr_txt = f"HR {hr['value']:5.1f} bpm" if hr else "HR   --   "
        if offline_from is not None and p.day >= offline_from:
            buffered.measurements += p.measurements
            buffered.checkins += p.checkins
            log(f"  day {p.day:2d}  {hr_txt}  [OFFLINE - buffered on device]")
            sleep(interval)
            continue

        new_alerts: list[str] = []
        if p.measurements:
            t0 = time.perf_counter()
            status, body = api.post("/measurements", _stamp_received(p.measurements, clock()))
            res.post_ms.append((time.perf_counter() - t0) * 1000)
            if status != 200:
                raise RuntimeError(f"/measurements returned {status}: {body}")
            res.sent_live += body["accepted"]
            new_alerts += body["alerts"]
        for c in p.checkins:
            status, body = api.post("/check-ins", _stamp_received([c], clock())[0])
            if status not in (200, 201):
                raise RuntimeError(f"/check-ins returned {status}: {body}")
            res.sent_live += 0 if body["duplicate"] else 1
            new_alerts += body["alerts"]

        flag = ""
        for a in new_alerts:
            if a not in res.alerts:
                res.alerts.append(a)
            flag = f"  <-- alert {a}"
        log(f"  day {p.day:2d}  {hr_txt}  sent{flag}")
        sleep(interval)

    if buffered.measurements or buffered.checkins:
        log("  link restored - sending buffered data as one sync batch ...")
        now = clock()
        batch = {
            "batch_id": f"SYNC-{uuid4().hex[:8].upper()}",
            "source_node": "CREWBAND-GW-SIM",
            "created_at": now.isoformat().replace("+00:00", "Z"),
            "measurements": _stamp_received(buffered.measurements, now),
            "checkins": _stamp_received(buffered.checkins, now),
        }
        status, body = api.post("/sync", batch)
        if status not in (200, 201):
            raise RuntimeError(f"/sync returned {status}: {body}")
        res.sync_entry = body
        res.sent_synced = body["measurements_accepted"] + body["checkins_accepted"]
        for a in body["alerts"]:
            if a not in res.alerts:
                res.alerts.append(a)
        log(f"  sync {body['batch_id']}: {res.sent_synced} records applied, "
            f"alerts {body['alerts'] or 'none'}")
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description="CrewBand simulator (SIMULATED data only)")
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--scenario", default="gradual_deviation",
                    help="heart-rate scenario: stable, gradual_deviation, single_noise, repeated_deviation, "
                         "missing_data, dropout, stale_feed, motion_artifact")
    ap.add_argument("--checkins", default="stable", help="check-in scenario, or 'none'")
    ap.add_argument("--skin", default="stable", help="skin-temperature scenario, or 'none'")
    ap.add_argument("--offline-from", type=int, default=None, help="buffer days >= this, then sync")
    ap.add_argument("--interval", type=float, default=0.5, help="seconds between simulated days")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--astronaut", default="AST-001")
    args = ap.parse_args()

    days = build_days(args.scenario, None if args.checkins == "none" else args.checkins,
                      None if args.skin == "none" else args.skin, args.seed, args.astronaut)
    print(f"CrewBand simulator -> {args.url}  (all data labelled SIMULATED)")
    res = run(HttpApi(args.url), days, args.offline_from, args.interval)
    print(f"done: {res.sent_live} live + {res.sent_synced} synced records, alerts: {res.alerts or 'none'}")


if __name__ == "__main__":
    main()
