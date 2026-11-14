// Local-first state. Everything the astronaut records is saved on the device
// first and queued; the queue is sent when the link to the ground is up.

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { api, SIMULATED_DATASET } from './api/client';
import type { ActionRecord, AlertState, CheckIn, Dashboard } from './types';

interface Persisted {
  actions: ActionRecord[];
  checkins: CheckIn[];
  alertStates: Record<string, AlertState>;
  linkUp: boolean;
}

const KEY = 'crew-health:v1';
export const DRAFT_KEY = 'crew-health:checkin-draft';
const RETRY_BASE_MS = 2_000;
const RETRY_MAX_MS = 60_000;
/** How long "Acquiring signal" plays before the link comes up. */
export const ACQUIRE_MS = 1400;
const empty: Persisted = { actions: [], checkins: [], alertStates: {}, linkUp: false };

function load(): Persisted {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? { ...empty, ...(JSON.parse(raw) as Persisted) } : empty;
  } catch {
    return empty;
  }
}

/** With the simulated dataset (demo or backend) the clock is set to the morning of the chosen mission day and runs from there. */
let clockBase = Date.now();
let clockSetAt = Date.now();
export const nowMs = () => (SIMULATED_DATASET ? clockBase + (Date.now() - clockSetAt) : Date.now());
let clockFor = '';
/**
 * Starts the demo clock at the time the dashboard was generated for (the day shown). Fetching
 * the same day again (after a send or a reset) leaves the clock running, so time never goes
 * backwards and records keep the order they were made in.
 */
const setClock = (iso: string) => {
  if (iso === clockFor) return;
  clockFor = iso;
  clockBase = new Date(iso).getTime();
  clockSetAt = Date.now();
};

/** Which crew member and mission day the demo shows. */
export interface View {
  crewId: string;
  day: number;
}
const VIEW_KEY = 'crew-health:view';
const defaultView: View = { crewId: 'FE-02', day: 143 };
function loadView(): View {
  try {
    return { ...defaultView, ...(JSON.parse(localStorage.getItem(VIEW_KEY) ?? '{}') as Partial<View>) };
  } catch {
    return defaultView;
  }
}

interface Store extends Persisted {
  dashboard: Dashboard | null;
  error: string | null;
  syncError: string | null;
  syncing: boolean;
  pending: number;
  lastSync: string | null;
  reload: () => void;
  view: View;
  setView: (v: View) => void;
  record: (a: Omit<ActionRecord, 'id' | 'at' | 'synced'>, nextState?: AlertState) => void;
  submitCheckin: (c: Omit<CheckIn, 'id' | 'at' | 'synced'>) => void;
  setLinkUp: (up: boolean) => void;
  /** True while the link is being established (between connectLink and the link coming up). */
  acquiring: boolean;
  /** Start establishing the ground link. Keeps going if the user leaves the page. */
  connectLink: () => void;
  /** Drop the link, or cancel a connection still being established. */
  dropLink: () => void;
  sync: () => Promise<void>;
  resetDemo: () => void;
}

const Ctx = createContext<Store | null>(null);

type Outgoing = { type: 'checkin'; record: CheckIn } | { type: 'action'; record: ActionRecord };

/**
 * The next record to send: the oldest one not yet sent, check-ins and actions together, so
 * the ground receives them in the order they happened (an acknowledgement before the recheck
 * that followed it). Both lists are stored newest first, so on equal timestamps the record
 * further down the list is the older one.
 */
export function oldestUnsent(checkins: CheckIn[], actions: ActionRecord[], sent: Set<string>): Outgoing | undefined {
  let best: { item: Outgoing; at: number; pos: number } | undefined;
  const consider = (item: Outgoing, at: string, pos: number) => {
    const t = Date.parse(at);
    if (!best || t < best.at || (t === best.at && pos > best.pos)) best = { item, at: t, pos };
  };
  checkins.forEach((c, i) => {
    if (!c.synced && !sent.has(c.id)) consider({ type: 'checkin', record: c }, c.at, i);
  });
  // A check-in's log row travels with the check-in, so it isn't sent on its own.
  actions.forEach((a, i) => {
    if (!a.synced && a.kind !== 'checkin' && !sent.has(a.id)) consider({ type: 'action', record: a }, a.at, i);
  });
  return best?.item;
}
// UUIDs, because the backend uses record IDs to ignore duplicates when a send is retried.
const uid = (): string =>
  typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (ch) => {
        const r = (Math.random() * 16) | 0;
        return (ch === 'x' ? r : (r & 0x3) | 0x8).toString(16);
      });

export function StoreProvider({ children }: { children: ReactNode }) {
  const [p, setP] = useState<Persisted>(load);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [acquiring, setAcquiring] = useState(false);
  // Lives in the provider, not in a page, so leaving the Data page doesn't cancel a connection.
  const acquireTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const clearAcquire = () => {
    if (acquireTimer.current) clearTimeout(acquireTimer.current);
    acquireTimer.current = null;
    setAcquiring(false);
  };
  useEffect(() => () => {
    if (acquireTimer.current) clearTimeout(acquireTimer.current);
  }, []);
  const [lastSync, setLastSync] = useState<string | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [retryTick, setRetryTick] = useState(0);
  const [view, setViewState] = useState<View>(loadView);
  const setView = useCallback((v: View) => {
    setViewState(v);
    try {
      localStorage.setItem(VIEW_KEY, JSON.stringify(v));
    } catch {
      /* ignore */
    }
  }, []);
  const latest = useRef(p);
  const sending = useRef(false);
  const attempts = useRef(0);
  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    latest.current = p;
  }, [p]);

  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(p));
    } catch {
      /* storage unavailable: state stays in memory */
    }
  }, [p]);

  const reload = useCallback(() => {
    setError(null);
    api
      .getDashboard(view, new Set(Object.keys(latest.current.alertStates)))
      .then((d) => {
        setClock(d.generatedAt);
        setDashboard(d);
      })
      .catch((e: Error) => setError(e.message));
  }, [view]);
  useEffect(reload, [reload]);
  // sync() is created once, so it reaches the current reload through a ref.
  const reloadRef = useRef(reload);
  useEffect(() => {
    reloadRef.current = reload;
  }, [reload]);

  const stamp = () => new Date(nowMs()).toISOString();

  const record: Store['record'] = (a, nextState) => {
    const rec: ActionRecord = { crewId: dashboard?.profile.id ?? view.crewId, ...a, id: uid(), at: stamp(), synced: false };
    setP((s) => ({
      ...s,
      actions: [rec, ...s.actions],
      // An escalation stays visible: later actions are added to its history but don't replace it.
      alertStates:
        a.alertId && nextState && s.alertStates[a.alertId] !== 'escalated'
          ? { ...s.alertStates, [a.alertId]: nextState }
          : s.alertStates,
    }));
  };

  const submitCheckin: Store['submitCheckin'] = (c) => {
    const rec: CheckIn = { crewId: dashboard?.profile.id ?? view.crewId, ...c, id: uid(), at: stamp(), synced: false };
    setP((s) => ({
      ...s,
      checkins: [rec, ...s.checkins],
      actions: [{ id: uid(), kind: 'checkin', note: 'Daily check-in recorded', at: rec.at, synced: false }, ...s.actions],
    }));
  };

  // A check-in's log row travels with the check-in, so it isn't a record of its own.
  const pending = p.actions.filter((a) => !a.synced && a.kind !== 'checkin').length + p.checkins.filter((c) => !c.synced).length;

  const clearRetry = () => {
    if (retryTimer.current) clearTimeout(retryTimer.current);
    retryTimer.current = null;
  };

  // Sends one record at a time and marks each as soon as it is accepted, reading the
  // latest state each pass so records added mid-sync are sent rather than assumed sent.
  const sync = useCallback(async () => {
    if (!latest.current.linkUp || sending.current) return;
    sending.current = true;
    setSyncing(true);
    const sent = new Set<string>();
    try {
      while (latest.current.linkUp) {
        const { checkins, actions } = latest.current;
        const next = oldestUnsent(checkins, actions, sent);
        const c = next?.type === 'checkin' ? next.record : undefined;
        const a = next?.type === 'action' ? next.record : undefined;
        if (c) {
          await api.postCheckin(c);
          sent.add(c.id);
          setP((s) => ({
            ...s,
            checkins: s.checkins.map((x) => (x.id === c.id ? { ...x, synced: true } : x)),
            actions: s.actions.map((x) => (x.kind === 'checkin' && x.at === c.at ? { ...x, synced: true } : x)),
          }));
        } else if (a) {
          await api.postAction(a);
          sent.add(a.id);
          setP((s) => ({ ...s, actions: s.actions.map((x) => (x.id === a.id ? { ...x, synced: true } : x)) }));
        } else {
          break;
        }
      }
      attempts.current = 0;
      setSyncError(null);
      setLastSync(new Date(nowMs()).toISOString());
    } catch (e) {
      // Wait before retrying, doubling up to a limit, so a failing backend isn't flooded.
      setSyncError((e as Error).message);
      const delay = Math.min(RETRY_BASE_MS * 2 ** attempts.current, RETRY_MAX_MS);
      attempts.current += 1;
      clearRetry();
      retryTimer.current = setTimeout(() => {
        retryTimer.current = null;
        setRetryTick((t) => t + 1);
      }, delay);
    } finally {
      sending.current = false;
      setSyncing(false);
      // What was sent can change alerts on the backend (an acknowledgement, a new sleep
      // alert from a check-in), so show the backend's view again.
      if (sent.size > 0) reloadRef.current();
    }
  }, []);

  // Link changes start fresh: no waiting retry, no stale failure message.
  useEffect(() => {
    clearRetry();
    attempts.current = 0;
    setSyncError(null);
  }, [p.linkUp]);

  // Send the queue when the link comes up or new records arrive, unless a retry is waiting.
  useEffect(() => {
    if (p.linkUp && pending > 0 && !syncing && !retryTimer.current) void sync();
  }, [p.linkUp, pending, syncing, retryTick, sync]);

  const value = useMemo<Store>(
    () => ({
      ...p,
      dashboard,
      error,
      syncError,
      syncing,
      pending,
      lastSync,
      reload,
      view,
      setView,
      record,
      submitCheckin,
      setLinkUp: (up) => {
        clearAcquire();
        setP((s) => ({ ...s, linkUp: up }));
      },
      acquiring,
      connectLink: () => {
        if (latest.current.linkUp || acquireTimer.current) return;
        setAcquiring(true);
        acquireTimer.current = setTimeout(() => {
          acquireTimer.current = null;
          setAcquiring(false);
          setP((s) => ({ ...s, linkUp: true }));
        }, ACQUIRE_MS);
      },
      dropLink: () => {
        clearAcquire();
        setP((s) => ({ ...s, linkUp: false }));
      },
      sync,
      resetDemo: () => {
        clearAcquire();
        try {
          localStorage.removeItem(DRAFT_KEY);
        } catch {
          /* ignore */
        }
        setP(empty);
        // Only this device is cleared. Records already sent stay on the backend, so fetch
        // its alerts again rather than keep showing a copy from before they arrived.
        reload();
      },
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [p, dashboard, view, error, syncError, syncing, acquiring, pending, lastSync, sync, reload],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useStore() {
  const s = useContext(Ctx);
  if (!s) throw new Error('useStore must be used inside StoreProvider');
  return s;
}
