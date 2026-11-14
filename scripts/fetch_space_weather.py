"""Download space-weather context data and keep it locally (no training).

    python scripts/fetch_space_weather.py            # GOES (last 7 days) + DONKI (last 30 days)
    python scripts/fetch_space_weather.py --days 90  # longer DONKI window

Saves:
    data/raw/nasa_radiation/goes/<UTC stamp>_<product>.json  (+ latest_<product>.json)
    data/raw/nasa_space_weather/donki/<UTC stamp>_<TYPE>.json (+ latest_<TYPE>.json)
    data/metadata/space_weather_fetch_log.json                (what was fetched, when, from where)

Sources:
  - NOAA SWPC GOES JSON service: https://services.swpc.noaa.gov/json/goes/
    Integral proton flux; the >=10 MeV channel defines the NOAA S-scale
    (S1..S5 at 10, 100, 1000, 10000, 100000 pfu).
  - NASA DONKI (space weather event notifications) via api.nasa.gov.
    Set NASA_API_KEY to your free key; otherwise DEMO_KEY is used (low rate limit).
    If api.nasa.gov fails, the CCMC DONKI web service is tried instead.
  The exact product file names and endpoints were not tested from the development
  machine; if one fails, the script says which, and keeps going.

This is ENVIRONMENT context (what the space environment was doing), NOT anyone's radiation dose.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
GOES_BASE = "https://services.swpc.noaa.gov/json/goes/primary/"
GOES_PRODUCTS = ("integral-protons-7-day.json", "xrays-7-day.json")
DONKI_TYPES = {"FLR": "solar flares", "SEP": "solar energetic particle events",
               "CME": "coronal mass ejections", "GST": "geomagnetic storms"}
DONKI_PRIMARY = "https://api.nasa.gov/DONKI/{type}?startDate={start}&endDate={end}&api_key={key}"
DONKI_FALLBACK = "https://kauai.ccmc.gsfc.nasa.gov/DONKI/WS/get/{type}?startDate={start}&endDate={end}"
S_SCALE = ((100000, "S5"), (10000, "S4"), (1000, "S3"), (100, "S2"), (10, "S1"))

Fetcher = Callable[[str], Any]


def http_json(url: str, timeout: float = 30.0) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "ASTRA-hackathon/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
    return json.loads(body) if body.strip() else []


def s_level(flux_pfu: float) -> str:
    """NOAA S-scale level for a >=10 MeV flux value. Indicative only: an official
    S1 storm needs the threshold met on 3 consecutive 5-minute readings."""
    for threshold, name in S_SCALE:
        if flux_pfu >= threshold:
            return name
    return "below S1"


def latest_10mev(records: list[dict]) -> dict | None:
    rows = [r for r in records if isinstance(r, dict) and str(r.get("energy", "")).replace(" ", "") == ">=10MeV"
            and r.get("flux") is not None]
    return max(rows, key=lambda r: r.get("time_tag", "")) if rows else None


def _save(folder: Path, stamp: str, name: str, data: Any) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{stamp}_{name}"
    text = json.dumps(data, indent=1)
    path.write_text(text, encoding="utf-8")
    (folder / f"latest_{name}").write_text(text, encoding="utf-8")
    return path


def fetch_all(days: int, root: Path = ROOT, fetch: Fetcher = http_json,
              now: datetime | None = None, api_key: str | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%MZ")
    key = api_key or os.getenv("NASA_API_KEY") or "DEMO_KEY"
    log: list[dict] = []

    goes_dir = root / "data" / "raw" / "nasa_radiation" / "goes"
    for product in GOES_PRODUCTS:
        url = GOES_BASE + product
        entry = {"source": "NOAA SWPC GOES", "product": product, "url": url,
                 "fetched_at": now.isoformat(timespec="seconds")}
        try:
            data = fetch(url)
            entry.update(status="ok", records=len(data), file=str(_save(goes_dir, stamp, product, data).relative_to(root)))
            if "proton" in product:
                last = latest_10mev(data)
                if last:
                    entry["latest_10MeV"] = {"time_tag": last.get("time_tag"), "flux_pfu": last["flux"],
                                             "indicative_s_level": s_level(float(last["flux"]))}
        except (urllib.error.URLError, OSError, ValueError) as e:
            entry.update(status="failed", error=str(e)[:200],
                         hint=f"open {GOES_BASE} in a browser to see current product names")
        log.append(entry)

    start = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")
    donki_dir = root / "data" / "raw" / "nasa_space_weather" / "donki"
    for typ, desc in DONKI_TYPES.items():
        entry = {"source": "NASA DONKI", "product": f"{typ} ({desc})", "start": start, "end": end,
                 "fetched_at": now.isoformat(timespec="seconds")}
        tried = []
        for template in (DONKI_PRIMARY, DONKI_FALLBACK):
            url = template.format(type=typ, start=start, end=end, key=key)
            shown = url.replace(key, "***") if "api_key=" in url else url  # never log the key
            tried.append(shown)
            try:
                data = fetch(url)
                if isinstance(data, dict) and data.get("error"):
                    raise ValueError(str(data["error"]))
                data = data if isinstance(data, list) else [data]
                entry.pop("error", None)
                entry.update(status="ok", url=shown, records=len(data),
                             file=str(_save(donki_dir, stamp, f"{typ}.json", data).relative_to(root)))
                break
            except (urllib.error.URLError, OSError, ValueError) as e:
                entry.update(status="failed", error=str(e)[:200])
        entry["tried"] = tried
        log.append(entry)

    meta = root / "data" / "metadata" / "space_weather_fetch_log.json"
    meta.parent.mkdir(parents=True, exist_ok=True)
    history = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else []
    history.append({"run_at": now.isoformat(timespec="seconds"), "items": log})
    meta.write_text(json.dumps(history, indent=1), encoding="utf-8")
    return log


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch GOES + DONKI space-weather context and keep it locally")
    ap.add_argument("--days", type=int, default=30, help="DONKI look-back window in days")
    args = ap.parse_args()

    log = fetch_all(args.days)
    print("Space-weather fetch (environment context, NOT a personal dose)\n")
    for e in log:
        if e["status"] == "ok":
            print(f"  OK      {e['source']:<15} {e['product']:<38} {e['records']:5d} records -> {e['file']}")
            if "latest_10MeV" in e:
                l = e["latest_10MeV"]
                print(f"          latest >=10 MeV proton flux {float(l['flux_pfu']):.3g} pfu at {l['time_tag']} "
                      f"-> {l['indicative_s_level']} (indicative)")
        else:
            print(f"  FAILED  {e['source']:<15} {e['product']:<38} {e.get('error', '')}")
            if e.get("hint"):
                print(f"          hint: {e['hint']}")
    print(f"\nLog: {ROOT / 'data' / 'metadata' / 'space_weather_fetch_log.json'}")
    if not any(e["status"] == "ok" for e in log):
        print("Nothing was downloaded. Check the internet connection and try again.")
        sys.exit(1)


if __name__ == "__main__":
    main()
