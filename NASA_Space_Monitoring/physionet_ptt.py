

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

import requests
from tqdm import tqdm


DATASET_SLUG = "pulse-transit-time-ppg"
VERSION = "1.1.0"
BASE_URL = f"https://physionet.org/files/{DATASET_SLUG}/{VERSION}/"


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEST_DIR = PROJECT_ROOT / "data" / "raw" / "physionet" / "pulse_transit_time_ppg"
METADATA_DIR = PROJECT_ROOT / "data" / "metadata"

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "NASA-Space-Health-Monitoring-downloader/1.0"})


class _LinkParser(HTMLParser):
    """Collects href values from PhysioNet's directory-listing pages."""

    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for name, value in attrs:
                if name == "href" and value:
                    self.links.append(value)


def list_remote_files(url, rel_prefix="", skip_dirs=()):
    """Recursively walk the PhysioNet file listing and return relative file paths."""
    resp = SESSION.get(url, timeout=60)
    resp.raise_for_status()
    parser = _LinkParser()
    parser.feed(resp.text)

    files = []
    for href in parser.links:
        
        if href.startswith(("?", "#", "/", "http", "..")):
            continue
        if href.endswith("/"):
            sub = href.rstrip("/")
            if sub in skip_dirs:
                print(f"  - skipping folder: {sub}/")
                continue
            files += list_remote_files(urljoin(url, href), rel_prefix + href, skip_dirs)
        else:
            files.append(rel_prefix + href)
    return sorted(set(files))


def remote_size(url):
    try:
        r = SESSION.head(url, timeout=60, allow_redirects=True)
        return int(r.headers.get("Content-Length", -1))
    except Exception:
        return -1


def download_file(url, dest, retries=3):
    """Download with resume-by-skip and retries."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    expected = remote_size(url)

    if dest.exists() and expected > 0 and dest.stat().st_size == expected:
        return "skipped"

    tmp = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(1, retries + 1):
        try:
            with SESSION.get(url, stream=True, timeout=120) as r:
                r.raise_for_status()
                total = int(r.headers.get("Content-Length", 0))
                with open(tmp, "wb") as f, tqdm(
                    total=total, unit="B", unit_scale=True,
                    desc=dest.name[:40], leave=False,
                ) as bar:
                    for chunk in r.iter_content(chunk_size=1024 * 256):
                        f.write(chunk)
                        bar.update(len(chunk))
            tmp.replace(dest)
            return "downloaded"
        except Exception as e:
            print(f"    attempt {attempt}/{retries} failed for {dest.name}: {e}")
            time.sleep(3 * attempt)
    if tmp.exists():
        tmp.unlink()
    return "failed"


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_checksums(dest_dir):
    sums_file = dest_dir / "SHA256SUMS.txt"
    sums = {}
    if sums_file.exists():
        for line in sums_file.read_text().splitlines():
            parts = line.strip().split(maxsplit=1)
            if len(parts) == 2:
                sums[parts[1].lstrip("*")] = parts[0]
    return sums



def main():
    ap = argparse.ArgumentParser(description="Download PhysioNet Pulse Transit Time PPG v1.1.0")
    ap.add_argument("--wfdb-only", action="store_true",
                    help="Skip the csv/ folder (saves ~2.4 GB). WFDB files contain the same signals.")
    ap.add_argument("--no-verify", action="store_true", help="Skip SHA256 verification")
    args = ap.parse_args()

    print(f"Project root : {PROJECT_ROOT}")
    print(f"Destination  : {DEST_DIR}")
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    METADATA_DIR.mkdir(parents=True, exist_ok=True)

    print("\n[1/3] Listing files on PhysioNet ...")
    skip = ("csv",) if args.wfdb_only else ()
    files = list_remote_files(BASE_URL, skip_dirs=skip)
    print(f"  found {len(files)} files")

    print("\n[2/3] Downloading ...")
    stats = {"downloaded": 0, "skipped": 0, "failed": 0}
    failed = []
    for rel in tqdm(files, desc="Files", unit="file"):
        status = download_file(urljoin(BASE_URL, rel), DEST_DIR / rel)
        stats[status] += 1
        if status == "failed":
            failed.append(rel)
    print(f"  {stats}")

    bad = []
    if not args.no_verify:
        print("\n[3/3] Verifying SHA256 checksums ...")
        sums = load_checksums(DEST_DIR)
        for rel in tqdm(files, desc="Verify", unit="file"):
            if rel in sums and (DEST_DIR / rel).exists():
                if sha256_of(DEST_DIR / rel) != sums[rel]:
                    bad.append(rel)
        print("  all checksums OK" if not bad else f"  {len(bad)} file(s) FAILED checksum: {bad[:10]}")
    else:
        print("\n[3/3] Verification skipped")

    
    meta = {
        "dataset": "Pulse Transit Time PPG Dataset",
        "source": "PhysioNet",
        "version": VERSION,
        "url": f"https://physionet.org/content/{DATASET_SLUG}/{VERSION}/",
        "license": "Open Data Commons Open Database License v1.0",
        "local_path": str(DEST_DIR.relative_to(PROJECT_ROOT)),
        "wfdb_only": args.wfdb_only,
        "n_files": len(files),
        "download_stats": stats,
        "failed_files": failed,
        "checksum_failures": bad,
        "downloaded_at": datetime.now().isoformat(timespec="seconds"),
    }
    meta_path = METADATA_DIR / "physionet_pulse_transit_time_ppg.json"
    meta_path.write_text(json.dumps(meta, indent=2))
    print(f"\nMetadata saved -> {meta_path}")

    if failed or bad:
        print("\nSome files had problems - just run the script again to retry them.")
        sys.exit(1)
    print("\nDone!")


if __name__ == "__main__":
    main()