"""
download_wesad.py
-----------------
Downloads the WESAD dataset (Wearable Stress and Affect Detection) and extracts it to:
    <project_root>/data/raw/wesad/WESAD/S2/S2.pkl, S3/S3.pkl, ... (15 people)

Put this file in your project (same place as physionet_ptt.py, or in scripts/) and run:

    python NASA_Space_Monitoring/download_wesad.py
    python NASA_Space_Monitoring/download_wesad.py --zip "C:/Users/HP/Downloads/WESAD.zip"   # ZIP you already have

What it does
  * Tries several download sources in order, and checks each answer is really a ZIP
    (a dead link often returns a web page instead - that is detected and skipped)
  * Resumes a broken download: just run it again
  * Handles a ZIP inside a ZIP (UCI sometimes wraps the original)
  * Keeps only the 15 SX/SX.pkl files the project needs; writes data/metadata/wesad.json

Requirements:  pip install requests tqdm
Citation: Schmidt, P. & Reiss, A. (2018). WESAD (Wearable Stress and Affect Detection) [Dataset].
          UCI Machine Learning Repository. https://doi.org/10.24432/C57K5T
Use for academic, non-commercial purposes.
"""

import argparse
import io
import json
import re
import shutil
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path

import requests
from tqdm import tqdm

# File lives in <root>/NASA_Space_Monitoring/ or <root>/scripts/ -> root is one level up
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEST_DIR = PROJECT_ROOT / "data" / "raw" / "wesad"
TARGET = DEST_DIR / "WESAD"
ZIP_PATH = DEST_DIR / "WESAD_download.zip"
METADATA = PROJECT_ROOT / "data" / "metadata" / "wesad.json"

# Tried in this order. None of these could be tested from the machine that wrote this script.
# (The older share link that UCI points to, .../s/pYjSgfOVs6Ntahr, returned 404 on 2026-11-14.)
SOURCES = [
    ("Univ. Siegen official page link (ubi29.informatik.uni-siegen.de/usi/data_wesad.html)",
     "https://uni-siegen.sciebo.de/s/HGdUkoNlW1Ub0Gx/download"),
    ("Univ. Siegen official page link (share page)",
     "https://uni-siegen.sciebo.de/s/HGdUkoNlW1Ub0Gx"),
    ("UCI repository (static file)",
     "https://archive.ics.uci.edu/static/public/465/wesad+wearable+stress+and+affect+detection.zip"),
    ("UCI repository (short name)",
     "https://archive.ics.uci.edu/static/public/465/wesad.zip"),
]
MANUAL_PAGES = [
    "https://archive.ics.uci.edu/dataset/465/wesad+wearable+stress+and+affect+detection   (click 'Download')",
    "https://ubi29.informatik.uni-siegen.de/usi/data_wesad.html   (link 'ICMI'18 dataset')",
    "https://uni-siegen.sciebo.de/s/HGdUkoNlW1Ub0Gx   (open, then click Download)",
]
EXPECTED_SUBJECTS = 15

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0 (NASA-Space-Health-Monitoring downloader)"})


def looks_like_zip(first_bytes: bytes) -> bool:
    return first_bytes[:2] == b"PK"


def try_download(name: str, url: str, dest: Path, found_links: list[str] | None = None) -> tuple[bool, str]:
    """Download url to dest with resume. Returns (ok, message).
    Links found inside a pointer ZIP are appended to found_links."""
    part = dest.with_suffix(".part")
    have = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={have}-"} if have else {}
    try:
        r = SESSION.get(url, stream=True, timeout=60, headers=headers, allow_redirects=True)
    except requests.RequestException as e:
        return False, f"could not connect ({type(e).__name__}: {str(e)[:120]})"
    if r.status_code == 416:  # already complete
        part.replace(dest)
        return True, "already complete"
    if r.status_code not in (200, 206):
        return False, f"server answered HTTP {r.status_code}"
    if have and r.status_code == 200:  # server ignored resume: restart
        have = 0
    ctype = r.headers.get("Content-Type", "")
    stream = r.iter_content(chunk_size=1024 * 1024)
    try:
        first = next(stream)
    except StopIteration:
        return False, "empty response"
    if not have and not looks_like_zip(first):
        return False, f"not a ZIP file (got '{ctype or 'unknown'}' - probably a web page or a dead link)"

    total = int(r.headers.get("Content-Length", 0)) + have
    with open(part, "ab" if have else "wb") as f, tqdm(
        total=total or None, initial=have, unit="B", unit_scale=True, desc="WESAD"
    ) as bar:
        f.write(first)
        bar.update(len(first))
        for chunk in stream:
            f.write(chunk)
            bar.update(len(chunk))
    if not zipfile.is_zipfile(part):
        return False, "download finished but the file is not a valid ZIP (incomplete?) - run the script again to resume"
    ok, report = zip_contents_report(part)
    if not ok:
        if found_links is not None:
            found_links.extend(links_in_zip(part))
        size = part.stat().st_size
        part.unlink()
        return False, f"{report} [{size} bytes - discarded]"
    part.replace(dest)
    return True, "ok"


URL_RE = re.compile(r"https?://[^\s\"'<>]+")


def links_in_zip(path: Path) -> list[str]:
    """Web links written in small text files inside a ZIP (UCI ships a pointer file)."""
    found: list[str] = []
    try:
        with zipfile.ZipFile(path) as z:
            for i in z.infolist():
                if i.file_size < 20000 and not i.is_dir():
                    text = z.read(i).decode("utf-8", "replace")
                    for url in URL_RE.findall(text):
                        url = url.rstrip(".,);")
                        if url not in found:
                            found.append(url)
    except zipfile.BadZipFile:
        pass
    return found


def download_candidates(url: str) -> list[str]:
    """A cloud 'share' page is not the file itself; add its direct-download form."""
    out = [url]
    if "sciebo.de/s/" in url and not url.rstrip("/").endswith("/download"):
        out.insert(0, url.rstrip("/") + "/download")
    return out


def zip_contents_report(path: Path) -> tuple[bool, str]:
    """True if the ZIP holds WESAD subject files (or a big inner ZIP). Otherwise a short
    description of what it holds instead, including any small text (often a link)."""
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            for i in infos:
                p = Path(i.filename)
                if p.suffix == ".pkl" and p.parent.name == p.stem:
                    return True, "ok"
                if p.suffix.lower() == ".zip" and i.file_size > 1_000_000:
                    return True, "ok (archive inside archive)"
            lines = [f"{i.filename} ({i.file_size} bytes)" for i in infos[:10]]
            for i in infos[:5]:
                if i.file_size < 5000 and not i.is_dir():
                    text = " ".join(z.read(i).decode("utf-8", "replace").split())[:300]
                    lines.append(f"   text of {i.filename}: {text}")
            return False, "ZIP does not contain WESAD data. It holds: " + "; ".join(lines)
    except zipfile.BadZipFile:
        return False, "not a valid ZIP"


def extract_subjects(zip_source, depth: int = 0) -> int:
    """Copy SX/SX.pkl files to data/raw/wesad/WESAD/. Opens a nested ZIP if needed."""
    n = 0
    with zipfile.ZipFile(zip_source) as z:
        names = z.infolist()
        for info in names:
            p = Path(info.filename)
            if p.suffix == ".pkl" and p.stem.startswith("S") and p.parent.name == p.stem:
                out = TARGET / p.stem / p.name
                if out.exists() and out.stat().st_size == info.file_size:
                    n += 1
                    continue
                out.parent.mkdir(parents=True, exist_ok=True)
                print(f"  extracting {p.stem} ({info.file_size / 1e6:.0f} MB)")
                with z.open(info) as src, open(out, "wb") as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
                n += 1
        if n == 0 and depth == 0:  # maybe the real archive is inside this one
            for info in names:
                if info.filename.lower().endswith(".zip"):
                    print(f"  opening inner archive {info.filename} ...")
                    inner = DEST_DIR / "_inner.zip"
                    with z.open(info) as src, open(inner, "wb") as dst:
                        shutil.copyfileobj(src, dst, 1024 * 1024)
                    n = extract_subjects(inner, depth + 1)
                    inner.unlink(missing_ok=True)
                    if n:
                        break
    return n


def main():
    ap = argparse.ArgumentParser(description="Download and extract WESAD")
    ap.add_argument("--zip", type=Path, default=None, help="use a WESAD ZIP you already downloaded")
    ap.add_argument("--keep-zip", action="store_true", help="keep the downloaded ZIP after extracting")
    args = ap.parse_args()

    print(f"Project root : {PROJECT_ROOT}")
    print(f"Destination  : {TARGET}")
    DEST_DIR.mkdir(parents=True, exist_ok=True)

    present = sorted(TARGET.glob("S*/S*.pkl"))
    if len(present) >= EXPECTED_SUBJECTS and not args.zip:
        print(f"\nWESAD is already here ({len(present)} subjects). Nothing to do.")
        return

    source_used = None
    if args.zip:
        ok, report = zip_contents_report(args.zip)
        if not ok:
            sys.exit(f"{args.zip}: {report}")
        zip_file = args.zip
        source_used = f"local file {args.zip}"
    else:
        zip_file = ZIP_PATH
        if zip_file.exists() and zip_contents_report(zip_file)[0]:
            print("\n[1/2] ZIP already downloaded, skipping download")
            source_used = "earlier download"
        else:
            if zip_file.exists():
                zip_file.unlink()  # leftover from an earlier failed attempt
            print("\n[1/2] Downloading (about 2.5 GB) ...")
            queue = list(SOURCES)
            tried: set[str] = set()
            while queue:
                name, url = queue.pop(0)
                if url in tried:
                    continue
                tried.add(url)
                print(f"\n  trying: {name}\n          {url}")
                links: list[str] = []
                ok, msg = try_download(name, url, zip_file, links)
                print(f"  -> {msg}")
                if ok:
                    source_used = url
                    break
                for link in links:  # follow the pointer UCI ships, before anything else
                    for cand in reversed(download_candidates(link)):
                        queue.insert(0, ("link found inside the previous ZIP", cand))
                time.sleep(1)
            if source_used is None:
                print("\nAll automatic sources failed. Download it in your browser from one of these pages:")
                for page in MANUAL_PAGES:
                    print(f"  {page}")
                print('\nThen run:  python NASA_Space_Monitoring/download_wesad.py --zip "PATH\\TO\\THE.zip"')
                print("And please send the messages above, so the script can be fixed.")
                sys.exit(1)

    print("\n[2/2] Extracting the subject files ...")
    n = extract_subjects(zip_file)
    if n == 0:
        sys.exit("No SX/SX.pkl files found in the ZIP. Is it the WESAD archive?")

    METADATA.parent.mkdir(parents=True, exist_ok=True)
    METADATA.write_text(json.dumps({
        "dataset": "WESAD (Wearable Stress and Affect Detection)",
        "citation": "Schmidt, P. & Reiss, A. (2018). UCI Machine Learning Repository. https://doi.org/10.24432/C57K5T",
        "source": source_used,
        "subjects": n,
        "local_path": str(TARGET.relative_to(PROJECT_ROOT)),
        "downloaded_at": datetime.now().isoformat(timespec="seconds"),
    }, indent=2))

    if not args.zip and not args.keep_zip and ZIP_PATH.exists():
        ZIP_PATH.unlink()
        print("  removed the downloaded ZIP to save space (use --keep-zip to keep it)")

    print(f"\nDone: {n} subjects in {TARGET}")
    if n < EXPECTED_SUBJECTS:
        print(f"Note: expected {EXPECTED_SUBJECTS}. The training will still run with {n}.")
    print("Next: python ml/eval/train_ppg_quality.py --with-wesad")


if __name__ == "__main__":
    main()