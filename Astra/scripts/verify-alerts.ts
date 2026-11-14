// Checks the alert rules against the planted events in the simulated dataset.
// The app never reads the `event` column; this script is the only place that does.
// Run: npx tsx scripts/verify-alerts.ts
import { readFileSync } from 'node:fs';
import { alertsAt, crewList, parseCrewCsv, Timeline } from '../src/data/crew';

const text = readFileSync(new URL('../src/data/astronaut_health_simulated.csv', import.meta.url), 'utf8');
const rows = parseCrewCsv(text);
const lines = text.trim().split(/\r?\n/);
const evCol = lines[0].split(',').indexOf('event');
const events = new Map<string, string>();
lines.slice(1).forEach((l) => {
  const c = l.split(',');
  if (c[evCol]) events.set(`${c[0]}:${c[3]}`, c[evCol]);
});

// Which rule should catch each kind of planted event.
const expected: Record<string, string> = {
  'Solar particle event (crew in shelter)': 'radiation',
  'CO2 scrubber degradation': 'co2',
  'Sleep disruption / stress': 'sleep',
  'Mild infection': 'fever',
};

let missed = 0;
const falsePos: string[] = [];
const perEvent = new Map<string, { days: number; caught: number }>();
for (const crew of crewList(rows)) {
  const t = new Timeline(rows.filter((r) => r.id === crew.id));
  for (let i = 0; i < t.rows.length; i++) {
    const day = t.rows[i].day;
    const dose = rows.filter((r) => r.day === day).map((r) => r.v.radiation_dose_msv);
    const alerts = alertsAt(t, i, crew, dose);
    const ruleIds = alerts.map((a) => a.id.split('-')[2]);
    const ev = events.get(`${crew.id}:${day}`);
    const want = ev ? expected[ev] : undefined;
    if (want) {
      const k = `${crew.id} ${ev}`;
      const s = perEvent.get(k) ?? { days: 0, caught: 0 };
      s.days++;
      if (ruleIds.includes(want)) s.caught++;
      else missed++;
      perEvent.set(k, s);
    }
    // An alert on a day with no event, and not in the 3 days after one (3-day means linger), is a false positive.
    const nearEvent = [0, 1, 2, 3].some((k) => events.has(`${crew.id}:${day - k}`));
    if (!nearEvent && alerts.length) falsePos.push(`${crew.id} day ${day}: ${alerts.map((a) => `${a.title} [${a.status}]`).join('; ')}`);
  }
}
console.log('Planted events (days caught / event days):');
for (const [k, s] of perEvent) console.log(`  ${s.caught === s.days ? 'OK  ' : 'MISS'} ${k}: ${s.caught}/${s.days}`);
console.log(`\nEvent days missed: ${missed}`);
console.log(`Days with alerts but no nearby event: ${falsePos.length}`);
falsePos.forEach((f) => console.log('  ' + f));
