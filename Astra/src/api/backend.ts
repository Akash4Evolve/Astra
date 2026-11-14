// Maps the ASTRA FastAPI backend (backend/app, /api/v1) onto the app's own types.
//
// The backend's analytics cover resting heart rate and sleep duration. For those two
// metrics the readings, personal baseline and alerts on screen come from the backend.
// Everything else still comes from the bundled simulated dataset, which the backend is
// seeded from too (scripts/serve_crew.py), so both sides show the same crew and days.

import type { ActionRecord, Alert, Baseline, CheckIn, Dashboard, Domain, Hazard, Metric, MetricId, Point, Provenance, Status } from '../types';

// ---------- backend shapes (backend/app/schemas.py, ml/src/astra_ml/alerts.py) ----------

interface BTrendPoint {
  record_id: string;
  timestamp_utc: string;
  value: number;
  quality_status: 'VALID' | 'SUSPECT' | 'MISSING' | 'STALE';
  is_simulated: boolean;
}
interface BBaseline {
  established: boolean;
  reason: string;
  centre: number | null;
  dispersion: number | null;
  window_start: string | null;
  window_end: string | null;
  sample_count: number | null;
  model_version: string | null;
}
interface BSeries {
  parameter: string;
  unit: string;
  points: BTrendPoint[];
  baseline: BBaseline;
}
export interface BTrends {
  astronaut_id: string;
  series: BSeries[];
}
export interface BAlert {
  alert_id: string;
  astronaut_id: string;
  parameter: string;
  domain: string;
  level: 'INFO' | 'WATCH' | 'REVIEW';
  title: string;
  created_at: string;
  status: 'OPEN' | 'ACKNOWLEDGED';
  explanation: {
    observed: string;
    comparison_window: string;
    data_quality: string;
    evidence_record_ids: string[];
    model: string;
    baseline_centre: number;
    baseline_dispersion: number;
    latest_robust_z: number;
    persistence_count: number;
    z_threshold: number;
  };
  next_step: string;
}

// ---------- which metrics the backend owns ----------

interface Owned {
  parameter: string;
  metric: MetricId;
  domain: Domain;
  hazard: Hazard;
  unit: string;
  decimals: number;
}
export const OWNED: Owned[] = [
  { parameter: 'heart_rate', metric: 'restingHr', domain: 'cardiovascular', hazard: 'gravity', unit: 'bpm', decimals: 0 },
  { parameter: 'sleep_hours', metric: 'sleep', domain: 'sleep-behaviour', hazard: 'isolation', unit: 'h', decimals: 1 },
];
export const OWNED_PARAMETERS = OWNED.map((o) => o.parameter);
const OWNED_METRICS = new Set<MetricId>(OWNED.map((o) => o.metric));
const byParameter = Object.fromEntries(OWNED.map((o) => [o.parameter, o])) as Record<string, Owned>;

const DAY_MS = 86_400_000;
/** An alert counts as current while its newest evidence is at most this old on the day shown. */
const CURRENT_WITHIN_DAYS = 2;

const day = (iso: string) => iso.slice(0, 10);
const fmt = (v: number, d: number) => v.toFixed(d);

function provenanceOf(p: BTrendPoint): Provenance {
  return p.is_simulated ? 'simulated' : 'sensor';
}

/** The backend's band: median ± z_threshold × scaled MAD from the first 14 days. */
function baselineOf(b: BBaseline, z: number): Baseline | null {
  if (!b.established || b.centre == null || b.dispersion == null) return null;
  const days = b.window_start && b.window_end ? Math.round((Date.parse(b.window_end) - Date.parse(b.window_start)) / DAY_MS) + 1 : 14;
  return {
    mean: b.centre,
    low: b.centre - z * b.dispersion,
    high: b.centre + z * b.dispersion,
    windowDays: days,
    method: `Backend: median ± ${z} × MAD, first ${days} days (${b.model_version ?? 'robust baseline'})`,
  };
}

function overlayMetric(base: Metric, s: BSeries, o: Owned, z: number, alerts: Alert[]): Metric {
  const points = s.points;
  const byDay = new Map(points.map((p) => [day(p.timestamp_utc), p]));
  // Keep the frontend's 30-day window and timestamps; take each value from the backend.
  const daily: Point[] = base.daily.map((pt) => {
    const b = byDay.get(day(pt.t));
    return { t: pt.t, v: b && b.quality_status === 'VALID' ? b.value : null };
  });
  const last = points[points.length - 1];
  const baseline = baselineOf(s.baseline, z);
  let status: Status = 'normal';
  if (alerts.some((a) => a.evidence[0]?.metricId === o.metric && a.status === 'review')) status = 'review';
  else if (alerts.some((a) => a.evidence[0]?.metricId === o.metric)) status = 'watch';
  else if (last && baseline && (last.value < baseline.low || last.value > baseline.high)) status = 'watch';
  return {
    ...base,
    daily,
    latest: last ? last.value : null,
    latestAt: last ? last.timestamp_utc : base.latestAt,
    status,
    provenance: last ? provenanceOf(last) : base.provenance,
    quality: !last ? 'missing' : last.quality_status === 'VALID' ? 'good' : 'degraded',
    qualityNote: s.baseline.established ? 'From the ASTRA backend' : `From the ASTRA backend: ${s.baseline.reason}`,
    baseline,
  };
}

function toAlert(a: BAlert, s: BSeries | undefined, o: Owned): Alert {
  const e = a.explanation;
  const pts = new Map((s?.points ?? []).map((p) => [p.record_id, p]));
  const evidence = e.evidence_record_ids.map((id) => pts.get(id)).filter((p): p is BTrendPoint => !!p);
  const first = evidence[0];
  const latest = evidence[evidence.length - 1];
  const low = e.baseline_centre - e.z_threshold * e.baseline_dispersion;
  const high = e.baseline_centre + e.z_threshold * e.baseline_dispersion;
  const diff = latest ? latest.value - e.baseline_centre : 0;
  const status = a.level === 'REVIEW' ? 'review' : 'watch';
  return {
    id: a.alert_id,
    title: a.title,
    status,
    domain: o.domain,
    hazard: o.hazard,
    createdAt: first ? first.timestamp_utc : a.created_at,
    state: a.status === 'ACKNOWLEDGED' ? 'acknowledged' : 'open',
    summary: `${e.observed}.`,
    trigger: `${e.persistence_count} valid readings in a row outside the personal band (|robust z| > ${e.z_threshold}); 2 in a row is Watch, 3 or more is Review.`,
    window:
      first && latest
        ? `${day(first.timestamp_utc)} to ${day(latest.timestamp_utc)}, against ${e.comparison_window}`
        : e.comparison_window,
    evidence: [
      {
        metricId: o.metric,
        observed: latest ? `${fmt(latest.value, o.decimals)} ${o.unit} (latest)` : 'n/a',
        baseline: `${fmt(low, o.decimals)}–${fmt(high, o.decimals)} ${o.unit}`,
        change: `${diff >= 0 ? '+' : ''}${fmt(diff, o.decimals)} ${o.unit}, z = ${e.latest_robust_z.toFixed(1)}`,
      },
    ],
    context: [],
    dataQuality: e.data_quality === 'VALID' ? 'All readings in the run were valid.' : e.data_quality.replace(/_/g, ' ').toLowerCase(),
    confidence: status === 'review' ? 'medium' : 'low',
    nextSteps: [a.next_step],
    escalateWhen: 'If the change keeps going or symptoms appear, follow the onboard medical protocol and involve the crew medical officer.',
    provenance: first ? provenanceOf(first) : 'simulated',
  };
}

/**
 * Puts the backend's heart rate and sleep onto a dashboard built from the bundled dataset.
 * Backend alerts replace the app's own alerts for those two metrics; only alerts that are
 * current on the day shown are kept.
 */
export function mergeBackend(base: Dashboard, trends: BTrends, alerts: BAlert[]): Dashboard {
  const viewEnd = Date.parse(`${day(base.generatedAt)}T23:59:59Z`);
  const series = Object.fromEntries(trends.series.map((s) => [s.parameter, s])) as Record<string, BSeries>;

  const current: Alert[] = [];
  for (const a of alerts) {
    const o = byParameter[a.parameter];
    if (!o || a.level === 'INFO') continue;
    const mapped = toAlert(a, series[a.parameter], o);
    const ids = new Set(a.explanation.evidence_record_ids);
    const times = (series[a.parameter]?.points ?? []).filter((p) => ids.has(p.record_id)).map((p) => Date.parse(p.timestamp_utc));
    if (!times.length) continue;
    const firstAt = Math.min(...times);
    const lastAt = Math.max(...times);
    if (firstAt <= viewEnd && lastAt >= viewEnd - CURRENT_WITHIN_DAYS * DAY_MS) current.push(mapped);
  }

  const metrics = { ...base.metrics };
  for (const o of OWNED) {
    const s = series[o.parameter];
    if (!s) continue;
    const z = alerts.find((a) => a.parameter === o.parameter)?.explanation.z_threshold ?? 3;
    metrics[o.metric] = overlayMetric(base.metrics[o.metric], s, o, z, current);
  }

  const own = base.alerts.filter((a) => !OWNED_METRICS.has(a.evidence[0]?.metricId));
  const rank = { review: 0, watch: 1 };
  return {
    ...base,
    metrics,
    alerts: [...current, ...own].sort((a, b) => rank[a.status] - rank[b.status]),
  };
}

// ---------- outgoing records ----------

/** 0–10 app scale to the backend's 1–5 scale. */
const to5 = (v: number) => Math.min(5, Math.max(1, Math.round(v / 2.5) + 1));

/** Body for POST /api/v1/check-ins, or null when the check-in has no sleep duration (older records). */
export function checkinBody(c: CheckIn, astronautId: string) {
  if (typeof c.sleepHours !== 'number') return null;
  return {
    checkin_id: c.id,
    astronaut_id: astronautId,
    timestamp_utc: c.at,
    sleep_hours: c.sleepHours,
    mood: Math.min(5, Math.max(1, Math.round(c.mood))),
    stress: to5(c.stress),
    fatigue: to5(c.fatigue),
    symptoms: c.symptoms,
    note: c.note.trim() || null,
    source_type: 'MANUAL',
    is_simulated: false,
  };
}

/** Body for POST /api/v1/actions, or null when this kind of record has no backend action. */
export function actionBody(a: ActionRecord) {
  if (!a.alertId) return null;
  const note = a.note.trim() || null;
  switch (a.kind) {
    case 'action':
      return { alert_id: a.alertId, action_type: note ? 'NOTE' : 'PROTOCOL_FOLLOWED', note };
    case 'recheck':
      return a.recheckAt ? { alert_id: a.alertId, action_type: 'FOLLOW_UP_MEASUREMENT', note, follow_up_at: a.recheckAt } : null;
    case 'escalate': {
      const to = a.escalateTo === 'mission-control' ? 'mission control' : 'crew medical officer';
      return { alert_id: a.alertId, action_type: 'ESCALATION_REQUESTED', note: [`Escalated to ${to}`, note].filter(Boolean).join(': ') };
    }
    default:
      return null;
  }
}

/** Backend alert IDs look like ALT-1A2B3C4D; the app's own alerts use other IDs. */
export const isBackendAlert = (id?: string) => !!id && /^ALT-[0-9A-F]+$/.test(id);
