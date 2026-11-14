// Turns the simulated crew dataset (one row per astronaut per mission day) into the
// app's Dashboard shape, as of a chosen mission day, and derives alerts from rules.
//
// The CSV's `event` column is ground truth for checking the rules. It is never parsed
// here, so the app's logic can't see it (see scripts/verify-alerts.ts).

import type { Alert, AlertEvidence, Baseline, Dashboard, Domain, Hazard, Metric, MetricId, Point, Status } from '../types';

export interface CrewRow {
  id: string;
  name: string;
  role: string;
  day: number;
  date: string; // YYYY-MM-DD
  v: Record<string, number>;
}

export interface CrewMember {
  id: string;
  name: string;
  role: string;
}

/**
 * Fixed limits, with where each comes from (see LIMIT_SOURCES). Readings that have no
 * published limit (heart rate, sleep, HRV and so on) are judged against the person's own
 * baseline instead.
 */
export const LIMITS = {
  /** NASA-STD-3001 Vol. 2 Rev D, V2 6004: 1-hour average CO₂ no more than 3 mmHg. */
  co2LimitMmHg: 3.0,
  /** Days in a row above the limit before alerting (daily averages; stops normal day-to-day spikes alerting). */
  co2SustainDays: 3,
  /** NASA OCHMO CO₂ technical brief: fatigue, malaise, poorer sleep and nausea above 4.5 mmHg. */
  co2ReviewMmHg: 4.5,
  /** Fever: 38.0 °C (100.4 °F), the CDC's definition. Below that, temperature is judged against the personal baseline. */
  feverC: 38.0,
  /** SpO₂ of 95–100% is the commonly cited normal range for healthy adults. */
  spo2WatchPct: 95,
  /** Common clinical advice: contact a clinician at 92% or lower. */
  spo2ReviewPct: 92,
  /** Our own rule, not a NASA limit: a day's dose this many times the usual daily dose counts as a spike. */
  doseSpikeFactor: 3,
  /** NASA-STD-3001 Vol. 1 Rev B: career effective dose under 600 mSv. */
  radiationCareerMsv: 600,
  /** NASA-STD-3001 Vol. 1 Rev B: short-term (solar particle event) limit, under 250 mSv. */
  radiationShortTermMsv: 250,
};

/** Public NASA (and other) sources behind the suggested next steps in alerts. */
const GUIDE = {
  radiation: { label: 'NASA OCHMO radiation protection technical brief', url: 'https://www.nasa.gov/wp-content/uploads/2023/03/radiation-protection-technical-brief-ochmo.pdf' },
  co2: { label: 'NASA OCHMO CO₂ technical brief', url: 'https://www.nasa.gov/wp-content/uploads/2023/12/ochmo-tb-004-carbon-dioxide.pdf' },
  sleep: { label: 'NASA OCHMO sleep accommodations technical brief', url: 'https://www.nasa.gov/wp-content/uploads/2023/03/sleep-accomodations-technical-brief-ochmo.pdf' },
  wake: { label: 'npj Microgravity (2023): wake-promoting countermeasures available on the ISS', url: 'https://www.nature.com/articles/s41526-023-00332-w' },
  care: { label: 'NASA OCHMO: in-flight medical care', url: 'https://www.nasa.gov/ochmo/health-and-medical-systems/in-flight-medical-care/' },
  infection: { label: 'NASA OCHMO health stabilization program brief', url: 'https://nasa.gov/wp-content/uploads/2023/08/ochmo-tb-006-health-stabilization-program-rev-d.pdf' },
  cardio: { label: 'NASA HRP: Risks of Human Spaceflight', url: 'https://www.nasa.gov/hrp/risks/' },
};

export const LIMIT_SOURCES = {
  co2: { label: 'NASA-STD-3001 Vol. 2 Rev D, V2 6004 (via NASA OCHMO CO₂ technical brief)', url: 'https://www.nasa.gov/wp-content/uploads/2023/12/ochmo-tb-004-carbon-dioxide.pdf' },
  radiation: { label: 'NASA-STD-3001 Vol. 1 Rev B', url: 'https://www.nasa.gov/wp-content/uploads/2020/10/2022-01-05_nasa-std-3001_vol.1_rev._b_final_draft_with_signature_010522.pdf' },
  radiationBrief: { label: 'NASA OCHMO radiation protection technical brief', url: 'https://www.nasa.gov/wp-content/uploads/2023/03/radiation-protection-technical-brief-ochmo.pdf' },
  fever: { label: 'CDC fever definition, 100.4 °F (38.0 °C)', url: 'https://www.cdc.gov/quarantine/maritime/definitions-signs-symptoms-conditions-ill-travelers.html' },
};

/** CO₂ above NASA's limit for the last `co2SustainDays` days. */
function co2Sustained(t: Timeline, i: number) {
  const n = LIMITS.co2SustainDays;
  return i >= n - 1 && t.col('co2').slice(i - n + 1, i + 1).every((v) => v > LIMITS.co2LimitMmHg);
}

export const MISSION_LENGTH = 180;
const MISSION_NAME = 'Simulated 180-day mission';

// ---------- parsing ----------

function splitCsvLine(line: string): string[] {
  const out: string[] = [];
  let cur = '';
  let quoted = false;
  for (const ch of line) {
    if (ch === '"') quoted = !quoted;
    else if (ch === ',' && !quoted) {
      out.push(cur);
      cur = '';
    } else cur += ch;
  }
  out.push(cur);
  return out;
}

export function parseCrewCsv(text: string): CrewRow[] {
  const lines = text.trim().split(/\r?\n/);
  const head = splitCsvLine(lines[0]);
  const col = (name: string) => head.indexOf(name);
  const skip = new Set(['astronaut_id', 'name', 'role', 'mission_day', 'date', 'event']);
  return lines.slice(1).map((line) => {
    const c = splitCsvLine(line);
    const v: Record<string, number> = {};
    head.forEach((h, i) => {
      if (skip.has(h)) return;
      const raw = c[i];
      v[h] = raw === 'True' ? 1 : raw === 'False' ? 0 : Number(raw);
    });
    return { id: c[col('astronaut_id')], name: c[col('name')], role: c[col('role')], day: Number(c[col('mission_day')]), date: c[col('date')], v };
  });
}

export function crewList(rows: CrewRow[]): CrewMember[] {
  const seen = new Map<string, CrewMember>();
  rows.forEach((r) => seen.has(r.id) || seen.set(r.id, { id: r.id, name: r.name, role: r.role }));
  return [...seen.values()];
}

export const isCmo = (role: string) => /\bCMO\b|medical officer/i.test(role);

// ---------- metrics ----------

interface Def {
  id: MetricId;
  col: string;
  label: string;
  unit: string;
  domain: Domain;
  hazard: Hazard;
  decimals: number;
  baseline: boolean;
  /** Hour of the day the reading is taken (UTC), for freshness. */
  at: number;
}

const DEFS: Def[] = [
  { id: 'restingHr', col: 'heart_rate_rest_bpm', label: 'Resting heart rate', unit: 'bpm', domain: 'cardiovascular', hazard: 'gravity', decimals: 0, baseline: true, at: 7 },
  { id: 'hrv', col: 'hrv_rmssd_ms', label: 'Heart rate variability (RMSSD)', unit: 'ms', domain: 'cardiovascular', hazard: 'isolation', decimals: 0, baseline: true, at: 7 },
  { id: 'bpSys', col: 'systolic_bp_mmhg', label: 'Blood pressure', unit: 'mmHg', domain: 'cardiovascular', hazard: 'gravity', decimals: 0, baseline: true, at: 7 },
  { id: 'bpDia', col: 'diastolic_bp_mmhg', label: 'Diastolic', unit: 'mmHg', domain: 'cardiovascular', hazard: 'gravity', decimals: 0, baseline: true, at: 7 },
  { id: 'spo2', col: 'spo2_pct', label: 'SpO₂', unit: '%', domain: 'cardiovascular', hazard: 'hostile', decimals: 1, baseline: true, at: 7 },
  { id: 'bodyTemp', col: 'body_temp_c', label: 'Body temperature', unit: '°C', domain: 'immune-symptoms', hazard: 'hostile', decimals: 1, baseline: true, at: 7 },
  { id: 'respRate', col: 'resp_rate_bpm', label: 'Respiratory rate', unit: '/min', domain: 'cardiovascular', hazard: 'hostile', decimals: 0, baseline: true, at: 7 },
  { id: 'sleep', col: 'sleep_hours', label: 'Sleep', unit: 'h', domain: 'sleep-behaviour', hazard: 'isolation', decimals: 1, baseline: true, at: 6 },
  { id: 'sleepQuality', col: 'sleep_quality_1_10', label: 'Sleep quality (self-rated)', unit: '/10', domain: 'sleep-behaviour', hazard: 'isolation', decimals: 1, baseline: true, at: 8 },
  { id: 'mood', col: 'mood_1_5', label: 'Mood (self-rated)', unit: '/5', domain: 'sleep-behaviour', hazard: 'isolation', decimals: 0, baseline: true, at: 8 },
  { id: 'stress', col: 'stress_0_10', label: 'Stress (self-rated)', unit: '/10', domain: 'sleep-behaviour', hazard: 'isolation', decimals: 0, baseline: true, at: 8 },
  { id: 'reactionTime', col: 'reaction_time_ms', label: 'Reaction time (PVT)', unit: 'ms', domain: 'sleep-behaviour', hazard: 'isolation', decimals: 0, baseline: true, at: 8 },
  { id: 'headache', col: 'headache', label: 'Headache (self-reported)', unit: 'days', domain: 'immune-symptoms', hazard: 'hostile', decimals: 0, baseline: false, at: 8 },
  { id: 'bodyMass', col: 'body_mass_kg', label: 'Body mass', unit: 'kg', domain: 'musculoskeletal', hazard: 'gravity', decimals: 1, baseline: false, at: 7 },
  { id: 'boneLoss', col: 'hip_bmd_loss_pct', label: 'Hip bone density loss (modelled)', unit: '%', domain: 'musculoskeletal', hazard: 'gravity', decimals: 1, baseline: false, at: 7 },
  { id: 'grip', col: 'grip_strength_pct_preflight', label: 'Grip strength', unit: '% of preflight', domain: 'musculoskeletal', hazard: 'gravity', decimals: 0, baseline: false, at: 7 },
  { id: 'exercise', col: 'exercise_min', label: 'Exercise completed', unit: 'min', domain: 'musculoskeletal', hazard: 'gravity', decimals: 0, baseline: true, at: 8 },
  { id: 'radiation', col: 'radiation_dose_msv', label: 'Radiation dose', unit: 'mSv/day', domain: 'radiation', hazard: 'radiation', decimals: 2, baseline: false, at: 9 },
  { id: 'co2', col: 'cabin_co2_mmhg', label: 'Cabin CO₂', unit: 'mmHg', domain: 'environment', hazard: 'hostile', decimals: 1, baseline: true, at: 9 },
  { id: 'cabinTemp', col: 'cabin_temp_c', label: 'Cabin temperature', unit: '°C', domain: 'environment', hazard: 'hostile', decimals: 1, baseline: true, at: 9 },
  { id: 'cabinNoise', col: 'cabin_noise_db', label: 'Cabin noise', unit: 'dB', domain: 'environment', hazard: 'hostile', decimals: 0, baseline: true, at: 9 },
];

const COL = Object.fromEntries(DEFS.map((d) => [d.id, d.col])) as Record<MetricId, string>;
const SHOWN_DAYS = 30;
const iso = (date: string, hour: number, min = 0) => `${date}T${String(hour).padStart(2, '0')}:${String(min).padStart(2, '0')}:00Z`;
const avg = (xs: number[]) => xs.reduce((a, b) => a + b, 0) / xs.length;
/** Mean of the last n values up to and including index i. */
const recent = (values: number[], i: number, n = 3) => avg(values.slice(Math.max(0, i - n + 1), i + 1));
const median = (xs: number[]) => {
  const s = [...xs].sort((a, b) => a - b);
  return s.length % 2 ? s[(s.length - 1) / 2] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2;
};

const BASE_WINDOW = 21;
const BASE_EXCLUDE = 7;

function bandFrom(vals: number[]): Baseline | null {
  if (vals.length < 10) return null;
  const mean = avg(vals);
  const sd = Math.sqrt(avg(vals.map((v) => (v - mean) ** 2)));
  return { mean, low: mean - 2 * sd, high: mean + 2 * sd, windowDays: BASE_WINDOW, method: `${BASE_WINDOW}-day mean ± 2 SD` };
}

/**
 * Personal baseline for every day: mean ± 2 SD of the last 21 usual days, leaving out the
 * most recent 7. Days inside an out-of-range spell (3-day mean outside the band) don't count
 * as usual, so a long bad patch can't become the new normal. Needs 10 days of history.
 */
function baselines(values: number[]): (Baseline | null)[] {
  const out: (Baseline | null)[] = [];
  const usual: boolean[] = [];
  for (let i = 0; i < values.length; i++) {
    const pool: number[] = [];
    for (let j = i - BASE_EXCLUDE; j >= 0 && pool.length < BASE_WINDOW; j--) if (usual[j]) pool.unshift(values[j]);
    const b = bandFrom(pool);
    out.push(b);
    const m = recent(values, i);
    usual.push(!b || (m >= b.low && m <= b.high));
  }
  return out;
}


/** One astronaut's timeline, with every column as an array indexed by mission day - 1. */
class Timeline {
  rows: CrewRow[];
  private cols = new Map<MetricId, number[]>();
  private bases = new Map<MetricId, (Baseline | null)[]>();
  constructor(rows: CrewRow[]) {
    this.rows = [...rows].sort((a, b) => a.day - b.day);
  }
  col(id: MetricId) {
    let c = this.cols.get(id);
    if (!c) this.cols.set(id, (c = this.rows.map((r) => r.v[COL[id]])));
    return c;
  }
  base(id: MetricId, i: number) {
    let b = this.bases.get(id);
    if (!b) this.bases.set(id, (b = baselines(this.col(id))));
    return b[i];
  }
  r3(id: MetricId, i: number, n = 3) {
    return recent(this.col(id), i, n);
  }
}

function bandStatus(t: Timeline, id: MetricId, i: number): Status {
  const b = t.base(id, i);
  if (!b) return 'normal';
  const m = t.r3(id, i);
  return m < b.low || m > b.high ? 'watch' : 'normal';
}

function metricStatus(t: Timeline, def: Def, i: number): Status {
  const v = t.col(def.id)[i];
  switch (def.id) {
    case 'co2':
      return v > LIMITS.co2ReviewMmHg ? 'review' : v > LIMITS.co2LimitMmHg ? 'watch' : 'normal';
    case 'bodyTemp':
      return v >= LIMITS.feverC ? 'review' : bandStatus(t, def.id, i);
    case 'spo2':
      return v <= LIMITS.spo2ReviewPct ? 'review' : v < LIMITS.spo2WatchPct ? 'watch' : 'normal';
    case 'radiation':
      return doseSpike(t, i) ? 'review' : 'normal';
    case 'headache':
      return t.col('headache').slice(Math.max(0, i - 1), i + 1).some((x) => x > 0) ? 'watch' : 'normal';
    case 'boneLoss':
    case 'bodyMass':
    case 'grip':
      return 'normal'; // slow modelled drifts, shown as trends rather than flagged
    default:
      return def.baseline ? bandStatus(t, def.id, i) : 'normal';
  }
}

function buildMetric(t: Timeline, def: Def, i: number): Metric {
  const values = t.col(def.id);
  const from = Math.max(0, i - SHOWN_DAYS + 1);
  const daily: Point[] = t.rows.slice(from, i + 1).map((r, k) => ({ t: iso(r.date, 12), v: values[from + k] }));
  const isHeadache = def.id === 'headache';
  return {
    id: def.id,
    label: def.label,
    unit: def.unit,
    domain: def.domain,
    hazard: def.hazard,
    decimals: def.decimals,
    latest: isHeadache ? values.slice(Math.max(0, i - 6), i + 1).reduce((a, b) => a + b, 0) : values[i],
    latestAt: iso(t.rows[i].date, def.at, 10),
    status: metricStatus(t, def, i),
    provenance: 'simulated',
    quality: 'good',
    qualityNote: isHeadache ? 'Days with a headache in the last 7' : def.id === 'boneLoss' ? 'Modelled estimate, not measured onboard' : undefined,
    baseline: def.baseline ? t.base(def.id, i) : null,
    daily,
  };
}

// ---------- alert rules ----------

function doseSpike(t: Timeline, i: number) {
  const dose = t.col('radiation');
  const prior = dose.slice(Math.max(0, i - 14), i);
  if (prior.length < 5) return false;
  return dose[i] > LIMITS.doseSpikeFactor * median(prior);
}

interface Hit {
  status: Exclude<Status, 'normal'>;
}
type Rule = {
  id: string;
  domain: Domain;
  hazard: Hazard;
  test: (t: Timeline, i: number) => Hit | null;
  /** Rules whose alert, when active, already covers this one. */
  coveredBy?: string[];
};

const RULES: Rule[] = [
  {
    id: 'radiation',
    domain: 'radiation',
    hazard: 'radiation',
    test: (t, i) => (doseSpike(t, i) ? { status: 'review' } : null),
  },
  {
    id: 'co2',
    domain: 'environment',
    hazard: 'hostile',
    test: (t, i) => {
      if (t.col('co2')[i] > LIMITS.co2ReviewMmHg) return { status: 'review' };
      return co2Sustained(t, i) ? { status: 'watch' } : null;
    },
  },
  {
    id: 'fever',
    domain: 'immune-symptoms',
    hazard: 'hostile',
    test: (t, i) => {
      // Fever at 38.0 °C; below that, a raise above your own usual range.
      const v = t.col('bodyTemp')[i];
      if (v >= LIMITS.feverC) return { status: 'review' };
      // A single warm day is common, so a raise needs a second sign: raised resting heart
      // rate the same day, or a raised temperature two days running.
      const b = t.base('bodyTemp', i);
      if (!b || v <= b.high) return null;
      const hrB = t.base('restingHr', i);
      const hrUp = !!hrB && t.col('restingHr')[i] > hrB.high;
      const yesterday = i > 0 && t.col('bodyTemp')[i - 1] > (t.base('bodyTemp', i - 1)?.high ?? Infinity);
      return hrUp || yesterday ? { status: 'watch' } : null;
    },
  },
  {
    id: 'sleep',
    domain: 'sleep-behaviour',
    hazard: 'isolation',
    test: (t, i) => {
      const sb = t.base('sleep', i);
      const stb = t.base('stress', i);
      const mb = t.base('mood', i);
      if (!sb || !stb || !mb) return null;
      // Last night alone counts when it is below range, so a sudden change shows the next morning.
      const short = t.r3('sleep', i) < sb.low || t.col('sleep')[i] < sb.low;
      const strained = t.r3('stress', i) > stb.high || t.col('stress')[i] > stb.high || t.r3('mood', i) < mb.low;
      if (!short || !strained) return null;
      // Five or more nights below range is more serious.
      const longRun = [1, 2, 3, 4].every((k) => i - k >= 0 && t.r3('sleep', i - k) < (t.base('sleep', i - k)?.low ?? 0));
      return { status: longRun ? 'review' : 'watch' };
    },
    coveredBy: ['co2', 'fever'],
  },
  {
    id: 'rhr',
    domain: 'cardiovascular',
    hazard: 'gravity',
    test: (t, i) => {
      const b = t.base('restingHr', i);
      return b && t.r3('restingHr', i) > b.high ? { status: 'watch' } : null;
    },
    coveredBy: ['fever', 'sleep'],
  },
  {
    id: 'hrv',
    domain: 'cardiovascular',
    hazard: 'isolation',
    test: (t, i) => {
      const b = t.base('hrv', i);
      return b && t.r3('hrv', i) < b.low ? { status: 'watch' } : null;
    },
    coveredBy: ['fever', 'sleep', 'co2'],
  },
  {
    id: 'spo2',
    domain: 'cardiovascular',
    hazard: 'hostile',
    test: (t, i) => {
      const v = t.col('spo2')[i];
      if (v <= LIMITS.spo2ReviewPct) return { status: 'review' };
      return v < LIMITS.spo2WatchPct ? { status: 'watch' } : null;
    },
    coveredBy: ['fever', 'co2'],
  },
  {
    id: 'headache',
    domain: 'immune-symptoms',
    hazard: 'hostile',
    test: (t, i) => (t.col('headache').slice(Math.max(0, i - 1), i + 1).some((x) => x > 0) ? { status: 'watch' } : null),
    coveredBy: ['co2', 'fever'],
  },
];

const fmtRange = (b: Baseline | null, d = 0) => (b ? `${b.low.toFixed(d)}–${b.high.toFixed(d)}` : 'not enough history');
const signed = (x: number, d = 0) => `${x >= 0 ? '+' : '−'}${Math.abs(x).toFixed(d)}`;

function evidence(t: Timeline, id: MetricId, i: number, n: number, unit: string, d = 0): AlertEvidence {
  const b = t.base(id, i);
  const m = n === 1 ? t.col(id)[i] : t.r3(id, i, n);
  return {
    metricId: id,
    observed: `${m.toFixed(d)} ${unit}${n === 1 ? ' (today)' : ` (${n}-day mean)`}`,
    baseline: b ? `${fmtRange(b, d)} ${unit}` : 'not enough history',
    change: b ? `${signed(m - b.mean, d)} ${unit}` : '—',
  };
}

interface Ctx {
  t: Timeline;
  i: number;
  start: number;
  crew: CrewMember;
  /** Today's dose for every crew member, for crew-wide context. */
  crewDose: number[];
}

function headachesIn(t: Timeline, i: number, n: number) {
  return t.col('headache').slice(Math.max(0, i - n + 1), i + 1).filter((x) => x > 0).length;
}

function cmoEscalation(crew: CrewMember, normal: string) {
  return isCmo(crew.role)
    ? `You are the crew medical officer, so you can’t review your own case. ${normal.replace(/the crew medical officer/gi, 'mission control (flight surgeon)')} Tell the commander as well.`
    : normal;
}

function describe(rule: Rule, hit: Hit, c: Ctx): Omit<Alert, 'id' | 'domain' | 'hazard' | 'status' | 'createdAt' | 'state' | 'window' | 'provenance'> {
  const { t, i } = c;
  const row = t.rows[i];
  const v = row.v;
  switch (rule.id) {
    case 'radiation': {
      const dose = t.col('radiation');
      const usual = median(dose.slice(Math.max(0, i - 14), i));
      const raised = c.crewDose.filter((d) => d > LIMITS.doseSpikeFactor * usual).length;
      return {
        title: 'Radiation dose spike: possible solar particle event',
        summary: `Today’s dose is ${dose[i].toFixed(2)} mSv, about ${(dose[i] / usual).toFixed(0)}× your usual ${usual.toFixed(2)} mSv/day.`,
        trigger: `Daily dose above ${LIMITS.doseSpikeFactor}× your median daily dose over the previous 14 days. This is Astra’s own spike rule; NASA’s limits are on total dose.`,
        evidence: [{ metricId: 'radiation', observed: `${dose[i].toFixed(2)} mSv (today)`, baseline: `${usual.toFixed(2)} mSv/day (14-day median)`, change: `${(dose[i] / usual).toFixed(1)}×` }],
        context: [
          `${raised} of ${c.crewDose.length} crew show a raised dose today`,
          `Mission total so far ${v.cumulative_dose_msv.toFixed(1)} mSv, against NASA’s ${LIMITS.radiationCareerMsv} mSv career limit (NASA-STD-3001 Vol. 1 Rev B)`,
          `NASA’s short-term limit for a solar particle event is ${LIMITS.radiationShortTermMsv} mSv`,
          `Self-rated stress ${v.stress_0_10}/10 today`,
        ],
        dataQuality: 'Dosimeter readings are daily totals, so a spike shows the day after it starts.',
        confidence: raised > 1 ? 'high' : 'medium',
        nextSteps: [
          'Go to your designated storm shelter (for example, your crew quarters) when mission control calls it, and stay until they say activities can resume',
          'Keep your personal dosimeter on, so your dose is recorded',
          'Log time spent in the shelter' + ' (general guidance)',
        ],
        guidanceSources: [GUIDE.radiation],
        escalateWhen: 'Mission control normally leads during a solar particle event. Escalate right away if you feel nausea, vomiting or unusual fatigue.',
      };
    }
    case 'co2': {
      const h = headachesIn(t, i, 3);
      return {
        title: hit.status === 'review' ? 'Cabin CO₂ well above NASA limit' : 'Cabin CO₂ above NASA limit for 3 days',
        summary: `Cabin CO₂ is ${v.cabin_co2_mmhg.toFixed(1)} mmHg, above NASA’s ${LIMITS.co2LimitMmHg} mmHg limit${h ? `, and you reported a headache on ${h} of the last 3 days` : ''}.`,
        trigger: `Cabin CO₂ above NASA’s ${LIMITS.co2LimitMmHg} mmHg limit (NASA-STD-3001 Vol. 2 Rev D, V2 6004) for ${LIMITS.co2SustainDays} days in a row, or above ${LIMITS.co2ReviewMmHg} mmHg on any day, where NASA’s CO₂ brief lists fatigue, poorer sleep and nausea.`,
        evidence: [
          { metricId: 'co2', observed: `${v.cabin_co2_mmhg.toFixed(1)} mmHg (today)`, baseline: `${fmtRange(t.base('co2', i), 1)} mmHg`, change: `${signed(v.cabin_co2_mmhg - (t.base('co2', i)?.mean ?? v.cabin_co2_mmhg), 1)} mmHg` },
          evidence(t, 'reactionTime', i, 3, 'ms'),
          evidence(t, 'sleep', i, 3, 'h', 1),
        ],
        context: [`Headache reported on ${h} of the last 3 days`, 'Headaches, poorer sleep and slower reactions are linked to raised CO₂ (association, not proof of cause)'],
        dataQuality: 'Cabin CO₂ from the cabin sensor (simulated). Headache is self-reported.',
        confidence: h ? 'high' : 'medium',
        nextSteps: [
          'Report the reading to mission control so the CO₂ removal equipment can be checked',
          'Tell the crew medical officer about headaches or vision changes, the most common CO₂ complaints in flight',
          'Rest in a well-ventilated module where possible' + ' (general guidance)',
        ],
        guidanceSources: [GUIDE.co2],
        escalateWhen: 'Escalate right away if you have a severe headache, confusion, or breathlessness.',
      };
    }
    case 'fever': {
      return {
        title: hit.status === 'review' ? 'Fever with raised heart rate' : 'Body temperature above your usual range',
        summary: `Your temperature is ${v.body_temp_c.toFixed(1)} °C, with resting heart rate ${v.heart_rate_rest_bpm} bpm and SpO₂ ${v.spo2_pct}%.`,
        trigger: `Fever: ${LIMITS.feverC.toFixed(1)} °C or higher (CDC definition, 100.4 °F). Below that, temperature above your own usual range. Core temperature runs slightly high in microgravity, which is why your own baseline is used.`,
        evidence: [
          { metricId: 'bodyTemp', observed: `${v.body_temp_c.toFixed(1)} °C (today)`, baseline: `${fmtRange(t.base('bodyTemp', i), 1)} °C`, change: `${signed(v.body_temp_c - (t.base('bodyTemp', i)?.mean ?? v.body_temp_c), 1)} °C` },
          evidence(t, 'restingHr', i, 1, 'bpm'),
          evidence(t, 'spo2', i, 1, '%', 1),
          evidence(t, 'hrv', i, 3, 'ms'),
        ],
        context: [`Headache reported on ${headachesIn(t, i, 3)} of the last 3 days`, `Exercise today ${v.exercise_min} min`, `Mood ${v.mood_1_5}/5`],
        dataQuality: 'Temperature, heart rate and SpO₂ from morning vitals (simulated).',
        confidence: 'high',
        nextSteps: [
          isCmo(c.crew.role)
            ? 'Report it to the flight surgeon at mission control, since you are the crew medical officer'
            : 'Report it to the crew medical officer now: in-flight care depends on early reporting',
          'Keep close contact with crewmates to a minimum while you have symptoms, as infections spread easily in a closed cabin',
          'Rest, drink fluids, and repeat temperature and SpO₂ in 4 hours' + ' (general guidance)',
        ],
        guidanceSources: [GUIDE.care, GUIDE.infection],
        escalateWhen: cmoEscalation(c.crew, 'Escalate to the crew medical officer if temperature reaches 38.5 °C, SpO₂ falls below 94%, or you feel short of breath.'),
      };
    }
    case 'sleep': {
      const nights = i - c.start + 3;
      return {
        title: hit.status === 'review' ? 'Ongoing short sleep with high stress' : 'Short sleep with higher stress',
        summary: `You averaged ${t.r3('sleep', i).toFixed(1)} h of sleep over 3 nights, below your usual ${fmtRange(t.base('sleep', i), 1)} h, with stress ${t.r3('stress', i).toFixed(0)}/10 and mood ${t.r3('mood', i).toFixed(0)}/5.`,
        trigger: 'Sleep below your personal range for 3 nights, together with stress above or mood below your range. Needs review after 5 nights.',
        evidence: [evidence(t, 'sleep', i, 3, 'h', 1), evidence(t, 'stress', i, 3, '/10'), evidence(t, 'mood', i, 3, '/5', 1), evidence(t, 'hrv', i, 3, 'ms'), evidence(t, 'reactionTime', i, 3, 'ms')],
        context: [`Below-range sleep for about ${nights} nights`, 'Lower HRV and slower reaction time often follow short sleep'],
        dataQuality: 'Sleep from actigraphy (simulated). Stress and mood are self-rated.',
        confidence: 'medium',
        nextSteps: [
          'Fix what disturbs your sleep station: NASA lists light, noise and temperature as causes of in-flight sleep loss',
          'Use the cabin’s dynamic lighting settings to help your body clock before your sleep window',
          'Raise workload and schedule with the flight surgeon, which NASA also lists as causes',
          'On duty after short sleep, ask the flight surgeon about caffeine or blue-enriched light, both available on the ISS',
        ],
        guidanceSources: [GUIDE.sleep, GUIDE.wake],
        escalateWhen: cmoEscalation(c.crew, 'Escalate to the crew medical officer if short sleep continues for 2 more nights or stress stays at 8/10 or higher.'),
      };
    }
    case 'rhr':
      return {
        title: 'Resting heart rate above your usual range',
        summary: `Your resting heart rate has averaged ${t.r3('restingHr', i).toFixed(0)} bpm over 3 days, above your usual ${fmtRange(t.base('restingHr', i))} bpm.`,
        trigger: '3-day mean resting heart rate above your personal range',
        evidence: [evidence(t, 'restingHr', i, 3, 'bpm'), evidence(t, 'hrv', i, 3, 'ms'), evidence(t, 'bodyTemp', i, 3, '°C', 1)],
        context: [`Sleep ${t.r3('sleep', i).toFixed(1)} h (3-night mean)`, `Exercise ${t.r3('exercise', i).toFixed(0)} min/day (3-day mean)`],
        dataQuality: 'Morning resting reading (simulated).',
        confidence: 'medium',
        nextSteps: [
          'Repeat a seated 5-minute resting reading after your next rest period' + ' (general guidance)',
          'Keep up your scheduled exercise, NASA’s main countermeasure for heart and fitness changes in space',
          'Log fluid intake and complete today’s check-in' + ' (general guidance)',
        ],
        guidanceSources: [GUIDE.cardio],
        escalateWhen: cmoEscalation(c.crew, 'Escalate to the crew medical officer if it stays above range for 2 more days, or right away with chest discomfort, dizziness or breathlessness.'),
      };
    case 'hrv':
      return {
        title: 'Heart rate variability below your usual range',
        summary: `HRV has averaged ${t.r3('hrv', i).toFixed(0)} ms over 3 days, below your usual ${fmtRange(t.base('hrv', i))} ms. Low HRV often follows stress, poor sleep or illness.`,
        trigger: '3-day mean HRV (RMSSD) below your personal range',
        evidence: [evidence(t, 'hrv', i, 3, 'ms'), evidence(t, 'sleep', i, 3, 'h', 1), evidence(t, 'stress', i, 3, '/10')],
        context: ['HRV is sensitive to stress, poor sleep and illness, so look at those alongside it'],
        dataQuality: 'Overnight HRV (simulated).',
        confidence: 'low',
        nextSteps: ['Prioritise sleep tonight' + ' (general guidance)', 'Note any symptoms in your check-in' + ' (general guidance)', 'Recheck tomorrow' + ' (general guidance)'],
        escalateWhen: cmoEscalation(c.crew, 'Escalate to the crew medical officer if it stays low for 3 more days or you feel unwell.'),
      };
    case 'spo2':
      return {
        title: 'Blood oxygen below limit',
        summary: `SpO₂ is ${v.spo2_pct}%, below ${LIMITS.spo2WatchPct}%.`,
        trigger: `SpO₂ below ${LIMITS.spo2WatchPct}%, the bottom of the commonly cited normal range (needs review at ${LIMITS.spo2ReviewPct}% or lower, where clinicians commonly advise contact)`,
        evidence: [evidence(t, 'spo2', i, 1, '%', 1), evidence(t, 'respRate', i, 1, '/min')],
        context: [`Cabin CO₂ ${v.cabin_co2_mmhg.toFixed(1)} mmHg`],
        dataQuality: 'Finger pulse oximeter (simulated). Cold hands and movement can lower readings.',
        confidence: 'medium',
        nextSteps: ['Repeat the reading at rest with warm hands' + ' (general guidance)', 'Note any breathlessness in your check-in' + ' (general guidance)'],
        escalateWhen: cmoEscalation(c.crew, 'Escalate to the crew medical officer right away if it stays below 94% or you feel short of breath.'),
      };
    default: {
      const h = headachesIn(t, i, 3);
      return {
        title: 'Headache reported',
        summary: `You reported a headache on ${h} of the last 3 days.`,
        trigger: 'Headache reported in the last 2 days',
        evidence: [{ metricId: 'headache', observed: `${h} of 3 days`, baseline: '0 days usually', change: `+${h}` }, evidence(t, 'sleep', i, 3, 'h', 1)],
        context: [`Cabin CO₂ ${v.cabin_co2_mmhg.toFixed(1)} mmHg`, `Sleep ${t.r3('sleep', i).toFixed(1)} h (3-night mean)`],
        dataQuality: 'Self-reported in the daily check-in.',
        confidence: 'low',
        nextSteps: ['Drink fluids and rest' + ' (general guidance)', 'Record the headache’s timing and severity in your check-in' + ' (general guidance)'],
        escalateWhen: cmoEscalation(c.crew, 'Escalate to the crew medical officer if it is severe, sudden, or comes with vision changes or confusion.'),
      };
    }
  }
}

/** Alerts active on day index i. The `event` column is never consulted. */
export function alertsAt(t: Timeline, i: number, crew: CrewMember, crewDose: number[]): Alert[] {
  const firing = new Map<string, Hit>();
  for (const r of RULES) {
    const hit = r.test(t, i);
    if (hit) firing.set(r.id, hit);
  }
  const out: Alert[] = [];
  for (const r of RULES) {
    const hit = firing.get(r.id);
    if (!hit || r.coveredBy?.some((c) => firing.has(c))) continue;
    let start = i;
    while (start > 0 && i - start < 30 && r.test(t, start - 1)) start--;
    const first = t.rows[start];
    const today = t.rows[i];
    out.push({
      id: `${crew.id}-${r.id}-d${first.day}`,
      domain: r.domain,
      hazard: r.hazard,
      status: hit.status,
      createdAt: iso(first.date, 9, 0),
      state: 'open',
      window: start === i ? `Day ${today.day}` : `Days ${first.day}–${today.day}`,
      provenance: 'simulated',
      ...describe(r, hit, { t, i, start, crew, crewDose }),
    });
  }
  const rank = { review: 0, watch: 1 };
  return out.sort((a, b) => rank[a.status] - rank[b.status]);
}

// ---------- dashboard ----------

export function buildCrewDashboard(rows: CrewRow[], crewId: string, day: number): Dashboard {
  const crew = crewList(rows).find((c) => c.id === crewId) ?? crewList(rows)[0];
  const t = new Timeline(rows.filter((r) => r.id === crew.id));
  const i = Math.min(Math.max(day, 1), t.rows.length) - 1;
  const row = t.rows[i];
  const metrics = Object.fromEntries(DEFS.map((d) => [d.id, buildMetric(t, d, i)])) as Record<MetricId, Metric>;
  const crewDose = rows.filter((r) => r.day === row.day).map((r) => r.v.radiation_dose_msv);
  const at = (h: number, m = 0) => iso(row.date, h, m);
  return {
    generatedAt: at(9, 42),
    profile: { id: crew.id, displayName: crew.name, role: crew.role, missionName: MISSION_NAME, missionDay: row.day, missionLength: MISSION_LENGTH, isDemo: true },
    metrics,
    alerts: alertsAt(t, i, crew, crewDose),
    cumulativeDoseMsv: row.v.cumulative_dose_msv,
    schedule: [
      { at: at(7, 0), label: 'Morning vitals', detail: 'Resting HR, blood pressure, SpO₂, temperature', done: true },
      { at: at(8, 0), label: 'Daily check-in', detail: 'Sleep quality, mood, stress, symptoms', done: false },
      { at: at(8, 30), label: 'Reaction time test', detail: '3-minute PVT', done: false },
      { at: at(13, 0), label: 'Exercise', detail: 'Treadmill and resistance (ARED)', done: false },
    ],
  };
}

/** Exposed for the verification script. */
export { Timeline };

// ---------- mission history ----------

/** One mission day's alert status for one crew member, for the mission timeline. */
export interface DayStatus {
  day: number;
  date: string;
  status: Status;
  alerts: { title: string; status: Exclude<Status, 'normal'> }[];
}

const historyCache = new WeakMap<CrewRow[], Map<string, DayStatus[]>>();

/**
 * The alert status of every mission day for one crew member, from the same rules as the
 * dashboard (the `event` column is never consulted). Worked out once per crew member.
 */
export function missionHistory(rows: CrewRow[], crewId: string): DayStatus[] {
  let perCrew = historyCache.get(rows);
  if (!perCrew) historyCache.set(rows, (perCrew = new Map()));
  const cached = perCrew.get(crewId);
  if (cached) return cached;
  const crew = crewList(rows).find((c) => c.id === crewId);
  if (!crew) return [];
  const t = new Timeline(rows.filter((r) => r.id === crew.id));
  const doseByDay = new Map<number, number[]>();
  for (const r of rows) {
    const list = doseByDay.get(r.day);
    if (list) list.push(r.v.radiation_dose_msv);
    else doseByDay.set(r.day, [r.v.radiation_dose_msv]);
  }
  const out = t.rows.map((row, i) => {
    const alerts = alertsAt(t, i, crew, doseByDay.get(row.day) ?? []);
    const status: Status = alerts.some((a) => a.status === 'review') ? 'review' : alerts.length ? 'watch' : 'normal';
    return { day: row.day, date: row.date, status, alerts: alerts.map((a) => ({ title: a.title, status: a.status })) };
  });
  perCrew.set(crewId, out);
  return out;
}
