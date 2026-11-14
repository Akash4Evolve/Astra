import { useEffect, useRef } from 'react';
import { METRICS, SYSTEMS, type MetricGuide, type Source } from '../data/guide';
import { domainIcon, domainLabel, hazardLabel, isActive, alertState } from '../derive';
import { go } from '../router';
import { useStore } from '../store';
import type { Dashboard, Domain, MetricId, Status } from '../types';
import { Icon, StatusChip, fmt } from './ui';

export function Sources({ sources }: { sources: Source[] }) {
  return (
    <p className="sources-line">
      Source{sources.length > 1 ? 's' : ''}:{' '}
      {sources.map((s, i) => (
        <span key={s.url}>
          {i > 0 && '; '}
          <a href={s.url} target="_blank" rel="noreferrer">
            {s.label}
          </a>
        </span>
      ))}
    </p>
  );
}

/** What a reading is, how to take it, why it matters in space, and when to get help. */
export function GuideCard({ guide }: { guide: MetricGuide }) {
  return (
    <div className="guide">
      <dl className="guide-list">
        <div>
          <dt>What it is</dt>
          <dd>{guide.what}</dd>
        </div>
        <div>
          <dt>How to measure</dt>
          <dd>{guide.howToMeasure}</dd>
        </div>
        <div>
          <dt>Why it matters in space</dt>
          <dd>{guide.whyInSpace}</dd>
        </div>
        <div>
          <dt>When to get help</dt>
          <dd>{guide.getHelp}</dd>
        </div>
      </dl>
      <Sources sources={guide.sources} />
    </div>
  );
}

export const metricGuide = (id: MetricId) => METRICS[id];

/** Detail for one body system: what it does, how space affects it, its readings and alerts. */
export function SystemDetail({ d, domain, status, onClose }: { d: Dashboard; domain: Domain; status: Status; onClose: () => void }) {
  const { alertStates } = useStore();
  const g = SYSTEMS[domain];
  const readings = Object.values(d.metrics).filter((m) => m.domain === domain && m.id !== 'bpDia');
  const alerts = d.alerts.filter((a) => a.domain === domain && isActive(alertState(a, alertStates)));
  const ref = useRef<HTMLElement>(null);
  // Bring the panel into view when a system is picked, since it opens below the list.
  useEffect(() => {
    const smooth = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    ref.current?.scrollIntoView({ block: 'nearest', behavior: smooth ? 'smooth' : 'auto' });
  }, [domain]);
  return (
    <section ref={ref} className={`sysdetail sd-${status}`} aria-labelledby="sysdetail-title">
      <header className="sd-head">
        <Icon name={domainIcon[domain]} size={22} />
        <h3 id="sysdetail-title">{domainLabel[domain]}</h3>
        <StatusChip status={status} small />
        <button type="button" className="sd-close" onClick={onClose} aria-label="Close details">
          ×
        </button>
      </header>

      {alerts.length > 0 && (
        <ul className="sd-alerts">
          {alerts.map((a) => (
            <li key={a.id}>
              <button type="button" className="link" onClick={() => go(`/alerts/${a.id}`)}>
                {a.title} →
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="sd-grid">
        <div>
          <h4>What it does</h4>
          <p>{g.function}</p>
          <h4>In space</h4>
          <p>{g.inSpace}</p>
          <div className="sd-hazards">
            {g.hazards.map((h) => (
              <span key={h} className="hazard-tag">
                {hazardLabel[h]}
              </span>
            ))}
          </div>
        </div>
        <div>
          <h4>Your readings</h4>
          <ul className="sd-readings">
            {readings.map((m) => (
              <li key={m.id}>
                <button type="button" onClick={() => go(`/trends/${m.id}`)}>
                  <span className={`dot dot-${m.status}`} />
                  <span className="sd-r-label">{m.label}</span>
                  <span className="num">
                    {m.id === 'bpSys' ? `${fmt(m.latest)}/${fmt(d.metrics.bpDia?.latest)}` : fmt(m.latest, m.decimals)} <span className="muted">{m.unit}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <h4>Looking after it</h4>
          <ul className="sd-care">
            {g.selfCare.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </div>
      </div>
      <Sources sources={g.sources} />
    </section>
  );
}
