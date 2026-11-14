"""Download the project datasets automatically. Run from the project folder:

    python scripts/download_datasets.py            # NASA DONKI + WESAD
    python scripts/download_datasets.py --nasa     # only NASA DONKI
    python scripts/download_datasets.py --wesad    # only WESAD (about 2.5 GB)

NASA DONKI (space-weather event catalogues, CCMC/NASA) -> data/raw/nasa_radiation/
    SEP.json / SEP.csv   Solar Energetic Particle events
    RBE.json / RBE.csv   Radiation Belt Enhancements
    CME.json / CME.csv   Coronal Mass Ejections
    FLR.json / FLR.csv   Solar Flares
  Fetched year by year from the CCMC DONKI web service (no key needed); if that fails,
  from api.nasa.gov (set NASA_API_KEY, otherwise DEMO_KEY with a low hourly limit).
  These are ENVIRONMENT events, not anyone's radiation dose.

WESAD (Schmidt & Reiss 2018, doi:10.24432/C57K5T) -> data/raw/wesad/WESAD/S2/S2.pkl ...
  The download link below was taken from a public project that uses WESAD, not from the
  official page. If it fails, the script prints where to get the file by hand, and
  `--wesad-zip PATH` extracts a ZIP you already downloaded.

A log of every download goes to data/metadata/download_log.json.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]

DONKI_TYPES = {"SEP": "Solar Energetic Particle events", "RBE": "Radiation Belt Enhancements",
               "CME": "Coronal Mass Ejections", "FLR": "Solar Flares"}
DONKI_ID_FIELD = {"SEP": "sepID", "RBE": "rbeID", "CME": "activityID", "FLR": "flrID"}
DONKI_URLS = (
    "https://kauai.ccmc.gsfc.nasa.gov/DONKI/WS/get/{type}?startDate={start}&endDate={end}",
    "https://api.nasa.gov/DONKI/{type}?startDate={start}&endDate={end}&api_key={key}",
)
WESAD_URL = "https://uni-siegen.sciebo.de/s/pYjSgfOVs6Ntahr/download"
WESAD_PAGES = ("https://ubicomp.eti.uni-siegen.de/home/datasets/icmi18/",
               "https://archive.ics.uci.edu/dataset/465/wesad+wearable+stress+and+affect+detection")

JsonFetcher = Callable[[str], Any]


# ------------------------------------------------------------------ helpers
def http_json(url: str, timeout: float = 120.0) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "ASTRA-hackathon/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
    return json.loads(body) if body.strip() else []


def log_entry(entry: dict, root: Path = ROOT) -> None:
    path = root / "data" / "metadata" / "download_log.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    history = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    history.append(entry)
    path.write_text(json.dumps(history, indent=1), encoding="utf-8")


def year_ranges(start: date, end: date) -> list[tuple[str, str]]:
    out, y = [], start.year
    while y <= end.year:
        a = max(start, date(y, 1, 1))
        b = min(end, date(y, 12, 31))
        out.append((a.isoformat(), b.isoformat()))
        y += 1
    return out


def to_csv(records: list[dict], path: Path) -> None:
    """Flatten DONKI records: plain fields become columns, nested lists/objects are kept as JSON text."""
    import csv

    columns: list[str] = []
    for r in records:
        for k in r:
            if k not in columns:
                columns.append(k)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(columns)
        for r in records:
            row = []
            for c in columns:
                v = r.get(c)
                row.append(json.dumps(v) if isinstance(v, (list, dict)) else ("" if v is None else v))
            w.writerow(row)


# ------------------------------------------------------------------ NASA DONKI
_UNREACHABLE: set[str] = set()  # hosts that timed out once are skipped for the rest of the run


def _fetch_range(typ: str, a: str, b: str, key: str, fetch: JsonFetcher,
                 errors: list[str]) -> list[dict] | None:
    """Try every source for one date range. Records each source's error."""
    for template in DONKI_URLS:
        url = template.format(type=typ, start=a, end=b, key=key)
        host = url.split("/")[2]
        if host in _UNREACHABLE:
            continue
        try:
            data = fetch(url)
            if isinstance(data, dict) and data.get("error"):
                raise ValueError(str(data["error"]))
            return data if isinstance(data, list) else [data]
        except (urllib.error.URLError, OSError, ValueError) as e:
            msg = str(e)[:150]
            if "10060" in msg or "timed out" in msg.lower():
                _UNREACHABLE.add(host)
                msg = "no response (timed out) - your network cannot reach this server; skipping it from now on"
            if "429" in msg and "api.nasa.gov" in host:
                if key == "DEMO_KEY":
                    msg += " -> the shared DEMO_KEY limit is used up; run again with --api-key YOUR_KEY"
                else:
                    msg += " -> your own key hit its hourly limit; wait a few minutes and run again"
            errors.append(f"{host}: {msg}")
    return None


def download_donki(start: date, end: date, root: Path = ROOT, fetch: JsonFetcher = http_json,
                   api_key: str | None = None, pause: float = 1.0,
                   log: Callable[[str], None] = print) -> dict[str, int]:
    """One request per event type for the whole range (few requests = no rate-limit trouble).
    Only if that fails, fall back to one request per year."""
    key = api_key or os.getenv("NASA_API_KEY") or "DEMO_KEY"
    if key == "DEMO_KEY":
        log("  using NASA DEMO_KEY (very low limit) - better: --api-key YOUR_KEY")
    else:
        log(f"  using your NASA key {key[:4]}...{key[-4:]}")
    out_dir = root / "data" / "raw" / "nasa_radiation"
    out_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for typ, desc in DONKI_TYPES.items():
        merged: dict[str, dict] = {}
        failed: list[str] = []
        errors: list[str] = []
        whole = _fetch_range(typ, start.isoformat(), end.isoformat(), key, fetch, errors)
        if whole is not None:
            chunks = [(f"{start.year}-{end.year}", whole)]
        else:
            for e in errors:
                log(f"    {typ} whole range failed - {e}")
            log(f"    {typ}: trying year by year ...")
            chunks = []
            for a, b in year_ranges(start, end):
                errs: list[str] = []
                got = _fetch_range(typ, a, b, key, fetch, errs)
                if got is None:
                    failed.append(f"{a}..{b}: " + " | ".join(errs))
                    log(f"    {typ} {a[:4]}: FAILED")
                    for e in errs:
                        log(f"        {e}")
                else:
                    chunks.append((a[:4], got))
                time.sleep(pause)
        for label, got in chunks:
            for rec in got:
                rid = rec.get(DONKI_ID_FIELD[typ]) or json.dumps(rec, sort_keys=True)
                merged[rid] = rec
            log(f"    {typ} {label}: {len(got):5d} events")
        records = sorted(merged.values(), key=lambda r: str(r.get(DONKI_ID_FIELD[typ], "")))
        if records or not failed:
            (out_dir / f"{typ}.json").write_text(json.dumps(records, indent=1), encoding="utf-8")
            to_csv(records, out_dir / f"{typ}.csv")
            log(f"  {typ} ({desc}): {len(records)} events -> data/raw/nasa_radiation/{typ}.json + .csv")
        else:
            log(f"  {typ} ({desc}): NOT saved (every request failed, see errors above)")
        counts[typ] = len(records)
        log_entry({"dataset": f"NASA DONKI {typ}", "start": start.isoformat(), "end": end.isoformat(),
                   "records": len(records), "failed_ranges": failed,
                   "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "source": "CCMC DONKI (kauai.ccmc.gsfc.nasa.gov) / api.nasa.gov"}, root)
        time.sleep(pause)
    return counts


# ------------------------------------------------------------------ WESAD
def download_file(url: str, dest: Path, log: Callable[[str], None] = print) -> Path:
    """Stream to dest with resume if a partial file exists."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    done = part.stat().st_size if part.exists() else 0
    headers = {"User-Agent": "ASTRA-hackathon/1.0"}
    if done:
        headers["Range"] = f"bytes={done}-"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as r:
        if done and r.status != 206:  # server ignored the resume request: start again
            done = 0
        total = done + int(r.headers.get("Content-Length") or 0)
        mode = "ab" if done else "wb"
        last = time.time()
        with open(part, mode) as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if time.time() - last > 2:
                    pct = f"{100 * done / total:5.1f}%" if total else ""
                    log(f"    {done / 1e9:6.2f} GB {pct}")
                    last = time.time()
    part.replace(dest)
    return dest


def extract_wesad(zip_path: Path, root: Path = ROOT, log: Callable[[str], None] = print) -> int:
    """Extract only SX/SX.pkl files into data/raw/wesad/WESAD/SX/SX.pkl. Returns subject count."""
    target = root / "data" / "raw" / "wesad" / "WESAD"
    n = 0
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            name = Path(info.filename)
            if name.suffix == ".pkl" and name.stem.startswith("S") and name.parent.name == name.stem:
                out = target / name.stem / name.name
                if out.exists() and out.stat().st_size == info.file_size:
                    n += 1
                    continue
                out.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, open(out, "wb") as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
                n += 1
                log(f"    extracted {name.stem}")
    if n == 0:
        raise ValueError(f"{zip_path} has no WESAD subject files (expected S2/S2.pkl ...)")
    return n


def download_wesad(root: Path = ROOT, url: str = WESAD_URL, zip_path: Path | None = None,
                   log: Callable[[str], None] = print, downloader=download_file) -> int:
    existing = list((root / "data" / "raw" / "wesad" / "WESAD").glob("S*/S*.pkl"))
    if len(existing) >= 15 and zip_path is None:
        log(f"  WESAD already present ({len(existing)} subjects) - skipping download")
        return len(existing)
    if zip_path is None:
        zip_path = root / "data" / "raw" / "wesad" / "WESAD.zip"
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        if not zip_path.exists():
            log(f"  downloading WESAD (about 2.5 GB) from {url}")
            try:
                downloader(url, zip_path, log)
            except (urllib.error.URLError, OSError) as e:
                log(f"  WESAD download FAILED: {e}")
                log("  Download the ZIP by hand from one of these pages, then run:")
                for p in WESAD_PAGES:
                    log(f"    {p}")
                log("    python scripts/download_datasets.py --wesad --wesad-zip PATH_TO_THE_ZIP")
                raise
    log(f"  extracting {zip_path} ...")
    n = extract_wesad(zip_path, root, log)
    log(f"  WESAD: {n} subjects -> data/raw/wesad/WESAD/")
    log_entry({"dataset": "WESAD", "subjects": n, "zip": str(zip_path),
               "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "source": url, "citation": "doi:10.24432/C57K5T"}, root)
    return n


# ------------------------------------------------------------------ main
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--nasa", action="store_true", help="only NASA DONKI")
    ap.add_argument("--wesad", action="store_true", help="only WESAD")
    ap.add_argument("--api-key", default=None, help="your NASA API key from https://api.nasa.gov")
    ap.add_argument("--start", default="2020-01-01", help="DONKI start date (yyyy-mm-dd)")
    ap.add_argument("--end", default=None, help="DONKI end date (default: today)")
    ap.add_argument("--wesad-zip", type=Path, default=None, help="extract a WESAD ZIP you already have")
    ap.add_argument("--delete-zip", action="store_true", help="delete the WESAD ZIP after extracting")
    args = ap.parse_args()
    both = not (args.nasa or args.wesad)
    ok = True

    if args.nasa or both:
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end) if args.end else datetime.now(timezone.utc).date()
        print(f"NASA DONKI {start} to {end}")
        counts = download_donki(start, end, api_key=args.api_key)
        ok = ok and any(counts.values())

    if args.wesad or both:
        print("\nWESAD")
        try:
            download_wesad(zip_path=args.wesad_zip)
            z = ROOT / "data" / "raw" / "wesad" / "WESAD.zip"
            if args.delete_zip and z.exists():
                z.unlink()
                print("  deleted WESAD.zip")
        except (urllib.error.URLError, OSError, ValueError, zipfile.BadZipFile) as e:
            print(f"  WESAD not completed: {e}")
            ok = False

    print("\nDone." if ok else "\nFinished with problems - see messages above.")
    print(f"Log: {ROOT / 'data' / 'metadata' / 'download_log.json'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
