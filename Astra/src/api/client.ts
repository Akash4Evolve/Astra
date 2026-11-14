// API client. If VITE_API_URL is set, the app talks to the ASTRA FastAPI backend
// (backend/app). Otherwise it runs in demo mode on the bundled simulated dataset alone.
//
// Backend endpoints used:
//   GET  /api/v1/astronauts/{id}/trends   heart rate and sleep, with the personal baseline
//   GET  /api/v1/alerts?astronaut_id=     alerts from the backend's baseline engine
//   POST /api/v1/check-ins
//   POST /api/v1/alerts/{id}/acknowledge
//   POST /api/v1/actions
//
// The rest of the dashboard comes from the bundled dataset in both modes; see ./backend.ts.

import { buildCrewDashboard } from '../data/crew';
import { CREW_ROWS } from '../data/crewData';
import type { ActionRecord, CheckIn, Dashboard } from '../types';
import { actionBody, checkinBody, isBackendAlert, mergeBackend, OWNED_PARAMETERS, type BAlert, type BTrends } from './backend';

const BASE = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/+$/, '') || undefined;
/** No backend configured: sending is simulated and nothing leaves the device. */
export const DEMO_MODE = !BASE;
/** The readings are dated by the simulated mission in both modes, so the demo clock and crew/day picker stay on. */
export const SIMULATED_DATASET = true;
export const API_URL = BASE;

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    // Declared role (the backend's simple roles; not authentication).
    headers: { 'Content-Type': 'application/json', 'X-ASTRA-Role': 'astronaut' },
    ...init,
  });
  if (!res.ok) {
    let detail = '';
    try {
      const body = (await res.json()) as { error?: { message?: string } };
      detail = body.error?.message ? `: ${body.error.message}` : '';
    } catch {
      /* not JSON */
    }
    throw new Error(`${init?.method ?? 'GET'} ${path} failed with ${res.status}${detail}`);
  }
  return res.json() as Promise<T>;
}

const wait = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));
const q = encodeURIComponent;

export const api = {
  /** `view` picks the crew member and mission day. */
  /** `keep`: backend alert IDs this device has responded to, kept visible after their readings end. */
  async getDashboard(view?: { crewId: string; day: number }, keep?: ReadonlySet<string>): Promise<Dashboard> {
    const base = buildCrewDashboard(CREW_ROWS, view?.crewId ?? 'FE-02', view?.day ?? 143);
    if (DEMO_MODE) {
      await wait(150);
      return base;
    }
    const id = base.profile.id;
    const end = `${base.generatedAt.slice(0, 10)}T23:59:59Z`;
    const params = OWNED_PARAMETERS.map((p) => `parameter=${q(p)}`).join('&');
    const [trends, alerts] = await Promise.all([
      http<BTrends>(`/api/v1/astronauts/${q(id)}/trends?${params}&end=${q(end)}&limit=2000`),
      http<BAlert[]>(`/api/v1/alerts?astronaut_id=${q(id)}`),
    ]);
    return mergeBackend(base, trends, alerts, keep);
  },

  async postCheckin(c: CheckIn): Promise<void> {
    if (DEMO_MODE) return wait(300);
    const body = checkinBody(c, c.crewId ?? 'FE-02');
    if (!body) return; // older check-in without sleep duration: kept on this device only
    await http('/api/v1/check-ins', { method: 'POST', body: JSON.stringify(body) });
  },

  async postAction(a: ActionRecord): Promise<void> {
    if (DEMO_MODE) return wait(300);
    // The backend only knows its own alerts; responses to the app's other alerts stay on this device.
    if (!isBackendAlert(a.alertId)) return;
    if (a.kind === 'acknowledge') {
      await http(`/api/v1/alerts/${q(a.alertId!)}/acknowledge`, { method: 'POST' });
      return;
    }
    const body = actionBody(a);
    if (!body) return;
    await http('/api/v1/actions', { method: 'POST', body: JSON.stringify(body) });
  },
};
