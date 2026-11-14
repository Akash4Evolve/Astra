import { useState } from 'react';
import { TrendChart, type Range } from '../components/charts';
import { Icon, Panel, ProvenanceTag, StatusChip, utcDate, utcTime } from '../components/ui';
import { isCmo } from '../data/crew';
import { alertState, domainIcon, domainLabel, hazardLabel } from '../derive';
import { go } from '../router';
import { nowMs, useStore } from '../store';
import type { Alert, AlertState } from '../types';
import { RangeTabs, stateLabel } from './Overview';
import { Sources } from '../components/Explain';

export function AlertsList() {
  const { dashboard: d, alertStates } = useStore();
  if (!d) return null;
  return (
    <div className="page">
      <header className="page-head">
        <h1>Alerts</h1>
        <p className="lede">
          Alerts compare your readings with your own usual range. They are prompts to check and act, not diagnoses.
        </p>
      </header>
      <ul className="alert-cards">
        {d.alerts.map((a) => {
          const st = alertState(a, alertStates);
          return (
            <li key={a.id}>
              <button className={`alert-card ac-${a.status}`} onClick={() => go(`/alerts/${a.id}`)}>
                <Icon name={domainIcon[a.domain]} size={26} className={`ai ai-${a.status}`} />
                <span className="alert-main">
                  <span className="alert-title">{a.title}</span>
                  <span className="alert-sum">{a.summary}</span>
                  <span className="alert-meta">
                    <StatusChip status={a.status} small />
                    <span className="state">{stateLabel[st]}</span>
                    <span>{domainLabel[a.domain]}</span>
                    {a.hazard && <span className="hazard-tag">{hazardLabel[a.hazard]}</span>}
                    <span>
                      {utcDate(a.createdAt)} {utcTime(a.createdAt)} UTC
                    </span>
                    <ProvenanceTag p={a.provenance} />
                  </span>
                </span>
                <Icon name="arrow" size={20} className="chev" />
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

const quickActions = ['Rested 30 minutes', 'Drank 500 ml water', 'Repeated reading', 'Adjusted sleep station light'];
const rechecks = [
  { label: 'In 4 hours', h: 4 },
  { label: 'This evening', h: 9 },
  { label: 'Tomorrow morning', h: 24 },
];

function ActionPanel({ a }: { a: Alert }) {
  const { record, alertStates, actions, linkUp, dashboard } = useStore();
  // The crew medical officer can't review their own case, so it goes to mission control.
  const selfIsCmo = !!dashboard && isCmo(dashboard.profile.role);
  const st = alertState(a, alertStates);
  const [mode, setMode] = useState<null | 'action' | 'recheck' | 'escalate'>(null);
  const [note, setNote] = useState('');
  const [to, setTo] = useState<'crew-medical-officer' | 'mission-control'>(selfIsCmo ? 'mission-control' : 'crew-medical-officer');
  const [flash, setFlash] = useState<string | null>(null);
  const history = actions.filter((x) => x.alertId === a.id);

  const done = (msg: string) => {
    setFlash(msg);
    setMode(null);
    setNote('');
  };

  const toggle = (m: 'action' | 'recheck' | 'escalate') => {
    setMode(mode === m ? null : m);
    setNote('');
  };

  const commit = (kind: 'acknowledge' | 'action' | 'recheck' | 'escalate', next: AlertState, extra: Partial<Parameters<typeof record>[0]> = {}) =>
    record({ kind, alertId: a.id, note, ...extra }, next);

  return (
    <Panel title="Respond" icon="check" className="p-respond">
      <p className="muted small">
        Current status: <strong className="text">{stateLabel[st]}</strong>
      </p>
      <div className="action-grid">
        <button
          className="btn"
          disabled={st !== 'open'}
          onClick={() => {
            commit('acknowledge', 'acknowledged', { note: '' });
            done('Acknowledged');
          }}
        >
          <Icon name="check" size={18} />
          {st === 'open' ? 'Acknowledge' : 'Acknowledged'}
        </button>
        <button className={`btn${mode === 'action' ? ' btn-on' : ''}`} onClick={() => toggle('action')} aria-expanded={mode === 'action'}>
          <Icon name="clipboard" size={18} />
          Log an action
        </button>
        <button className={`btn${mode === 'recheck' ? ' btn-on' : ''}`} onClick={() => toggle('recheck')} aria-expanded={mode === 'recheck'}>
          <Icon name="clock" size={18} />
          Schedule recheck
        </button>
        <button className={`btn btn-escalate${mode === 'escalate' ? ' btn-on' : ''}`} onClick={() => toggle('escalate')} aria-expanded={mode === 'escalate'}>
          <Icon name="up" size={18} />
          Escalate
        </button>
      </div>

      {mode === 'action' && (
        <div className="sub">
          <div className="pills">
            {quickActions.map((q) => (
              <button key={q} className={`pill${note === q ? ' on' : ''}`} onClick={() => setNote(q)}>
                {q}
              </button>
            ))}
          </div>
          <label className="field">
            <span>What did you do?</span>
            <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Pick one above or type" />
          </label>
          <button
            className="btn btn-primary"
            disabled={!note.trim()}
            onClick={() => {
              commit('action', 'action-logged');
              done('Action logged');
            }}
          >
            Log action
          </button>
        </div>
      )}

      {mode === 'recheck' && (
        <div className="sub">
          <div className="pills">
            {rechecks.map((r) => (
              <button
                key={r.label}
                className="pill"
                onClick={() => {
                  const at = new Date(nowMs() + r.h * 3600_000).toISOString();
                  record({ kind: 'recheck', alertId: a.id, note: `Recheck ${r.label.toLowerCase()}`, recheckAt: at }, 'recheck-scheduled');
                  done(`Recheck scheduled for ${utcTime(at)} UTC`);
                }}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {mode === 'escalate' && (
        <div className="sub">
          <fieldset className="radio-row">
            <legend>Send to</legend>
            <label>
              <input type="radio" name="to" checked={to === 'crew-medical-officer'} disabled={selfIsCmo} onChange={() => setTo('crew-medical-officer')} />
              Crew medical officer{selfIsCmo && ' (you)'}
            </label>
            <label>
              <input type="radio" name="to" checked={to === 'mission-control'} onChange={() => setTo('mission-control')} />
              Mission control
            </label>
          </fieldset>
          <label className="field">
            <span>Note (optional)</span>
            <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Anything they should know" />
          </label>
          {to === 'mission-control' && !linkUp && (
            <p className="warn-line">
              <Icon name="sat" size={16} /> Ground link is down. This will be queued and sent when the link is back.
            </p>
          )}
          <button
            className="btn btn-escalate-solid"
            onClick={() => {
              commit('escalate', 'escalated', { escalateTo: to });
              done(to === 'mission-control' && !linkUp ? 'Escalation queued for mission control' : 'Escalated');
            }}
          >
            Escalate to {to === 'crew-medical-officer' ? 'crew medical officer' : 'mission control'}
          </button>
        </div>
      )}

      {flash && (
        <p className="flash" role="status">
          <Icon name="check" size={16} /> {flash}
        </p>
      )}

      {history.length > 0 && (
        <ol className="history">
          {history.map((h) => (
            <li key={h.id}>
              <span className="h-time">{utcTime(h.at)}</span>
              <span>
                {h.note || { acknowledge: 'Acknowledged', action: 'Action logged', recheck: 'Recheck scheduled', escalate: 'Escalated', checkin: 'Check-in', measurement: 'Measurement' }[h.kind]}
                {h.escalateTo && ` (to ${h.escalateTo === 'mission-control' ? 'mission control' : 'crew medical officer'})`}
              </span>
              <span className={`sync ${h.synced ? 'ok' : ''}`}>{h.synced ? 'Synced' : 'Queued'}</span>
            </li>
          ))}
        </ol>
      )}
    </Panel>
  );
}

export function AlertDetail({ id }: { id: string }) {
  const { dashboard: d } = useStore();
  const [range, setRange] = useState<Range>('7d');
  if (!d) return null;
  const a = d.alerts.find((x) => x.id === id);
  if (!a)
    return (
      <div className="page">
        <p className="empty">That alert no longer exists. It may have been cleared after a sync.</p>
        <button className="btn" onClick={() => go('/alerts')}>
          Back to alerts
        </button>
      </div>
    );
  const main = d.metrics[a.evidence[0].metricId];
  return (
    <div className="page">
      <button className="back" onClick={() => go('/alerts')}>
        <Icon name="back" size={16} /> Alerts
      </button>
      <header className={`detail-head dh-${a.status}`}>
        <div className="dh-row">
          <StatusChip status={a.status} />
          <span className="muted">{domainLabel[a.domain]}</span>
          {a.hazard && <span className="hazard-tag">{hazardLabel[a.hazard]}</span>}
          <ProvenanceTag p={a.provenance} />
        </div>
        <h1>{a.title}</h1>
        <p className="lede">{a.summary}</p>
      </header>

      <div className="detail-grid">
        <div className="detail-main">
          <Panel title={`${main.label} against your usual range`} icon="chart" action={<RangeTabs value={range} onChange={setRange} hourly={!!main.hourly} />}>
            <TrendChart metric={main} range={range} height={220} />
          </Panel>

          <Panel title="Why this alert appeared" icon="info">
            <dl className="why">
              <div>
                <dt>What changed</dt>
                <dd>
                  <table className="evidence">
                    <thead>
                      <tr>
                        <th scope="col">Reading</th>
                        <th scope="col">Now</th>
                        <th scope="col">Your usual</th>
                        <th scope="col">Change</th>
                      </tr>
                    </thead>
                    <tbody>
                      {a.evidence.map((e) => (
                        <tr key={e.metricId}>
                          <th scope="row">{d.metrics[e.metricId].label}</th>
                          <td className="num">{e.observed}</td>
                          <td className="num">{e.baseline}</td>
                          <td className="num hot">{e.change}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </dd>
              </div>
              <div>
                <dt>Rule</dt>
                <dd>{a.trigger}</dd>
              </div>
              <div>
                <dt>Time window</dt>
                <dd>{a.window}</dd>
              </div>
              <div>
                <dt>Data quality</dt>
                <dd>
                  {a.dataQuality} <span className={`conf conf-${a.confidence}`}>Confidence: {a.confidence}</span>
                </dd>
              </div>
              <div>
                <dt>Happening at the same time</dt>
                <dd>
                  <ul className="plain">
                    {a.context.map((c) => (
                      <li key={c}>{c}</li>
                    ))}
                  </ul>
                  <span className="muted small">These are associations, not causes.</span>
                </dd>
              </div>
            </dl>
          </Panel>
        </div>

        <div className="detail-side">
          <Panel title="Suggested next steps" icon="list">
            <ol className="steps">
              {a.nextSteps.map((s) => {
                const general = s.endsWith(' (general guidance)');
                return (
                  <li key={s}>
                    {general ? s.slice(0, -' (general guidance)'.length) : s}
                    {general && <span className="step-tag">General guidance</span>}
                  </li>
                );
              })}
            </ol>
            <p className="escalate-when">
              <Icon name="up" size={16} />
              {a.escalateWhen}
            </p>
            {a.guidanceSources?.length ? <Sources sources={a.guidanceSources} /> : null}
            <p className="note">
              Steps tagged “General guidance” are Astra’s own suggestions; the others follow the sources above. Onboard,
              approved medical procedures and the flight surgeon always take priority.
            </p>
          </Panel>
          <ActionPanel a={a} />
        </div>
      </div>
    </div>
  );
}
