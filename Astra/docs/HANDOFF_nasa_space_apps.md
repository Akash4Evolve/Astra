# Handoff: NASA Space Apps 2026, astronaut health monitoring

Context from a research chat (13–14 Nov 2026) for the chat working on the frontend code.

## Challenge
- **Name:** Create Health Monitoring Software for Astronauts on Space Missions (Intermediate; Human Exploration / Software / Space Exploration)
- **Statement:** build health monitoring software that gathers health indicators and enables astronauts to evaluate and act on the status of their health.
- **Event:** 14–15 Nov 2026
- **Official resources section:** NOT read. spaceappschallenge.org was down (connection errors) when checked, and the archive copy was blocked. Re-check the challenge page and add anything listed there.
- **No official dataset seems to be provided**, so we're using simulated crew data, with real NASA data where it exists.

## Frontend status (built 4 Nov in an earlier chat)
- **"Baseline — crew health monitor":** React + TypeScript + Vite, Recharts, fonts bundled locally (works offline).
- **Screens:** Overview, Trends, Alerts (acknowledge / log action / recheck / escalate), Check-in, Action log, Data/sync.
- **Current demo data:** 30 days in `src/data/demo.ts`, built for two scenarios: resting HR raised for 4 days, and 3 short nights plus high stress (CO2 shown as context).
- **Baseline rule:** 21-day mean ± 2 SD, excluding the last 7 days (`baselineOf`).
- **API contract:** `/api/v1/dashboard`, `/api/v1/checkins`, `/api/v1/alerts/{id}/acknowledge`, `/api/v1/actions`. Types are in `src/types.ts`.
- **Open items from that chat:**
  - The "next step" text on alerts is placeholder.
  - Verify the 600 mSv career limit against the current NASA-STD-3001.

## New simulated dataset (attached)
- **`astronaut_health_simulated.csv`:** 540 rows (3 fictional crew × 180 mission days, one row per day), 28 columns.
  - Crew: CDR-01, FE-02 (the crew medical officer, CMO), MS-03
  - Dates start 2027-03-01.
- **`data_dictionary.csv`:** each column with its unit, description and HRP hazard.
- **Columns:**
  - heart_rate_rest_bpm, hrv_rmssd_ms, systolic/diastolic_bp_mmhg, spo2_pct, body_temp_c, resp_rate_bpm
  - sleep_hours, sleep_quality_1_10, mood_1_5, stress_0_10, reaction_time_ms, headache
  - body_mass_kg, hip_bmd_loss_pct, grip_strength_pct_preflight, exercise_min
  - radiation_dose_msv, cumulative_dose_msv
  - cabin_co2_mmhg, cabin_temp_c, cabin_noise_db
  - event (ground-truth label)
- **Planted events:**
  - **Days 61–63, solar particle event:** whole crew; dose peaks at about 11.6 mSv on day 62 against a normal ~0.7/day, and stress rises.
  - **Days 95–99, CO2 scrubber fault:** CO2 reaches 6–7 mmHg, with headaches, worse sleep and slower reaction time.
  - **Days 120–130, MS-03 sleep disruption:** about 4 h sleep a night, low mood, high stress, low HRV, slow reaction time.
  - **Days 141–145, FE-02 mild infection:** fever up to 38.3 °C, raised HR, lower SpO2. FE-02 is the CMO, so the crew's own medic is the one who is ill.
  - **EVA days:** CDR-01 on days 45, 46 and 110; MS-03 on days 45, 110 and 160. Extra dose and no exercise on those days.
- **Slow drifts:**
  - Hip bone density loss of about 1% a month (modelled).
  - Body mass and grip strength decline slowly.
  - Slight drop in BP and HR in the first weeks.
- **Caveat:** the values are simulated from typical figures, not NASA-sourced. The ~0.7 mSv/day ISS dose came from another team's write-up and is unverified. Cite real thresholds before judging.

## Integration work needed
1. **Loader:** write a loader that maps the CSV columns onto the types in `src/types.ts`.
2. **24h view:** the CSV has one row per day, but the 24h trend view needs readings within each day. Either generate intra-day readings around each daily value or hide 24h for the CSV source.
3. **Alerts:** check that the five planted events trigger alerts. Use the `event` column only to verify; the app logic must not read it.
4. **Organisation:** consider using the five HRP hazards as the top-level grouping (radiation, isolation & confinement, distance from Earth, gravity fields, hostile/closed environment). The dictionary maps each column to one.

## Real data sources worth wiring in (verified to exist; not confirmed as official challenge resources)
- **NASA OSDR:** https://osdr.nasa.gov/bio/
  - OSD-569 (blood counts)
  - OSD-575 (Inspiration4 serum metabolic panel)
  - Spaceflight Standard Measures
- **OSDR RadLab:** https://visualization.osdr.nasa.gov/radlab/ (DOSTEL, CRaTER, MSL-RAD dose)
- **NOAA GOES live solar protons:** https://services.swpc.noaa.gov/json/goes/primary/integral-protons-1-day.json (good for a live radiation alert)
- **NASA LSAH:** https://nlsp.nasa.gov/resources/lsah (CO2 and headache findings, medical requirements)
- **NASA HRP five hazards:** https://www.nasa.gov/hrp/hazards/ and the risks overview at https://www.nasa.gov/hrp/risks/
- **NTRS reports:**
  - 20190000238: ISS BP/ECG kit
  - 20090014820: sleep measurement
  - 20240004905: communication delay
  - 20150019624: CO2 operational bands
- **CSA Bio-Monitor:** https://www.asc-csa.gc.ca/eng/sciences/bio-monitor.asp (a model for the sensor/indicator set)
