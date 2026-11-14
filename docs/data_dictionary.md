# Data dictionary (backend)

Definitions of what the ASTRA API stores and returns. The simulated crew CSV used by the frontend has its own dictionary at `Astra/src/data/data_dictionary.csv`.

All timestamps are ISO 8601 **with a timezone** (requests without one are rejected) and are stored in UTC.

## Measurement (`POST /api/v1/measurements`, inside `POST /api/v1/sync`)

| Field | Type | Meaning |
|---|---|---|
| `record_id` | UUID | Chosen by the sender. The same ID is never stored twice, so retries are safe. |
| `astronaut_id` | string | Crew member, e.g. `FE-02`, `AST-001` |
| `device_id` | string or null | Source device, e.g. `CREWBAND-FE-02` |
| `timestamp_utc` | datetime | When the reading was taken (source time) |
| `received_at` | datetime | When it reached ASTRA; later than `timestamp_utc` for buffered readings |
| `parameter` | enum | See Parameters |
| `value` | number | In the parameter's unit |
| `unit` | string | Must match the parameter's unit exactly |
| `source_type` | enum | See Source types |
| `quality_status` | enum | See Quality statuses. Only `VALID` readings are used for baselines and alerts. |
| `is_simulated` | bool | Must be true exactly when `source_type` is `SIMULATED` |
| `metadata` | object | Free-form context, e.g. `{"mission_day": 143}` |

## Parameters

| `parameter` | Unit | Accepted range | Minimum baseline spread | Domain |
|---|---|---|---|---|
| `heart_rate` | `bpm` | 20–250 | 2.0 bpm | cardiovascular |
| `skin_temperature` | `degC` | 10–45 | 0.2 °C | physiological |
| `sleep_hours` | `h` | 0–24 | 0.4 h | behavioural |

The accepted range only rejects impossible values; it is not a clinical range. Self-report scores (`mood`, `stress`, `fatigue`) appear in trends and the dashboard from check-ins, without a statistical baseline.

## Enumerations

| Name | Values |
|---|---|
| Source types | `DEVICE`, `SIMULATED`, `MANUAL` (typed by a person), `NASA_RESEARCH`, `PUBLIC_RESEARCH`, `CLINICAL` |
| Quality statuses | `VALID`, `SUSPECT`, `MISSING`, `STALE` |
| Alert levels | `WATCH` (2 readings in a row outside the band), `REVIEW` (3 or more). `INFO` exists but is not raised. No mission-escalation level: that needs an authorised protocol. |
| Alert status | `OPEN`, `ACKNOWLEDGED` |
| Action types | `NOTE`, `FOLLOW_UP_MEASUREMENT`, `PROTOCOL_FOLLOWED`, `ESCALATION_REQUESTED` |
| Action outcome | `PENDING`, `COMPLETED`, `NOT_NEEDED` |
| Roles (`X-ASTRA-Role`) | `device`, `astronaut`, `crew_medical_officer`, `ground` |
| Audit event types | `MEASUREMENTS_INGESTED`, `CHECKIN_RECORDED`, `ALERT_CREATED`, `ALERT_LEVEL_CHANGED`, `ALERT_ACKNOWLEDGED`, `ACTION_RECORDED`, `SYNC_APPLIED`, `SYNC_DUPLICATE_IGNORED`, `PPG_QUALITY_ASSESSED` |
| Twin domain states | `CHANGE_FROM_BASELINE`, `CHANGE_ACKNOWLEDGED`, `WITHIN_PERSONAL_BASELINE`, `LOW_QUALITY_DATA`, `BUILDING_BASELINE`, `NO_DATA`, `NOT_CONNECTED` |

## Check-in (`POST /api/v1/check-ins`)

| Field | Type | Meaning |
|---|---|---|
| `checkin_id` | UUID | Chosen by the sender; duplicates are ignored |
| `astronaut_id` | string | |
| `timestamp_utc` | datetime | |
| `sleep_hours` | number 0–24 | Also stored as a `sleep_hours` measurement (same ID), so it feeds the sleep baseline |
| `mood`, `stress`, `fatigue` | integer 1–5 | 1 = low, 5 = high (the Astra app maps its 0–10 stress and fatigue scales onto this) |
| `symptoms` | list of strings | Up to 20, each 1–60 characters |
| `note` | string or null | Up to 500 characters |
| `source_type` | `MANUAL` or `SIMULATED` | |

## Alert (`GET /api/v1/alerts`)

| Field | Meaning |
|---|---|
| `alert_id` | `ALT-` + 8 hex characters |
| `parameter`, `domain`, `level`, `title`, `status` | See above |
| `created_at`, `acknowledged_at` | Server time |
| `explanation.observed` | Plain-language description of the run |
| `explanation.comparison_window` | Baseline dates and sample count |
| `explanation.data_quality` | `VALID`, or how many readings were excluded |
| `explanation.evidence_record_ids` | The readings the alert is based on (traceable to measurements and check-ins) |
| `explanation.model` | `robust_baseline_v2+persistence_v1` |
| `explanation.baseline_centre`, `baseline_dispersion`, `latest_robust_z`, `persistence_count`, `z_threshold` | The numbers behind the decision |
| `next_step` | General prompt; never a diagnosis or treatment |
| `diagnosis` | Always null |

An alert covers one **episode**, identified by its first evidence reading. New readings in the same episode update it (and may raise its level) instead of creating a new alert. An acknowledged episode is not raised again.

## Action (`POST /api/v1/actions`)

`alert_id`, `action_type`, `note` (required for `NOTE`), `follow_up_at` (required for `FOLLOW_UP_MEASUREMENT`), `outcome`. The server assigns `action_id` (`ACT-…`), `astronaut_id` and `timestamp_utc`. Actions are append-only.

## Sync batch (`POST /api/v1/sync`)

`batch_id` (sender-chosen; a repeated ID returns `DUPLICATE_BATCH` and changes nothing), `source_node`, `created_at`, `measurements[]`, `checkins[]`. The response reports counts accepted/duplicate, alerts raised and `max_delivery_delay_seconds` (how late the oldest reading arrived).

## Audit event (`GET /api/v1/audit`)

`event_id`, `timestamp_utc` (server), `event_type`, `actor` (`api_client`, `system` or `sync`: the channel, not a verified person), `role` (declared, may be null), `astronaut_id`, `entity_type`, `entity_id`, `details`. Never edited or deleted.

## Experimental PPG quality (`POST /api/v1/experimental/ppg-quality`)

Request: `ppg[]` (one channel, any units), `ppg_fs` (Hz, ≥ 20), `acc_g[]` (`[x, y, z]` in g), `acc_fs` (Hz, ≥ 10), optional `astronaut_id`, `device_id`, `window_start_utc`. The window must last 10 s ± 5%.
Response: `verdict` (`LIKELY_RELIABLE`, `LIKELY_UNRELIABLE`, `CANNOT_ASSESS`), `p_unreliable`, `threshold`, `ppg_hr_bpm`, `suggested_quality_status`, `reason`, `features`, `model`. See `docs/model_card_ppg_quality.md`.
