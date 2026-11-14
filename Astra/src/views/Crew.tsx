import { useMemo, useState } from 'react';
import { SIMULATED_DATASET } from '../api/client';
import { MissionTimeline } from '../components/MissionTimeline';
import { CountRing, Icon, Panel, ProvenanceTag, StatusChip, fmt, statusText } from '../components/ui';
import { CREW, crewDashboards } from '../data/crewData';
import { alertState, isActive, overallStatus, readingCount } from '../derive';
import { buildReport, downloadText } from '../report';
import { go } from '../router';
import { useStore } from '../store';
import type { Dashboard, Metric, MetricId } from '../types';

const KEY_VITALS: { id: MetricId; label: string }[] = [
  { id: 'restingHr', label: 'Resting HR' },
  { id: 'bodyTemp', label: 'Temperature' },
  { id: 'spo2', label: 'SpO₂' },
  { id: 'sleep', label: 'Sleep' },
  { id: 'stress', label: 'Stress' },
  { id: 'co2', label: 'Cabin CO₂' },
];

const initials = (name: string) =>
  name
    .replace(/^(Dr|Cdr|Col|Maj|Capt|Lt)\.?\s+/i, '')
    .split(/\s+/)
    .map((w) => w[0])
    .join('')
    .slice(0, 2)
    .toUpperCase();

function MiniVital({ m, label }: { m: Metric; label: string }) {
  return (
    <div className={`mini mini-${m.status}`}>
      <span className="mini-label">{label}</span>
      <span className="mini-val">
        <span className="num">{fmt(m.latest, m.decimals)}</span> <span className="muted">{m.unit}</span>
      </span>
      {m.status !== 'normal' && (
        <span className="mini-flag" title={statusText[m.status]}>
          <Icon name={m.status === 'review' ? 'warn' : 'info'} size={14} />
          <span className="sr-only">{statusText[m.status]}</span>
        </span>
      )}
    </div>
  );
}

function CrewCard({ d, current }: { d: Dashboard; current: boolean }) {
  const { alertStates, setView, view } = useStore();
  const status = overallStatus(d, alertStates);
  const count = readingCount(d);
  const active = d.alerts.filter((a) => isActive(alertState(a, alertStates)));
  const open = (path: string) => {
    setView({ ...view, crewId: d.profile.id });
    go(path);
  };
  return (
    <article className={`crew-card cc-${status}${current ? ' cc-current' : ''}`}>
      <header className="cc-head">
        <span className="cc-avatar" aria-hidden="true">
          {initials(d.profile.displayName)}
        </span>
        <div className="cc-who">
          <h2>{d.profile.displayName}</h2>
          <p className="muted small">
            <span className="num">{d.profile.id}</span> · {d.profile.role}
          </p>
        </div>
      </header>

      <div className="cc-summary">
        <CountRing normal={count.normal} total={count.total} status={status} size={76} />
        <div className="cc-sumtext">
          <StatusChip status={status} small />
          <p className="cc-lead">
            {active.length === 0 ? 'No active alerts' : `${active.length} active ${active.length === 1 ? 'alert' : 'alerts'}`}
          </p>
          <p className="muted small">
            {count.normal} of {count.total} readings normal today
          </p>
        </div>
      </div>

      <div className="mini-grid">
        {KEY_VITALS.map((k) => (
          <MiniVital key={k.id} m={d.metrics[k.id]} label={k.label} />
        ))}
      </div>

      {active.length > 0 && (
        <ul className="cc-alerts">
          {active.map((a) => (
            <li key={a.id}>
              <button type="button" onClick={() => open(`/alerts/${a.id}`)}>
                <span className={`dot dot-${a.status}`} />
                <span className="cc-alert-title">{a.title}</span>
                <span className="muted small">{a.window}</span>
                <Icon name="arrow" size={16} className="chev" />
              </button>
            </li>
          ))}
        </ul>
      )}

      <footer className="cc-foot">
        <button type="button" className="btn" onClick={() => open('/overview')}>
          {current ? 'Open dashboard' : `Switch to ${d.profile.id}`}
        </button>
        <ProvenanceTag p="simulated" />
      </footer>
    </article>
  );
}

export function Crew() {
  const { view, setView, alertStates, actions } = useStore();
  const crew = useMemo(() => (SIMULATED_DATASET ? crewDashboards(view.day) : []), [view.day]);
  const [copied, setCopied] = useState(false);

  if (!SIMULATED_DATASET || !crew.length)
    return (
      <div className="page narrow">
        <header className="page-head">
          <h1>Crew</h1>
          <p className="lede">The crew view needs a crew endpoint on the backend. It is available in demo mode.</p>
        </header>
      </div>
    );

  const report = () => buildReport(crew, alertStates, actions);
  const needing = crew.filter((d) => overallStatus(d, alertStates) !== 'normal').length;
  // The same alert in two or more crew members on the same day.
  const seen = new Map<string, number>();
  crew.forEach((d) =>
    d.alerts.filter((a) => isActive(alertState(a, alertStates))).forEach((a) => seen.set(a.title, (seen.get(a.title) ?? 0) + 1)),
  );
  const shared = [...seen].filter(([, n]) => n > 1);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(report());
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      downloadText(`astra-handover-day-${view.day}.txt`, report());
    }
  };

  return (
    <div className="page">
      <header className="page-head page-head-row">
        <div>
          <h1>Crew</h1>
          <p className="lede">
            {needing === 0
              ? `All ${crew.length} crew members are in their usual ranges on day ${view.day}.`
              : `${needing} of ${crew.length} crew members ${needing === 1 ? 'has' : 'have'} an active alert on day ${view.day}.`}{' '}
            For the commander and crew medical officer.
          </p>
        </div>
        <div className="head-actions">
          <button type="button" className="btn" onClick={copy}>
            <Icon name={copied ? 'check' : 'copy'} size={18} />
            {copied ? 'Copied' : 'Copy handover report'}
          </button>
          <button type="button" className="btn btn-primary" onClick={() => downloadText(`astra-handover-day-${view.day}.txt`, report())}>
            <Icon name="download" size={18} />
            Download report
          </button>
        </div>
      </header>

      {shared.length > 0 && (
        <div className="shared-note" role="status">
          <Icon name="users" size={20} />
          <div>
            <strong>Seen across the crew today</strong>
            <ul className="plain">
              {shared.map(([title, n]) => (
                <li key={title}>
                  {title}: {n} of {crew.length} crew members
                </li>
              ))}
            </ul>
            <span className="muted small">
              The same alert in several people on the same day suggests a shared cause, such as the cabin or a solar event,
              more than an individual one. This is an association, not proof.
            </span>
          </div>
        </div>
      )}

      <div className="crew-grid">
        {crew.map((d) => (
          <CrewCard key={d.profile.id} d={d} current={d.profile.id === view.crewId} />
        ))}
      </div>

      <Panel title="Mission so far, all crew" icon="flag">
        <MissionTimeline crewIds={CREW.map((c) => c.id)} day={view.day} activeCrew={view.crewId} onPick={(crewId, day) => setView({ crewId, day })} />
        <p className="note">
          A day flagged on every row at once points to something shared, such as the cabin or a solar event, not to one
          person. Click any day to open it.
        </p>
      </Panel>

      <p className="note">
        Health data is personal. In flight, this view would be limited to the commander and the crew medical officer, and
        each crew member would see only their own dashboard.
      </p>
    </div>
  );
}
