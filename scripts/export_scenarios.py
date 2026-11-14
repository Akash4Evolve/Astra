import json
from pathlib import Path

from astra_ml.scenarios import available_scenarios, generate_checkins, generate_series

out = Path("data/synthetic")
out.mkdir(parents=True, exist_ok=True)

for parameter in ("heart_rate", "skin_temperature"):
    for scenario in available_scenarios(parameter):
        data = [m.model_dump(mode="json") for m in generate_series(parameter, scenario)]
        (out / f"{parameter}_{scenario}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"wrote {parameter}/{scenario}: {len(data)} records")

for scenario in available_scenarios("sleep_hours"):
    data = [c.model_dump(mode="json") for c in generate_checkins(scenario)]
    (out / f"checkins_{scenario}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"wrote checkins/{scenario}: {len(data)} records")
