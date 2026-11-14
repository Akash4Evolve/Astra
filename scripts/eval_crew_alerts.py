"""Score the backend alert engine on the simulated crew dataset (Astra/src/data).

Replays the CSV day by day through the same code the API uses and compares each alert
with the planted events. The `event` column is read here only, never by the engine.

    python scripts/eval_crew_alerts.py
"""
import csv, sys, uuid
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'ml'/'src'), str(ROOT/'backend')]
from astra_ml.models import Measurement, SourceType
from app.store import InMemoryStore
from app.services import evaluate_series

COLS = {'heart_rate': ('heart_rate_rest_bpm','bpm','07:10'), 'sleep_hours': ('sleep_hours','h','06:10')}
rows = list(csv.DictReader(open(ROOT/'Astra/src/data/astronaut_health_simulated.csv', encoding='utf-8')))
events = {(r['astronaut_id'], int(r['mission_day'])): r['event'] for r in rows if r['event']}
store = InMemoryStore(); day_of = {}
for d in range(1, 181):
    batch = []
    for r in rows:
        if int(r['mission_day']) != d: continue
        for p,(c,u,hm) in COLS.items():
            m = Measurement(record_id=uuid.uuid5(uuid.NAMESPACE_URL, f"{r['astronaut_id']}{d}{p}"), astronaut_id=r['astronaut_id'],
                timestamp_utc=datetime.fromisoformat(f"{r['date']}T{hm}:00+00:00"), parameter=p, value=float(r[c]), unit=u,
                source_type=SourceType.SIMULATED, is_simulated=True)
            day_of[str(m.record_id)] = d; batch.append(m)
    store.add_measurements(batch)
    for a,p in sorted({(m.astronaut_id, m.parameter) for m in batch}):
        evaluate_series(store, a, p)
tp = fp = 0
for al in sorted(store.list_alerts(), key=lambda a: (a.astronaut_id, a.parameter, day_of[a.explanation.evidence_record_ids[0]])):
    ds = [day_of[i] for i in al.explanation.evidence_record_ids]
    ev = {events.get((al.astronaut_id, x)) for x in range(ds[0]-2, ds[-1]+1)} - {None}
    ok = bool(ev - {'EVA', 'eva'}) and not all('EVA' in e.upper() for e in ev)
    tp += ok; fp += not ok
    print(f"{al.astronaut_id:7}{al.parameter:12}{al.level.value:7} days {ds[0]:3}-{ds[-1]:3}  {'HIT '+','.join(sorted(ev)) if ok else 'FALSE ' + ','.join(sorted(ev))}")
print(f"\n{tp+fp} alerts: {tp} on planted events, {fp} false")
print('planted events:', sorted({(e, a) for (a,_), e in events.items()}))
