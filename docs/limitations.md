# Limitations

Say these out loud when presenting. Each one is something ASTRA does **not** do or has **not** shown.

## Data and validation

1. **No real astronaut data.** Every astronaut reading in the repo is simulated: the crew dataset (`Astra/src/data`), the synthetic scenarios and the CrewBand simulator. Its typical values come from public figures and our own assumptions; the ~0.7 mSv/day ISS dose figure is unverified.
2. **No clinical validation.** Results show the logic behaves as designed on data we generated, with planted events we know about. They say nothing about real crew, real illness or real missions.
3. **Planted events are easy to find.** The crew dataset's events are larger and cleaner than real physiology. 3 of 4 crew-dataset alerts land on planted events; that number will not hold on real data.
4. **The PPG quality model was trained on healthy volunteers on Earth** (37 people, finger and wrist sensors), not astronauts, not microgravity, not CrewBand. It misses windows where the pulse signal locks cleanly onto a wrong rate. See `docs/model_card_ppg_quality.md`.

## Analytics

5. **Thresholds are demo assumptions, not clinical limits**: |robust z| > 3, 2 and 3 readings in a row, the 14-day baseline window, and the minimum spread per parameter (2.0 bpm, 0.4 h, 0.2 °C). They were tuned on simulated data.
6. **The baseline is fixed after the first 14 days.** Slow real changes over a long mission (deconditioning, adaptation) will eventually look like deviations. The frontend's own rules use a rolling 21-day baseline instead; the two do not agree everywhere.
7. **The backend analyses three parameters** (resting heart rate, skin temperature, sleep duration). Bone and muscle, immune function, radiation and cabin environment are shown as `NOT_CONNECTED`. The frontend shows more metrics, but those come from its bundled dataset and its own rules, not from the backend.
8. **Tuning trade-off.** Raising the minimum spread cut false alerts on the crew dataset from 25 to 1, but lowered detection of gradual drift in the synthetic scenarios from 92% to 84%.
9. **Self-report scales differ.** The app collects stress and fatigue on 0–10; the backend stores 1–5. The mapping is ours.

## System

10. **Storage is single-node.** By default the store is in memory and a restart loses everything. With `ASTRA_DB` data is kept in one SQLite file on the machine running the API: no replication, no backup schedule, no encryption at rest, and no migrations beyond refusing a newer schema. There is no Postgres option yet.
11. **Roles are declared, not authenticated.** `X-ASTRA-Role` is taken on trust. There is no login, no encryption at rest, and no access control beyond preventing mistakes. Do not expose the API beyond a trusted local network.
12. **Single process.** No horizontal scaling, no background jobs; alerts are evaluated when data arrives.
13. **Latency was measured on one laptop** with the in-memory store and 21 simulated days; SQLite is slower and it will differ elsewhere.
14. **Time.** All times are UTC; the crew dataset is dated in 2027, so server "now" and data time differ in the crew demo.

## Scope

15. **ASTRA never diagnoses and never decides escalation.** Next steps are general prompts to follow the onboard medical protocol. `ESCALATION_REQUESTED` is recorded only when a person asks for it.
16. **No official challenge dataset was used**; the challenge resources page could not be checked when the project started.
