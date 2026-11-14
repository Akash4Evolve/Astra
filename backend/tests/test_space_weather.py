"""Space-weather fetcher, tested with a fake internet (no real network calls)."""
import json
import sys
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from fetch_space_weather import fetch_all, latest_10mev, s_level  # noqa: E402

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
PROTONS = [
    {"time_tag": "2026-11-14T11:50:00Z", "satellite": 19, "flux": 0.42, "energy": ">=10 MeV"},
    {"time_tag": "2026-11-14T11:55:00Z", "satellite": 19, "flux": 12.5, "energy": ">=10 MeV"},
    {"time_tag": "2026-11-14T11:55:00Z", "satellite": 19, "flux": 0.1, "energy": ">=100 MeV"},
]


def fake_internet(fail_primary_donki=False, fail_goes=False):
    calls = []

    def fetch(url):
        calls.append(url)
        if "swpc" in url:
            if fail_goes:
                raise urllib.error.URLError("no route")
            return PROTONS if "proton" in url else [{"time_tag": "x", "flux": 1e-7}]
        if "api.nasa.gov" in url and fail_primary_donki:
            raise urllib.error.URLError("rate limited")
        return [{"activityID": "2026-11-10-FLR-001"}]
    return fetch, calls


def test_s_scale_levels():
    assert s_level(0.4) == "below S1" and s_level(10) == "S1" and s_level(150) == "S2"
    assert s_level(1e5) == "S5"


def test_latest_10mev_reading_is_picked():
    assert latest_10mev(PROTONS)["flux"] == 12.5
    assert latest_10mev([{"energy": ">=100 MeV", "flux": 1}]) is None


def test_fetch_saves_files_and_log(tmp_path):
    fetch, calls = fake_internet()
    log = fetch_all(30, root=tmp_path, fetch=fetch, now=NOW, api_key="SECRET123")
    assert all(e["status"] == "ok" for e in log) and len(log) == 6
    goes = tmp_path / "data/raw/nasa_radiation/goes"
    assert (goes / "latest_integral-protons-7-day.json").exists()
    assert (goes / "20261114T1200Z_integral-protons-7-day.json").exists()
    assert (tmp_path / "data/raw/nasa_space_weather/donki/latest_FLR.json").exists()
    protons = next(e for e in log if "proton" in e["product"])
    assert protons["latest_10MeV"]["indicative_s_level"] == "S1"
    flr = next(e for e in log if e["product"].startswith("FLR"))
    assert "startDate=2026-10-15" in calls[2] and flr["records"] == 1

    saved = (tmp_path / "data/metadata/space_weather_fetch_log.json").read_text()
    assert "SECRET123" not in saved  # API key is never written to disk
    fetch_all(30, root=tmp_path, fetch=fetch, now=NOW, api_key="SECRET123")
    assert len(json.loads(saved := (tmp_path / "data/metadata/space_weather_fetch_log.json").read_text())) == 2


def test_falls_back_to_ccmc_and_survives_failures(tmp_path):
    fetch, calls = fake_internet(fail_primary_donki=True, fail_goes=True)
    log = fetch_all(7, root=tmp_path, fetch=fetch, now=NOW, api_key="K")
    donki = [e for e in log if e["source"] == "NASA DONKI"]
    assert all(e["status"] == "ok" and "kauai.ccmc" in e["url"] and "error" not in e for e in donki)
    goes = [e for e in log if e["source"] == "NOAA SWPC GOES"]
    assert all(e["status"] == "failed" and "hint" in e for e in goes)
