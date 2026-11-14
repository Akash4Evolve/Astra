import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { Model3D } from './components/Model3D';
import { SIMULATED_DATASET } from './api/client';
import { MISSION_LENGTH } from './data/crew';
import { CREW, SCENARIOS } from './data/crewData';
import type { MetricId } from './types';
import { Icon } from './components/ui';
import { alertState, isActive, isCurrent } from './derive';
import { go, useRoute } from './router';
import { nowMs, useStore } from './store';
import { AlertDetail, AlertsList } from './views/Alerts';
import { CheckIn } from './views/CheckIn';
import { Crew } from './views/Crew';
import { DataSync, Log } from './views/Log';
import { Measure } from './views/Measure';
import { Overview } from './views/Overview';
import { Trends } from './views/Trends';

/** The app's name, shown in the sidebar. */
export const APP_NAME = 'Astra';

const nav = [
  { id: 'overview', label: 'Overview', icon: 'home' },
  { id: 'crew', label: 'Crew', icon: 'users' },
  { id: 'trends', label: 'Trends', icon: 'chart' },
  { id: 'alerts', label: 'Alerts', icon: 'bell' },
  { id: 'checkin', label: 'Check-in', icon: 'clipboard' },
  { id: 'log', label: 'Action log', icon: 'list' },
  { id: 'data', label: 'Data and sync', icon: 'database' },
].filter((n) => SIMULATED_DATASET || n.id !== 'crew');

/** How long each mission day stays on screen during playback. */
const PLAY_MS = 900;

/** Ticks every 15 s, and jumps when the demo moves to another mission day. */
function useClock(resetKey?: string) {
  const [t, setT] = useState(nowMs());
  useEffect(() => {
    setT(nowMs());
    const i = setInterval(() => setT(nowMs()), 15_000);
    return () => clearInterval(i);
  }, [resetKey]);
  return new Date(t);
}

function Sidebar({ route, alertCount }: { route: string; alertCount: number }) {
  const { dashboard } = useStore();
  const p = dashboard?.profile;
  return (
    <aside className="side">
      <div className="brand">
        <svg viewBox="0 0 40 40" width="36" height="36" aria-hidden="true" className="brand-mark">
          <circle cx="20" cy="20" r="17" fill="none" stroke="currentColor" strokeOpacity=".35" />
          <ellipse cx="20" cy="20" rx="17" ry="6" fill="none" stroke="currentColor" transform="rotate(-24 20 20)" />
          <path d="M6 22h7l3-7 5 12 3-5h10" fill="none" stroke="var(--accent-2)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <div>
          <div className="brand-name">{APP_NAME}</div>
          <div className="brand-sub">Crew health monitor</div>
        </div>
      </div>
      <nav aria-label="Main">
        <ul className="nav">
          {nav.map((n) => (
            <li key={n.id}>
              <a href={`#/${n.id}`} className={route === n.id ? 'on' : ''} aria-current={route === n.id ? 'page' : undefined}>
                <Icon name={n.icon} size={20} />
                <span>{n.label}</span>
                {n.id === 'alerts' && alertCount > 0 && <span className="badge">{alertCount}</span>}
              </a>
            </li>
          ))}
        </ul>
      </nav>
      {p && (
        <div className="mission">
          <div className="mission-planet" aria-hidden="true" />
          <Model3D model="station" className="mission-station" />
          <div className="mission-body">
            <span className="muted small">{p.missionName}</span>
            <span className="mission-day">
              Day <span className="num">{p.missionDay}</span> <span className="muted">of {p.missionLength}</span>
            </span>
            <div className="meter thin">
              <span style={{ width: `${(p.missionDay / p.missionLength) * 100}%` }} />
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}

/**
 * Demo controls, kept in their own bar so they read as tooling and not as part of the product:
 * crew member, mission day (stepper and slider), playback, and shortcuts to the planted events.
 */
function DemoBar() {
  const { view, setView, dashboard } = useStore();
  const [playing, setPlaying] = useState(false);
  const seen = useRef<Set<string> | null>(null);
  const day = (n: number) => setView({ ...view, day: Math.min(MISSION_LENGTH, Math.max(1, n)) });

  // Playback: step a day at a time, stopping at the end of the mission.
  useEffect(() => {
    if (!playing) return;
    if (view.day >= MISSION_LENGTH) {
      setPlaying(false);
      return;
    }
    const t = setTimeout(() => setView({ ...view, day: view.day + 1 }), PLAY_MS);
    return () => clearTimeout(t);
  }, [playing, view, setView]);

  // Playback pauses by itself the day a new alert appears, so it can be read.
  useEffect(() => {
    if (!dashboard) return;
    const ids = new Set(dashboard.alerts.map((a) => a.id));
    const before = seen.current;
    seen.current = ids;
    if (playing && before && [...ids].some((id) => !before.has(id))) setPlaying(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dashboard]);

  const scenario = SCENARIOS.findIndex((s) => s.crewId === view.crewId && s.day === view.day);
  return (
    <section className="demo-bar" aria-label="Demo controls">
      <span className="demo-flag" title="All readings are synthetic demonstration data">
        Demo data
      </span>
      <label className="demo-field">
        <span className="sr-only">Crew member</span>
        <select value={view.crewId} onChange={(e) => setView({ ...view, crewId: e.target.value })}>
          {CREW.map((c) => (
            <option key={c.id} value={c.id}>
              {c.id} · {c.name}
            </option>
          ))}
        </select>
      </label>
      <div className="day-step">
        <button type="button" aria-label="Previous day" onClick={() => day(view.day - 1)} disabled={view.day <= 1}>
          ‹
        </button>
        <label>
          Day{' '}
          <input type="number" min={1} max={MISSION_LENGTH} value={view.day} onChange={(e) => day(Number(e.target.value) || 1)} aria-label="Mission day" />
        </label>
        <button type="button" aria-label="Next day" onClick={() => day(view.day + 1)} disabled={view.day >= MISSION_LENGTH}>
          ›
        </button>
      </div>
      <input
        className="day-slider"
        type="range"
        min={1}
        max={MISSION_LENGTH}
        value={view.day}
        onChange={(e) => day(Number(e.target.value))}
        aria-label="Mission day slider"
        style={{ '--fill': `${((view.day - 1) / (MISSION_LENGTH - 1)) * 100}%` } as CSSProperties}
      />
      <button
        type="button"
        className={`play${playing ? ' on' : ''}`}
        onClick={() => setPlaying((p) => !p)}
        disabled={!playing && view.day >= MISSION_LENGTH}
        title="Step through the mission a day at a time. Pauses when a new alert appears."
      >
        <Icon name={playing ? 'pause' : 'play'} size={16} />
        {playing ? 'Pause' : 'Play mission'}
      </button>
      <label className="demo-field">
        <span className="sr-only">Jump to a scenario</span>
        <select
          value={scenario}
          onChange={(e) => {
            const s = SCENARIOS[Number(e.target.value)];
            if (!s) return;
            setPlaying(false);
            setView({ crewId: s.crewId, day: s.day });
            go('/overview');
          }}
        >
          <option value={-1}>Jump to a scenario…</option>
          {SCENARIOS.map((s, i) => (
            <option key={s.label} value={i}>
              {s.label}
            </option>
          ))}
        </select>
      </label>
    </section>
  );
}

function TopBar({ watchCount, reviewCount, earlier }: { watchCount: number; reviewCount: number; earlier: number }) {
  const { dashboard, linkUp, acquiring, pending, syncing } = useStore();
  const now = useClock(dashboard?.generatedAt);
  const h = now.getUTCHours();
  const greet = h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
  const p = dashboard?.profile;
  return (
    <header className="top">
      <div className="hello">
        <div className="avatar" aria-hidden="true">
          <Icon name="person" size={24} />
        </div>
        <div>
          <h1 className="hello-h">
            {greet}
            {p ? `, ${p.displayName}` : ''}
          </h1>
          <p className="hello-sub">
            {p && <span className="role">{p.role}. </span>}
            {watchCount === 0
              ? 'Your readings are in your usual range.'
              : `${watchCount} active ${watchCount === 1 ? 'alert' : 'alerts'}${reviewCount ? `, ${reviewCount} ${reviewCount === 1 ? 'needs' : 'need'} review.` : ' to watch. Nothing needs urgent review.'}`}
            {earlier > 0 && ` ${earlier} earlier ${earlier === 1 ? 'alert is' : 'alerts are'} not yet acknowledged.`}
          </p>
        </div>
      </div>
      <div className="top-right">
        <span className={`link-pill ${linkUp ? 'up' : 'down'}`} role="status">
          <Icon name="sat" size={16} />
          {linkUp
            ? syncing
              ? 'Sending…'
              : 'Ground link up'
            : acquiring
              ? 'Connecting…'
              : `Link down${pending ? `, ${pending} queued` : ''}`}
        </span>
        <span className="clock">
          <span className="num">
            {now.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' })}
          </span>{' '}
          UTC
          <span className="muted small block">
            {now.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })}
          </span>
        </span>
      </div>
    </header>
  );
}

export default function App() {
  const route = useRoute();
  const { dashboard, error, reload, alertStates, view } = useStore();
  const active = dashboard ? dashboard.alerts.filter((a) => isCurrent(a) && isActive(alertState(a, alertStates))) : [];
  const earlier = dashboard ? dashboard.alerts.filter((a) => !isCurrent(a) && alertState(a, alertStates) === 'open').length : 0;
  const open = dashboard ? dashboard.alerts.filter((a) => alertState(a, alertStates) === 'open').length : 0;

  let page;
  if (error && !dashboard)
    page = (
      <div className="page narrow">
        <div className="panel">
          <h2>Couldn’t load readings</h2>
          <p className="muted">{error}. Readings already on this device are still available once loaded. Check the backend address and try again.</p>
          <button className="btn btn-primary" onClick={reload}>
            Try again
          </button>
        </div>
      </div>
    );
  else if (!dashboard) page = <div className="loading" aria-busy="true">Loading readings…</div>;
  else if (route[0] === 'alerts' && route[1] && SIMULATED_DATASET && dashboard.profile.id !== view.crewId)
    // Opened from the crew view: wait for that crew member's readings.
    page = <div className="loading" aria-busy="true">Loading readings…</div>;
  else if (route[0] === 'alerts' && route[1]) page = <AlertDetail id={route[1]} />;
  else if (route[0] === 'crew') page = <Crew />;
  else if (route[0] === 'alerts') page = <AlertsList />;
  else if (route[0] === 'trends') page = <Trends key={route[1] ?? ''} initial={route[1] as MetricId | undefined} />;
  else if (route[0] === 'measure') page = <Measure />;
  else if (route[0] === 'checkin') page = <CheckIn />;
  else if (route[0] === 'log') page = <Log />;
  else if (route[0] === 'data') page = <DataSync />;
  else page = <Overview />;

  return (
    <div className="shell">
      <a href="#main" className="skip" onClick={(e) => (e.preventDefault(), document.getElementById('main')?.focus())}>
        Skip to content
      </a>
      <Sidebar route={route[0]} alertCount={open} />
      <div className="main-col">
        <TopBar watchCount={active.length} reviewCount={active.filter((a) => a.status === 'review').length} earlier={earlier} />
        {SIMULATED_DATASET && <DemoBar />}
        <main id="main" tabIndex={-1}>
          <div key={route[0]} className="page-enter">
            {page}
          </div>
        </main>
      </div>
    </div>
  );
}
