# Astra: crew health monitor (frontend)

Frontend for our NASA Space Apps 2026 entry: astronaut health monitoring and decision support for long-duration missions. React + TypeScript + Vite, charts with Recharts. Fonts are bundled locally, so the app works with no internet connection.


## Run

```bash
npm install
npm run dev        # http://localhost:5173
npm run build      # production build in dist/
```

With no backend configured, the app runs in **demo mode** on the simulated crew dataset (`src/data/astronaut_health_simulated.csv`: 3 fictional crew × 180 mission days, described in `src/data/data_dictionary.csv`). Pick the crew member and mission day in the demo bar under the header, or use its **Jump to a scenario** list. Every simulated value is tagged "Simulated" in the UI.

### Install Astra as an offline desktop app

Astra is a local, onboard app: everything it needs is bundled, data is saved on the device first, and it only talks to the ground when a link is available. To run it as an installed app instead of a browser tab:

1. Run `npm install` once, then `npm run app`. This builds Astra and serves it at http://localhost:4173.
2. Open http://localhost:4173 in Chrome or Edge.
3. Click the install icon at the right of the address bar (or the browser menu → *Install Astra*).
4. Astra now has its own desktop and Start menu icon and opens in its own window. It runs fully offline, with no terminal, server or internet needed.

After changing the code, run `npm run app` again and open Astra once while it is running; the installed copy updates itself. `npm run dev` is unaffected and never installs anything.

Only the app's own files are saved for offline use. Requests to a backend (`VITE_API_URL`) are never cached.

> **Windows note:** Windows' App Control policy on this machine blocks some native Node binaries. The project uses the WebAssembly build of Rollup (`@rollup/wasm-node`, via `overrides` in `package.json`) so the offline build works. `npm run lint` is still blocked by the same policy.

### Checking the alert rules

```bash
npx tsx scripts/verify-alerts.ts
```

This compares the alerts against the dataset's planted events (the `event` column). The app itself never reads that column. Current result: every day of all five planted events is caught (43 of 43 event days), with 2 false alarms in 540 crew-days (CDR-01 day 140: one short night with high stress; FE-02 day 132: warm two days running). EVA days correctly raise no alert.

### Running with the ASTRA backend

From the repo root, start the API preloaded with the same simulated crew dataset (days 1–143 by default):

```bash
python scripts/serve_crew.py
```

Then, in `Astra/`, point the app at it and start the dev server:

```bash
cp .env.example .env.local   # VITE_API_URL=http://127.0.0.1:8000
npm run dev
```

With a backend set, resting heart rate and sleep (readings, personal baseline and alerts) come from the backend; everything else still comes from the bundled dataset (`src/api/backend.ts` does the mapping). Check-ins, acknowledgements, actions, rechecks and escalations on backend alerts (IDs `ALT-…`) are sent when the ground link is up. Responses to the app's own alerts stay on the device, since the backend has no record of them. The backend store is in memory, so restarting `serve_crew.py` starts it over. The Crew page still uses the bundled dataset only.

## Screens

| Route | What it does | Brief owner |
|---|---|---|
| `#/overview` | Latest vitals against personal baseline, body systems status, trends (24h/7d/30d), alerts, cabin context, today's schedule | Member 1 |
| `#/crew` | All crew on the same mission day: status, key readings and alerts per person, the mission so far for everyone, a note when the same alert shows in several people, and a plain-text handover report for the ground (demo mode only; a backend would need a crew endpoint) | Both |
| `#/trends` | Any metric over time with the baseline band; table of every reading vs. its usual range | Member 1 |
| `#/alerts`, `#/alerts/:id` | Explainable alert: what changed, rule, time window, data quality + confidence, related signals, next steps, when to escalate | Member 2 |
| (alert detail) | Response workflow: acknowledge, log an action, schedule a recheck, escalate to crew medical officer or mission control | Member 2 |
| `#/checkin` | Daily check-in: mood, stress, fatigue, sleep quality, exertion (Borg CR10), symptoms. Draft auto-saves | Member 2 |
| `#/log` | Action log with send status of each record | Member 2 |
| `#/data` | Ground-link toggle (demo), data provenance key, demo reset | Both |

## Demo walkthrough (about 2 minutes)

The dashed **Demo data** bar under the header holds every demo control, so it reads as tooling and not as part of the product.

1. Pick **Jump to a scenario → Mild infection in the crew medical officer**. The status summary at the top names the alert and offers **Review and respond**.
2. Set the day to 137 and press **Play mission**. Days advance one at a time and playback pauses by itself on day 141, when the temperature alert first appears.
3. On **Your mission so far**, click the tall bars around day 62 (solar particle event) or days 95–99 (CO₂ fault). Bar height and colour both show the day's status; days after the one being viewed are left blank.
4. Open **Crew** on day 62 or 97: all three crew show the same alert, and the page says a shared cause is more likely than an individual one. **Download report** gives the handover text for the ground.
5. Click any vital tile to open its trend against the personal baseline.

The mission strip and crew view use the same alert rules as the dashboard (`missionHistory` in `src/data/crew.ts`); neither reads the `event` column.

## How it maps to the brief

- **Status states** are Normal / Watch / Needs review, shown with colour, an icon and text (never colour alone).
- **Personal baseline**: usual range = 21-day mean ± 2 SD, leaving out the most recent 7 days and any spell that was already out of range, so a long bad patch can't become the new normal (`src/data/crew.ts`, `baselines`). The ML module should replace this. Keep the same `Baseline` shape.
- **Alert rules** (`src/data/crew.ts`, `RULES`): radiation dose spike (> 3× the 14-day median), cabin CO₂ limit, fever, short sleep with stress or low mood, and resting HR, HRV, SpO₂ and headache. Related alerts are grouped (for example, a headache during a CO₂ fault is shown inside the CO₂ alert). Fixed limits are in `LIMITS`, each with its source:

  | Limit | Value | Source |
  |---|---|---|
  | Cabin CO₂ | Above 3 mmHg for 3 days in a row; needs review above 4.5 mmHg | [NASA-STD-3001 Vol. 2 Rev D, V2 6004](https://www.nasa.gov/wp-content/uploads/2023/12/ochmo-tb-004-carbon-dioxide.pdf) (1-hour average ≤ 3 mmHg); symptoms above 4.5 mmHg from the same NASA OCHMO CO₂ brief. The 3-day rule is ours: the dataset has daily averages, and 51 normal days sit just over 3 mmHg |
  | Radiation | 600 mSv career; 250 mSv solar particle event | [NASA-STD-3001 Vol. 1 Rev B](https://www.nasa.gov/wp-content/uploads/2020/10/2022-01-05_nasa-std-3001_vol.1_rev._b_final_draft_with_signature_010522.pdf) |
  | Radiation spike | Daily dose > 3× the 14-day median | Astra's own rule (NASA's limits are on total dose) |
  | Fever | 38.0 °C (100.4 °F); below that, above personal range plus a second sign | CDC fever definition (confirmed only via secondary sources) |
  | SpO₂ | Watch below 95%; review at 92% or lower | Commonly cited clinical guidance; no primary NHS/FDA page confirmed |

  No public NASA limit was found for fever or SpO₂, so those use general clinical guidance.
- **Crew medical officer as patient**: when the CMO's own readings raise an alert, escalation goes to mission control, and the option to escalate to themselves is disabled.
- **HRP hazards**: every metric and alert is tagged with one of NASA's five hazards (from the data dictionary). Trends are grouped by hazard. "Distance from Earth" has no metric in the dataset.
- **Clickable body** (the challenge's own example): click a dot on the 3D body or a system in the list to see what it does, how spaceflight affects it, its readings, alerts and self-care, with sources (`src/data/guide.ts`, written from the NASA HRP hazards and risks pages in the challenge resources).
- **Reading explainers**: every reading on the Trends page has a "What it is / How to measure / Why it matters in space / When to get help" card.
- **Log a measurement** (`#/measure`): enter blood sugar (mg/dL, fasting or not), blood pressure, temperature, heart rate or SpO₂ and get an immediate explained result. Blood sugar uses general clinical ranges (ADA), not spaceflight-specific ones, so confirm with a flight surgeon.
- **No 24h view** for the crew dataset, as it has one reading per day. The 24h tab appears only for metrics with readings through the day.
- **Provenance**: every reading carries `sensor`, `self-report` or `simulated`.
- **Data quality**: stale readings (> 6 h) and degraded readings (e.g. the wrist-sensor dropout last night) are flagged on the tile.
- **Offline-first**: check-ins and actions are saved to `localStorage` and queued. They are sent when the ground link is up (`src/store.tsx`). Switch to IndexedDB if the data grows.
- **Demo scenarios**: solar particle event (day 62, all crew), CO₂ scrubber fault (days 95–99), MS-03 sleep disruption (days 120–130), FE-02 mild infection while being the CMO (days 141–145), and EVA days (no alert expected).
- **Not included on purpose**: a chatbot (the brief rates it less defensible than explainable alerts), and "immune function" or bone scores from wearables (they can't be measured that way).

## API contract

Types are in `src/types.ts`. The client is `src/api/client.ts`:

```
GET  /api/v1/dashboard                 -> Dashboard
POST /api/v1/checkins                  <- CheckIn
POST /api/v1/alerts/{id}/acknowledge   <- ActionRecord
POST /api/v1/actions                   <- ActionRecord
```

`Dashboard` contains `profile`, `metrics` (keyed by `MetricId`, each with `daily`, optional `hourly`, `baseline`, `status`, `provenance`, `quality`), `alerts` and `schedule`. Agree this with Members 3–5 and freeze it before parallel work.

## Files

```
src/
  types.ts            shared API types
  api/client.ts       backend client + demo fallback
  data/crew.ts        CSV loader, personal baselines and alert rules
  data/crewData.ts    bundled simulated dataset and demo scenario shortcuts
  store.tsx           local-first state, sync queue
  derive.ts           domain status rollup
  router.ts           hash router
  components/         ui (chips, icons, panels), charts, MissionTimeline, BodyMap (2D fallback), Model3D
  components/three/   procedural 3D models; three.js loads only when one is on screen
  report.ts           plain-text crew handover report
  views/              Overview, Crew, Trends, Alerts, CheckIn, Log (+ DataSync)
  styles.css          design tokens and layout
```

## Credits

- 3D body: [Anatomy study 2.0 Basemesh Human Male Body](https://sketchfab.com/3d-models/anatomy-study-20-basemesh-human-male-body-c3f13a4baa2f4ea5a0a88d29e7fa1779) by zeroran, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Simplified (`public/models/body.glb`) and recoloured in the app. Keep this credit in the app and README.

## Before the demo

- Next steps in alerts cite NASA OCHMO technical briefs (radiation, CO₂, sleep, in-flight care, health stabilization) and NASA HRP risks where possible. Steps with no public source are tagged "General guidance" in the app. Have the team review the wording.
- Check that NASA-STD-3001 Vol. 1 Rev B is still the current radiation volume.
- The simulated values come from typical figures, not NASA sources; the ~0.7 mSv/day dose is unverified (see `docs/HANDOFF_nasa_space_apps.md`).
- Re-check the official challenge page's resources section, which hadn't been read when the handoff was written.
- Don't use the NASA logo in the app; Space Apps rules restrict use of NASA insignia.
