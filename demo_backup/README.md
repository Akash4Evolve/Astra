# Backup demo material (all data SIMULATED)

Made by `python scripts/make_demo_backup.py` on 2026-11-14T20:08:49+00:00. Re-run it after code changes.

| File | Use it when |
|---|---|
| `demo_transcript.txt` | `python scripts/demo.py` won't run: walk through this output instead (steps 1-7 of the judge story). |
| `crew_api_snapshot.json` | The API won't start: these are the real responses for the crew dataset (alerts, dashboard, twin, trends per crew member). |

Zero-dependency fallback: the Astra frontend runs without any backend. In `Astra/`, remove `.env.local`
(or leave `VITE_API_URL` unset) and run `npm run app`, then open http://localhost:4173. It uses the bundled
crew dataset and its own alert rules, and every value is tagged Simulated.

Order of fallbacks on the day: live backend + frontend -> frontend alone (demo mode) -> this transcript and
snapshot -> the recorded video.
