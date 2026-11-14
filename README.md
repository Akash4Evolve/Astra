# ASTRA: crew health monitoring for long-duration missions

NASA Space Apps 2026 entry for *Create Health Monitoring Software for Astronauts on Space Missions*.

ASTRA collects health readings (wearable, self-report check-ins), compares each astronaut against **their own** baseline, raises **explainable** alerts, and lets the crew acknowledge and act on them, while working through a delayed or dropped link to the ground. It never diagnoses. **All astronaut data in this repository is simulated.**

| Part | Folder | What it is |
|---|---|---|
| Backend API | `backend/app` | FastAPI: ingest, alerts, check-ins, actions, dashboard, trends, Digital Twin, offline sync, audit trail, roles, experimental PPG quality gate; in-memory or SQLite storage |
| Analytics | `ml/src/astra_ml` | Robust personal baseline + persistence rule; PPG signal-quality model |
| Frontend | `Astra/` | React app for the crew (see `Astra/README.md`); runs alone in demo mode or against the backend |
| Scripts | `scripts/` | Simulator, one-command demo, crew-data server, backup recorder, dataset download |
| Docs | `docs/` | Data dictionary, limitations, model card, evaluation, latency |

## Quick start (Windows, Python 3.11, Node 20+)

```bash
pip install -r requirements.txt
python -m pytest -q
```

**The judge story in one command** (starts its own API, streams simulated data, drops the link, syncs late, raises an alert, acknowledges it, shows the Twin and audit trail, measures latency):

```bash
python scripts/demo.py
```

**Backend + frontend together**: terminal 1 starts the API preloaded with the simulated crew dataset (mission days 1-143):

```bash
python scripts/serve_crew.py
```

Terminal 2, in `Astra/`:

```bash
cp .env.example .env.local
npm install
npm run dev
```

Open http://localhost:5173. Swagger UI: http://127.0.0.1:8000/docs.

To keep data (check-ins, acknowledgements, actions, audit trail) across restarts, add `--db data/astra.db`. Without it the store is in memory and every restart starts clean, which is what you want before a live demo.

**Frontend alone** (no Python at all): in `Astra/`, leave `VITE_API_URL` unset and run `npm run dev`.

## How it works

1. **Readings** arrive at `POST /api/v1/measurements` (live) or `POST /api/v1/sync` (a batch buffered while offline; resending the same `batch_id` is ignored). Every record carries its source time, source type and quality status; duplicates (same `record_id`) are never stored twice.
2. **Baseline**: for each astronaut and parameter, median ± robust spread (scaled MAD, with a minimum per parameter) over the first 14 days. Model `robust_baseline_v2`.
3. **Alert rule** `persistence_v1`: 2 valid readings in a row more than 3 robust SDs from the baseline is **Watch**; 3 or more is **Review**. Readings not marked `VALID` break the run, so noisy data can't build an alert. Each alert lists the observed change, comparison window, data quality, the record IDs it is based on, and a next step. `diagnosis` is always null.
4. **Response**: the crew acknowledges (means "seen", not medical clearance) and records actions (note, follow-up measurement, protocol followed, escalation requested). Actions are append-only.
5. **Digital Twin** (`/astronauts/{id}/twin`): a bounded per-domain summary against the astronaut's own baseline. Domains with no data source stay `NOT_CONNECTED` and are never filled in.
6. **Audit trail** (`/audit`): every change, with the declared role.
7. **Storage**: in memory by default, or SQLite with `ASTRA_DB=<file>` (same behaviour, checked by running the whole test suite on both). In SQLite the audit trail and actions are append-only at the database level too.

## Endpoints

| Method | Path | Role (when enforced) |
|---|---|---|
| GET | `/` (name, version, links to the docs) | any |
| POST | `/api/v1/measurements` | device |
| POST | `/api/v1/sync` | device |
| GET | `/api/v1/sync/status`, `/api/v1/sync/log` | any / device, CMO, ground |
| POST | `/api/v1/check-ins` | astronaut, CMO, device |
| GET | `/api/v1/alerts`, `/api/v1/alerts/{id}` | any |
| POST | `/api/v1/alerts/{id}/acknowledge` | astronaut, CMO |
| POST / GET | `/api/v1/actions` | astronaut, CMO / any |
| GET | `/api/v1/astronauts/{id}/dashboard`, `/trends`, `/twin` | any |
| GET | `/api/v1/devices/{id}/status` | any |
| GET | `/api/v1/audit` | CMO, ground |
| GET / POST | `/api/v1/experimental/ppg-quality` | any / device |

Errors always look like `{"error": {"code": ..., "message": ...}}`.

## Roles and logging

- **Roles are declared, not authenticated.** A client says who it is with `X-ASTRA-Role: device | astronaut | crew_medical_officer | ground`. The role is recorded in the audit trail. With `ASTRA_REQUIRE_ROLES=1`, writes and the audit trail are refused for the wrong role (reads stay open). `demo.py` and `serve_crew.py` turn enforcement on; the frontend sends `astronaut`. Anyone who can reach the API can claim any role, so this prevents mistakes, not attacks.
- **Logging**: one line per request (request ID, method, path, status, duration, role) on the `astra` logger; level via `ASTRA_LOG_LEVEL`. Health values are never logged. Each response has an `X-Request-ID`.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `ASTRA_DB` | unset (in memory) | SQLite file to keep data in, e.g. `data/astra.db` |
| `ASTRA_CORS_ORIGINS` | `http://localhost:5173,http://localhost:3000` | Comma-separated browser origins allowed to call the API |
| `ASTRA_REQUIRE_ROLES` | off | `1` to enforce roles |
| `ASTRA_LOG_LEVEL` | `INFO` | Python log level |
| `ASTRA_PPG_MODEL` | `models/ppg_quality_combined_rf.joblib` | Model file for the experimental gate |
| `VITE_API_URL` (frontend) | unset (demo mode) | Backend URL for `Astra/` |

## Data

- **Simulated crew dataset** `Astra/src/data/astronaut_health_simulated.csv`: 3 fictional crew × 180 days with planted events (solar particle event, CO₂ scrubber fault, sleep disruption, infection, EVAs). Used by the frontend and by `serve_crew.py`. Columns are described in `Astra/src/data/data_dictionary.csv`.
- **Synthetic scenarios** (`ml/src/astra_ml/scenarios.py`): labelled 21-day series for testing and `docs/evaluation.md`.
- **Real public data, used only for the PPG model and context**: PhysioNet Pulse Transit Time PPG, WESAD, NASA DONKI space weather. Download with `python scripts/download_datasets.py` (about 2.5 GB, needs internet). Raw data and trained models are not committed.

Field-by-field definitions: [docs/data_dictionary.md](docs/data_dictionary.md).

## Results

- **Synthetic scenarios** ([docs/evaluation.md](docs/evaluation.md), 200 seeds): 0% alerts on stable, noisy, missing, dropout, stale and motion-artifact scenarios; 84% of gradual drifts and 97% of repeated deviations caught.
- **Simulated crew dataset** (`python scripts/eval_crew_alerts.py`): 4 alerts in 540 crew-days; 3 on planted events (FE-02 infection, MS-03 sleep disruption, CDR-01 sleep during the CO₂ fault), 1 false.
- **Experimental PPG quality gate** ([docs/model_card_ppg_quality.md](docs/model_card_ppg_quality.md)): person-wise, catches 91% of unreliable windows (AUROC 0.90) on real PhysioNet + WESAD data.
- **Latency** ([docs/latency.md](docs/latency.md)): about 1.5 ms median per request on a laptop, in-memory store.

## Limitations

Read [docs/limitations.md](docs/limitations.md) before presenting any result. In short: simulated astronaut data, no clinical validation, single-node storage, declared (not authenticated) roles, and thresholds that are demo assumptions.

## If the demo fails

`python scripts/make_demo_backup.py` records a full demo transcript and a snapshot of the crew API state into `demo_backup/`. See `demo_backup/README.md` for the fallback order.

## Tests

```bash
python -m pytest -q
```

The same suite on the SQLite store (bash; in PowerShell set `$env:ASTRA_DB=":memory:"` first):

```bash
ASTRA_DB=":memory:" python -m pytest -q
```

Tested versions are pinned in `requirements-lock.txt`.
