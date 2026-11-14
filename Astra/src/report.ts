// Plain-text handover report for the ground: small enough to send over a slow link,
// and readable without the app.

import { statusText, utcDate, utcTime } from './components/ui';
import { alertState, isActive, overallStatus, readingCount } from './derive';
import type { ActionRecord, AlertState, Dashboard, Metric } from './types';

const stateText: Record<AlertState, string> = {
  open: 'not yet reviewed',
  acknowledged: 'acknowledged',
  'action-logged': 'action logged',
  'recheck-scheduled': 'recheck scheduled',
  escalated: 'escalated',
  resolved: 'resolved',
};

const reading = (m: Metric, label = m.label) => {
  const value = m.latest === null ? 'no reading' : `${m.latest.toFixed(m.decimals)} ${m.unit}`;
  const usual = m.baseline ? `, usual ${m.baseline.low.toFixed(m.decimals)}–${m.baseline.high.toFixed(m.decimals)}` : '';
  return `${label} ${value}${usual}${m.status === 'normal' ? '' : ` [${statusText[m.status]}]`}`;
};

export function buildReport(crew: Dashboard[], states: Record<string, AlertState>, actions: ActionRecord[]): string {
  if (!crew.length) return '';
  const first = crew[0];
  const p = first.profile;
  const out: string[] = [
    'ASTRA CREW HEALTH HANDOVER',
    `${p.missionName}, day ${p.missionDay} of ${p.missionLength}`,
    `Generated ${utcDate(first.generatedAt)} ${utcTime(first.generatedAt)} UTC`,
  ];
  if (p.isDemo) out.push('SIMULATED DATA: not real astronaut readings');
  out.push('');

  for (const d of crew) {
    const active = d.alerts.filter((a) => isActive(alertState(a, states)));
    const count = readingCount(d);
    const m = d.metrics;
    out.push(
      `${d.profile.id}  ${d.profile.displayName} (${d.profile.role})`,
      `  Status: ${statusText[overallStatus(d, states)]}. ${count.normal} of ${count.total} readings normal.`,
      `  ${reading(m.restingHr)}; ${reading(m.bodyTemp)}; ${reading(m.spo2)}; ${reading(m.sleep)}`,
      `  Cabin: ${reading(m.co2, 'CO₂')}; ${reading(m.cabinTemp, 'temperature')}; ${reading(m.cabinNoise, 'noise')}`,
    );
    if (!active.length) out.push('  No active alerts.');
    for (const a of active) {
      out.push(`  - [${statusText[a.status]}] ${a.title} (${a.window}; ${stateText[alertState(a, states)]}; confidence ${a.confidence})`, `    ${a.summary}`);
    }
    out.push('');
  }

  out.push('RECORDED ON BOARD');
  if (!actions.length) out.push('  Nothing recorded yet.');
  for (const a of actions.slice(0, 20)) {
    const what = a.note || (a.kind === 'acknowledge' ? 'Alert acknowledged' : a.kind);
    const to = a.escalateTo ? ` to ${a.escalateTo === 'mission-control' ? 'mission control' : 'crew medical officer'}` : '';
    out.push(`  ${utcDate(a.at)} ${utcTime(a.at)} UTC  ${a.kind}: ${what}${to} (${a.synced ? 'sent' : 'queued'})`);
  }
  out.push('', 'Alerts are prompts to check and act, not diagnoses.');
  return out.join('\n');
}

export function downloadText(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}
