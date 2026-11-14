import { Icon, Panel, ProvenanceTag, utcDate, utcTime } from '../components/ui';
import { DEMO_MODE, SIMULATED_DATASET } from '../api/client';
import { SCENARIOS } from '../data/crewData';
import { GroundLink } from '../components/GroundLink';
import { go } from '../router';
import { useStore } from '../store';

const kindLabel = { acknowledge: 'Acknowledged', action: 'Action', recheck: 'Recheck', escalate: 'Escalated', checkin: 'Check-in', measurement: 'Measurement' } as const;

export function Log() {
  const { actions, dashboard, pending, linkUp, syncing, syncError } = useStore();
  const title = (id?: string) => dashboard?.alerts.find((a) => a.id === id)?.title;
  return (
    <div className="page">
      <header className="page-head">
        <h1>Action log</h1>
        <p className="lede">Everything you record is saved here first, then sent to the ground when the link is up.</p>
      </header>
      <p className={`queue ${pending ? 'queue-wait' : ''}`} role="status">
        <Icon name="sat" size={18} />
        {syncing ? 'Sending…' : pending ? `${pending} record${pending > 1 ? 's' : ''} waiting to send${linkUp ? '' : ' (ground link down)'}` : 'Everything is sent'}
      </p>
      {syncError && pending > 0 && (
        <p className="warn-line" role="alert">
          <Icon name="sat" size={16} /> Couldn’t send: {syncError}. Your records are safe on this device and will retry automatically.
        </p>
      )}
      <Panel title="Recorded" icon="list">
        {actions.length === 0 ? (
          <p className="empty">Nothing recorded yet. Open an alert to acknowledge it or log what you did.</p>
        ) : (
          <ol className="log">
            {actions.map((a) => (
              <li key={a.id}>
                <span className="log-time">
                  {utcDate(a.at)}
                  <br />
                  {utcTime(a.at)} UTC
                </span>
                <span className="log-body">
                  <span className={`kind kind-${a.kind}`}>{kindLabel[a.kind]}</span>
                  <span>
                    {a.note || (a.kind === 'acknowledge' ? 'Alert acknowledged' : '')}
                    {a.escalateTo && ` to ${a.escalateTo === 'mission-control' ? 'mission control' : 'crew medical officer'}`}
                    {a.recheckAt && `, due ${utcTime(a.recheckAt)} UTC`}
                  </span>
                  {a.alertId && <span className="muted small">{title(a.alertId)}</span>}
                </span>
                <span className="log-side">
                  <ProvenanceTag p="self-report" />
                  <span className={`sync ${a.synced ? 'ok' : ''}`}>{a.synced ? 'Sent' : 'Queued'}</span>
                </span>
              </li>
            ))}
          </ol>
        )}
      </Panel>
      {DEMO_MODE && <p className="note">Demo mode: sending is simulated; no data leaves this device.</p>}
    </div>
  );
}

export function DataSync() {
  const { dashboard, resetDemo, setView } = useStore();
  if (!dashboard) return null;
  return (
    <div className="page narrow">
      <header className="page-head">
        <h1>Data and sync</h1>
        <p className="lede">Where each reading comes from, and how the app behaves when the ground link is down.</p>
      </header>
      <Panel title="Ground link" icon="sat">
        <GroundLink />
      </Panel>
      <Panel title="Data sources" icon="database">
        <dl className="sources">
          <div>
            <dt>
              <ProvenanceTag p="sensor" />
            </dt>
            <dd>From a validated onboard device or mission sensor. None are connected in this prototype.</dd>
          </div>
          <div>
            <dt>
              <ProvenanceTag p="self-report" />
            </dt>
            <dd>What you enter in check-ins and the action log.</dd>
          </div>
          <div>
            <dt>
              <ProvenanceTag p="simulated" />
            </dt>
            <dd>
              Synthetic data: a simulated 180-day mission for 3 fictional crew, generated from typical values. Not real
              astronaut readings, and not NASA-sourced.
            </dd>
          </div>
        </dl>
        <p className="note">
          Some indicators, such as bone density or immune biomarkers, need dedicated instruments or lab tests and are not
          estimated from wearables here.
        </p>
        <p className="note">
          3D body:{' '}
          <a href="https://sketchfab.com/3d-models/anatomy-study-20-basemesh-human-male-body-c3f13a4baa2f4ea5a0a88d29e7fa1779" target="_blank" rel="noreferrer">
            Anatomy study 2.0 Basemesh Human Male Body
          </a>{' '}
          by zeroran, licensed under{' '}
          <a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noreferrer">
            CC BY 4.0
          </a>
          . Simplified and recoloured for this app.
        </p>
      </Panel>
      {SIMULATED_DATASET && (
        <Panel title="Demo scenarios" icon="list">
          <p className="muted">
            Jump to a planted event in the simulated dataset (3 crew, 180 mission days). The app’s alert rules find these
            on their own; these shortcuts only set the crew member and day.
          </p>
          <div className="scenario-list">
            {SCENARIOS.map((s) => (
              <button
                key={s.label}
                className="btn"
                onClick={() => {
                  setView({ crewId: s.crewId, day: s.day });
                  go('/overview');
                }}
              >
                <span>{s.label}</span>
                <span className="muted small">
                  {s.crewId}, day {s.day}
                </span>
              </button>
            ))}
          </div>
        </Panel>
      )}
      {SIMULATED_DATASET && (
        <Panel title="Demo" icon="info">
          <p className="muted">
            Clears check-ins, actions and alert responses on this device.
            {!DEMO_MODE && ' Anything already sent to the backend stays there, and alerts show its status.'}
          </p>
          <button
            className="btn"
            onClick={() => {
              resetDemo();
              window.location.hash = '/overview';
            }}
          >
            Reset demo
          </button>
        </Panel>
      )}
    </div>
  );
}
