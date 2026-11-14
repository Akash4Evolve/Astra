import { useState } from 'react';
import { BodyMap } from '../components/BodyMap';
import { SystemDetail } from '../components/Explain';
import { Model3D } from '../components/Model3D';
import { Sparkline, TrendChart, type Range } from '../components/charts';
import { MissionTimeline } from '../components/MissionTimeline';
import { CountRing, Freshness, Icon, Panel, ProvenanceTag, StatusChip, fmt, statusText, utcTime } from '../components/ui';
import { SIMULATED_DATASET } from '../api/client';
import { LIMITS } from '../data/crew';
import { alertState, domainIcon, domainLabel, domainReason, domainStatuses, isActive, overallStatus, readingCount } from '../derive';
import { useStore } from '../store';
import type { Dashboard, Domain, Metric, MetricId } from '../types';
import { go } from '../router';

function delta(m: Metric) {
  if (!m.baseline || m.latest === null) return null;
  const d = m.latest - m.baseline.mean;
  return { d, pct: (d / m.baseline.mean) * 100 };
}

function VitalTile({ m, value, sub, label }: { m: Metric; value?: string; sub?: string; label?: string }) {
  const dl = delta(m);
  return (
    <a className={`vital vital-${m.status}`} href={`#/trends/${m.id}`} aria-label={`${m.label}: open trend`}>
      <div className="vital-top">
        <h3 title={m.label}>{label ?? m.label}</h3>
        <Icon name="arrow" size={14} className="vital-go" />
      </div>
      <div className="vital-value">
        <span className="num">{value ?? fmt(m.latest, m.decimals)}</span>
        <span className="unit">{m.unit}</span>
      </div>
      <div className="vital-status">
        <StatusChip status={m.status} small />
        {dl && Math.abs(dl.pct) >= 1 && (
          <span className={`delta ${m.status !== 'normal' ? 'delta-hot' : ''}`} title="Compared with your usual average">
            {dl.d > 0 ? '+' : '−'}
            {Math.abs(dl.pct).toFixed(0)}%
          </span>
        )}
      </div>
      <Sparkline metric={m} />
      <div className="vital-base">
        {sub ?? (m.baseline ? `Usual ${m.baseline.low.toFixed(m.decimals)}–${m.baseline.high.toFixed(m.decimals)}` : 'No baseline')}
      </div>
      <footer className="vital-foot">
        <Freshness at={m.latestAt} quality={m.quality} note={m.qualityNote} />
        <ProvenanceTag p={m.provenance} />
      </footer>
    </a>
  );
}

/** The one thing to know right now: overall status, the most serious alert, and what to do next. */
function Hero({ d }: { d: Dashboard }) {
  const { alertStates, checkins, pending, linkUp } = useStore();
  const active = d.alerts.filter((a) => isActive(alertState(a, alertStates)));
  const status = overallStatus(d, alertStates);
  const count = readingCount(d);
  const top = active[0];
  const next = d.schedule.find((s) => !s.done && !(s.label === 'Daily check-in' && checkins.length > 0));
  const outside = count.total - count.normal;
  return (
    <section className={`hero hero-${status}`} aria-label="Status summary">
      <CountRing normal={count.normal} total={count.total} status={status} size={104} />
      <div className="hero-main">
        <p className="hero-kicker">
          <StatusChip status={status} />
          <span className="muted">
            {count.normal} of {count.total} readings normal
          </span>
        </p>
        {top ? (
          <>
            <h2 className="hero-title">{top.title}</h2>
            <p className="hero-sum">
              {top.summary}
              {active.length > 1 && (
                <>
                  {' '}
                  <a href="#/alerts" className="hero-more">
                    {active.length - 1} more {active.length === 2 ? 'alert' : 'alerts'}
                  </a>
                </>
              )}
            </p>
          </>
        ) : (
          <>
            <h2 className="hero-title">{outside === 0 ? 'All readings are in your usual range' : 'No active alerts'}</h2>
            <p className="hero-sum">
              {outside === 0
                ? 'Astra keeps comparing each reading with your own baseline and will tell you when something changes.'
                : `${outside} ${outside === 1 ? 'reading is' : 'readings are'} outside your usual range, but not by enough, or not for long enough, to raise an alert. `}
              {outside > 0 && (
                <a href="#/trends" className="hero-more">
                  See trends
                </a>
              )}
            </p>
          </>
        )}
        <div className="hero-actions">
          {top && (
            <button className="btn btn-primary" onClick={() => go(`/alerts/${top.id}`)}>
              {alertState(top, alertStates) === 'open' ? 'Review and respond' : 'Open alert'}
              <Icon name="arrow" size={16} />
            </button>
          )}
          {checkins.length === 0 && (
            <button className={`btn${top ? '' : ' btn-primary'}`} onClick={() => go('/checkin')}>
              Start daily check-in
            </button>
          )}
          <button className="btn" onClick={() => go('/measure')}>
            Log a measurement
          </button>
        </div>
      </div>
      <dl className="hero-facts">
        <div>
          <dt>Next up</dt>
          <dd>
            {next ? (
              <>
                <span className="num">{utcTime(next.at)}</span> {next.label}
              </>
            ) : (
              'Nothing else scheduled'
            )}
          </dd>
        </div>
        <div>
          <dt>Saved on board</dt>
          <dd>{pending ? `${pending} record${pending === 1 ? '' : 's'} waiting${linkUp ? '' : ' for the link'}` : 'Everything is sent'}</dd>
        </div>
        <div>
          <dt>Radiation so far</dt>
          <dd>
            <span className="num">{(d.cumulativeDoseMsv ?? 0).toFixed(0)}</span> of {LIMITS.radiationCareerMsv} mSv limit
          </dd>
        </div>
      </dl>
    </section>
  );
}

const trendTabs: { id: MetricId; label: string }[] = [
  { id: 'restingHr', label: 'Resting HR' },
  { id: 'hrv', label: 'HRV' },
  { id: 'sleep', label: 'Sleep' },
  { id: 'stress', label: 'Stress' },
  { id: 'bodyTemp', label: 'Temperature' },
  { id: 'co2', label: 'Cabin CO₂' },
  { id: 'radiation', label: 'Radiation' },
];

/** 24h is offered only for metrics with readings through the day. */
export function RangeTabs({ value, onChange, hourly = false }: { value: Range; onChange: (r: Range) => void; hourly?: boolean }) {
  const ranges: Range[] = hourly ? ['24h', '7d', '30d'] : ['7d', '30d'];
  return (
    <div className="seg" role="tablist" aria-label="Time range">
      {ranges.map((r) => (
        <button key={r} role="tab" aria-selected={value === r} className={value === r ? 'on' : ''} onClick={() => onChange(r)}>
          {r}
        </button>
      ))}
    </div>
  );
}

function TrendsPanel({ d }: { d: Dashboard }) {
  // Opens on the reading behind the most serious alert, if it is one of the tabs.
  const lead = d.alerts[0]?.evidence[0]?.metricId;
  const [id, setId] = useState<MetricId>(lead && trendTabs.some((t) => t.id === lead) ? lead : 'restingHr');
  const [range, setRange] = useState<Range>('30d');
  const m = d.metrics[id];
  const dailyOnly = range === '24h' && !m.hourly;
  return (
    <Panel title="Trends" icon="chart" className="p-trends" action={<RangeTabs value={range} onChange={setRange} hourly={!!m.hourly} />}>
      <div className="tabs" role="tablist" aria-label="Metric">
        {trendTabs.map((t) => (
          <button key={t.id} role="tab" aria-selected={id === t.id} className={id === t.id ? 'on' : ''} onClick={() => setId(t.id)}>
            <span className={`dot dot-${d.metrics[t.id].status}`} />
            {t.label}
          </button>
        ))}
      </div>
      <TrendChart metric={m} range={range} height={230} />
      <div className="legend">
        <span>
          <i className="lg-line" style={{ background: `var(--${m.status})` }} />
          {m.label} ({m.unit})
        </span>
        {m.baseline && (
          <span>
            <i className="lg-band" />
            Your usual range, {m.baseline.method}
          </span>
        )}
        {dailyOnly && <span className="muted">Daily metric: showing last 7 days</span>}
      </div>
    </Panel>
  );
}

function AlertsPanel({ d }: { d: Dashboard }) {
  const { alertStates } = useStore();
  const active = d.alerts.filter((a) => isActive(alertState(a, alertStates)));
  return (
    <Panel
      title={active.length ? `Alerts (${active.length})` : 'Alerts'}
      icon="bell"
      className={`p-alerts${active.length ? ' has-alerts' : ''}`}
      action={
        <button className="link" onClick={() => go('/alerts')}>
          All alerts
        </button>
      }
    >
      {active.length === 0 ? (
        <p className="empty">No active alerts. Readings are within your usual ranges.</p>
      ) : (
        <ul className="alert-list">
          {active.map((a) => {
            const st = alertState(a, alertStates);
            return (
              <li key={a.id}>
                <button className="alert-row" onClick={() => go(`/alerts/${a.id}`)}>
                  <Icon name={domainIcon[a.domain]} size={22} className={`ai ai-${a.status}`} />
                  <span className="alert-main">
                    <span className="alert-title">{a.title}</span>
                    <span className="alert-sum">{a.summary}</span>
                    <span className="alert-meta">
                      <StatusChip status={a.status} small />
                      <span className="state">{st === 'open' ? 'Not yet reviewed' : stateLabel[st]}</span>
                      <span>{utcTime(a.createdAt)} UTC</span>
                    </span>
                  </span>
                  <Icon name="arrow" size={18} className="chev" />
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}

export const stateLabel: Record<string, string> = {
  open: 'Open',
  acknowledged: 'Acknowledged',
  'action-logged': 'Action logged',
  'recheck-scheduled': 'Recheck scheduled',
  escalated: 'Escalated',
  resolved: 'Resolved',
};

function SystemsPanel({ d }: { d: Dashboard }) {
  const { alertStates } = useStore();
  const st = domainStatuses(d, alertStates);
  const domains = Object.keys(domainLabel) as Domain[];
  const watching = domains.filter((k) => st[k] !== 'normal').length;
  const [open, setOpen] = useState<Domain | null>(null);
  const toggle = (k: Domain) => setOpen((o) => (o === k ? null : k));
  return (
    <Panel title="Body systems" icon="pulse" className="p-systems">
      <p className="muted small sys-hint">Click a dot on the body, or a system in the list, to see what it does and how space affects it.</p>
      <div className="systems">
        <Model3D
          model="body"
          statuses={st}
          className="body3d"
          showLoader
          onSelect={toggle}
          markerInfo={Object.fromEntries(
            domains.map((k) => [k, { title: domainLabel[k], detail: domainReason(d, k), status: st[k] ?? 'normal' }]),
          )}
          label={`Body model. ${domains.map((k) => `${domainLabel[k]}: ${statusText[st[k] ?? 'normal']}`).join('. ')}.`}
          fallback={<BodyMap statuses={st} />}
        />
        <div>
          <p className="systems-lead">
            {watching === 0 ? 'All systems in your usual range' : `${watching} of ${domains.length} areas to watch`}
          </p>
          <ul className="domain-list">
            {domains.map((k) => (
              <li key={k}>
                <button type="button" className={`dom dom-${st[k]}${open === k ? ' dom-open' : ''}`} aria-expanded={open === k} onClick={() => toggle(k)}>
                  <Icon name={domainIcon[k]} size={18} />
                  <span className="dom-text">
                    <span className="dom-name">{domainLabel[k]}</span>
                    <span className="dom-why">{domainReason(d, k)}</span>
                  </span>
                  <StatusChip status={st[k]} small />
                </button>
              </li>
            ))}
          </ul>
        </div>
      </div>
      {open && <SystemDetail d={d} domain={open} status={st[open]} onClose={() => setOpen(null)} />}
    </Panel>
  );
}

function EnvPanel({ d }: { d: Dashboard }) {
  const env: Metric[] = [d.metrics.co2, d.metrics.cabinTemp, d.metrics.cabinNoise];
  const dose = d.cumulativeDoseMsv ?? 0;
  const pct = Math.min(100, (dose / LIMITS.radiationCareerMsv) * 100);
  return (
    <Panel title="Cabin and exposure" icon="wind" className="p-env">
      <div className="env-grid">
        {env.map((m) => (
          <div key={m.id} className={`env env-${m.status}`}>
            <span className="env-label">{m.label}</span>
            <span className="env-val">
              <span className="num">{fmt(m.latest, m.decimals)}</span> {m.unit}
            </span>
            <StatusChip status={m.status} small />
          </div>
        ))}
        <div className="env env-wide">
          <span className="env-label">Mission radiation dose</span>
          <span className="env-val">
            <span className="num">{dose.toFixed(1)}</span> mSv
            <span className="muted"> of NASA’s {LIMITS.radiationCareerMsv} mSv career limit</span>
          </span>
          <div className="meter" role="meter" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="Radiation dose used">
            <span style={{ width: `${pct}%` }} />
          </div>
          <span className="muted small">
            Today {fmt(d.metrics.radiation.latest, 2)} mSv <StatusChip status={d.metrics.radiation.status} small />
          </span>
        </div>
      </div>
      <p className="note">Cabin readings are context. A change here alongside a body change is an association, not a cause.</p>
    </Panel>
  );
}

function TodayPanel({ d }: { d: Dashboard }) {
  const { checkins } = useStore();
  const checkedIn = checkins.length > 0;
  return (
    <Panel title="Today" icon="clock" className="p-today">
      <ol className="timeline">
        {d.schedule.map((s) => {
          const done = s.done || (s.label === 'Daily check-in' && checkedIn);
          return (
            <li key={s.label} className={done ? 'done' : ''}>
              <span className="tl-dot">{done && <Icon name="check" size={12} />}</span>
              <span className="tl-time">{utcTime(s.at)}</span>
              <span className="tl-body">
                <span className="tl-label">{s.label}</span>
                <span className="tl-detail">{s.detail}</span>
              </span>
            </li>
          );
        })}
      </ol>
      {checkedIn && (
        <p className="note">Today’s check-in is recorded. Thank you.</p>
      )}
    </Panel>
  );
}

export function Overview() {
  const { dashboard: d, view, setView } = useStore();
  if (!d) return null;
  const m = d.metrics;
  return (
    <div className="grid-overview">
      <Hero d={d} />
      <h2 className="sr-only">Latest vitals</h2>
      <div className="vitals">
        <VitalTile m={m.restingHr} label="Resting HR" />
        <VitalTile m={m.hrv} label="HRV" />
        <VitalTile m={m.bpSys} value={`${fmt(m.bpSys.latest)}/${fmt(m.bpDia.latest)}`} />
        <VitalTile m={m.spo2} />
        <VitalTile m={m.bodyTemp} label="Body temp" />
        <VitalTile m={m.sleep} />
      </div>
      {SIMULATED_DATASET && (
        <Panel title="Your mission so far" icon="flag" className="p-mission">
          <MissionTimeline crewIds={[view.crewId]} day={view.day} activeCrew={view.crewId} onPick={(crewId, day) => setView({ crewId, day })} />
        </Panel>
      )}
      <SystemsPanel d={d} />
      <div className="ov-stack">
        <AlertsPanel d={d} />
        <TodayPanel d={d} />
      </div>
      <TrendsPanel d={d} />
      <EnvPanel d={d} />
    </div>
  );
}
