import { LIMITS } from './data/crew';
import type { Alert, AlertState, Dashboard, Domain, Hazard, Status } from './types';

export const domainLabel: Record<Domain, string> = {
  cardiovascular: 'Cardiovascular',
  'sleep-behaviour': 'Sleep and behaviour',
  musculoskeletal: 'Musculoskeletal',
  'immune-symptoms': 'Immune and symptoms',
  radiation: 'Radiation exposure',
  environment: 'Cabin environment',
};

export const domainIcon: Record<Domain, string> = {
  cardiovascular: 'heart',
  'sleep-behaviour': 'moon',
  musculoskeletal: 'bone',
  'immune-symptoms': 'shield',
  radiation: 'radiation',
  environment: 'wind',
};

export const hazardLabel: Record<Hazard, string> = {
  radiation: 'Space radiation',
  isolation: 'Isolation and confinement',
  distance: 'Distance from Earth',
  gravity: 'Altered gravity',
  hostile: 'Hostile, closed environment',
};

const rank: Record<Status, number> = { normal: 0, watch: 1, review: 2 };
export const worst = (a: Status, b: Status) => (rank[b] > rank[a] ? b : a);

export function alertState(a: Alert, states: Record<string, AlertState>): AlertState {
  return states[a.id] ?? a.state;
}

export const isActive = (s: AlertState) => s !== 'resolved';

export function domainStatuses(d: Dashboard, states: Record<string, AlertState>) {
  const out = {} as Record<Domain, Status>;
  (Object.keys(domainLabel) as Domain[]).forEach((k) => (out[k] = 'normal'));
  Object.values(d.metrics).forEach((m) => (out[m.domain] = worst(out[m.domain], m.status)));
  d.alerts.filter((a) => isActive(alertState(a, states))).forEach((a) => (out[a.domain] = worst(out[a.domain], a.status)));
  return out;
}

/** One-line reason shown next to each domain: the active alert if there is one, otherwise the latest readings. */
export function domainReason(d: Dashboard, domain: Domain): string {
  const alert = d.alerts.find((a) => a.domain === domain);
  if (alert) return alert.title;
  const m = d.metrics;
  const n = (v: number | null | undefined, dp = 0) => (v === null || v === undefined ? '—' : v.toFixed(dp));
  switch (domain) {
    case 'cardiovascular':
      return `Resting HR ${n(m.restingHr?.latest)} bpm, HRV ${n(m.hrv?.latest)} ms`;
    case 'sleep-behaviour':
      return `Slept ${n(m.sleep?.latest, 1)} h; mood ${n(m.mood?.latest)}/5, stress ${n(m.stress?.latest)}/10`;
    case 'musculoskeletal':
      return `Exercise ${n(m.exercise?.latest)} min; est. hip bone loss ${n(m.boneLoss?.latest, 1)}% (modelled)`;
    case 'immune-symptoms':
      return `Temperature ${n(m.bodyTemp?.latest, 1)} °C; ${m.headache?.latest ? `headache on ${m.headache.latest} of the last 7 days` : 'no headache reported'}`;
    case 'radiation':
      return d.cumulativeDoseMsv === undefined
        ? 'Within configured mission limit'
        : `${d.cumulativeDoseMsv.toFixed(0)} mSv so far, ${((d.cumulativeDoseMsv / LIMITS.radiationCareerMsv) * 100).toFixed(0)}% of NASA’s career limit`;
    case 'environment':
      return (m.co2?.latest ?? 0) > LIMITS.co2LimitMmHg
        ? `CO₂ ${n(m.co2?.latest, 1)} mmHg, above NASA’s ${LIMITS.co2LimitMmHg} mmHg limit today`
        : `CO₂ ${n(m.co2?.latest, 1)} mmHg, within NASA’s ${LIMITS.co2LimitMmHg} mmHg limit`;
  }
}

/** The worst status among alerts that are still active. */
export function overallStatus(d: Dashboard, states: Record<string, AlertState>): Status {
  return d.alerts.filter((a) => isActive(alertState(a, states))).reduce<Status>((s, a) => worst(s, a.status), 'normal');
}

/** How many readings are normal today. A plain count, not a health score. */
export function readingCount(d: Dashboard) {
  const all = Object.values(d.metrics);
  return { normal: all.filter((m) => m.status === 'normal').length, total: all.length };
}
