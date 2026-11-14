"""Dataset downloader, tested with a fake internet and a tiny fake WESAD zip."""
import csv
import json
import sys
import urllib.error
import zipfile
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from download_datasets import download_donki, download_wesad, extract_wesad, year_ranges  # noqa: E402


def quiet(_):
    pass


def test_year_ranges():
    assert year_ranges(date(2024, 6, 1), date(2026, 2, 3)) == [
        ("2024-06-01", "2024-12-31"), ("2025-01-01", "2025-12-31"), ("2026-01-01", "2026-02-03")]


def test_donki_writes_json_and_csv_in_requested_layout(tmp_path):
    calls = []

    def fetch(url):
        calls.append(url)
        if "api.nasa.gov" in url:
            raise AssertionError("fallback should not be needed")
        typ = url.split("/get/")[1].split("?")[0]
        year = url.split("startDate=")[1][:4]
        idf = {"SEP": "sepID", "RBE": "rbeID", "CME": "activityID", "FLR": "flrID"}[typ]
        rec = {idf: f"{year}-{typ}-001", "eventTime": f"{year}-03-01T00:00Z",
               "linkedEvents": [{"activityID": "x"}], "note": None}
        return [rec, rec]  # duplicate inside the response is removed

    counts = download_donki(date(2024, 1, 1), date(2025, 12, 31), root=tmp_path, fetch=fetch,
                            pause=0, log=quiet)
    # One request per type for the whole range (the downloader only splits by year if that fails),
    # and the duplicate inside each response is removed.
    assert counts == {"SEP": 1, "RBE": 1, "CME": 1, "FLR": 1}
    assert len(calls) == 4 and all("startDate=2024-01-01&endDate=2025-12-31" in u for u in calls)
    out = tmp_path / "data/raw/nasa_radiation"
    assert sorted(p.name for p in out.iterdir()) == sorted(
        f"{t}.{ext}" for t in ("SEP", "RBE", "CME", "FLR") for ext in ("json", "csv"))
    rows = list(csv.DictReader(open(out / "RBE.csv", encoding="utf-8")))
    assert rows[0]["rbeID"] == "2024-RBE-001" and json.loads(rows[0]["linkedEvents"])[0]["activityID"] == "x"
    assert rows[0]["note"] == ""
    assert len(json.loads((tmp_path / "data/metadata/download_log.json").read_text())) == 4


def test_donki_falls_back_and_never_logs_the_key(tmp_path):
    def fetch(url):
        if "kauai" in url:
            raise urllib.error.URLError("down")
        return [{"flrID": "A"}] if "FLR" in url else []

    counts = download_donki(date(2025, 1, 1), date(2025, 1, 31), root=tmp_path, fetch=fetch,
                            api_key="SECRET", pause=0, log=quiet)
    assert counts["FLR"] == 1 and counts["SEP"] == 0
    assert "SECRET" not in (tmp_path / "data/metadata/download_log.json").read_text()


def make_zip(path: Path, subjects=(2, 3)) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("WESAD/wesad_readme.pdf", b"readme")
        for n in subjects:
            z.writestr(f"WESAD/S{n}/S{n}.pkl", b"fake-pickle")
            z.writestr(f"WESAD/S{n}/S{n}_quest.csv", b"q")
    return path


def test_wesad_extracts_only_subject_pickles(tmp_path):
    z = make_zip(tmp_path / "w.zip")
    assert extract_wesad(z, root=tmp_path, log=quiet) == 2
    target = tmp_path / "data/raw/wesad/WESAD"
    assert sorted(p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file()) == [
        "S2/S2.pkl", "S3/S3.pkl"]
    assert extract_wesad(z, root=tmp_path, log=quiet) == 2  # re-run skips existing files


def test_wesad_download_uses_downloader_then_extracts(tmp_path):
    def fake_download(url, dest, log):
        make_zip(dest, subjects=(2, 3, 4))
        return dest

    assert download_wesad(root=tmp_path, downloader=fake_download, log=quiet) == 3


def test_wesad_download_failure_explains_manual_route(tmp_path):
    msgs = []

    def broken(url, dest, log):
        raise urllib.error.URLError("blocked")

    with pytest.raises(urllib.error.URLError):
        download_wesad(root=tmp_path, downloader=broken, log=msgs.append)
    assert any("--wesad-zip" in m for m in msgs)


def test_bad_zip_is_rejected(tmp_path):
    z = tmp_path / "x.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("other.txt", b"x")
    with pytest.raises(ValueError):
        extract_wesad(z, root=tmp_path, log=quiet)
