import { useState } from 'react';
import { TrendChart, type Range } from '../components/charts';
import { GuideCard, metricGuide } from '../components/Explain';
import { Freshness, Panel, ProvenanceTag, StatusChip, fmt } from '../components/ui';
import { domainLabel, hazardLabel } from '../derive';
import { useStore } from '../store';
import type { Metric, MetricId } from '../types';
import { RangeTabs } from './Overview';

const mean = (m: Metric, n: number) => {
  const v = m.daily.slice(-n).map((p) => p.v).filter((x): x is number => x !== null);
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
};

export function Trends({ initial }: { initial?: MetricId }) {
  const { dashboard: d } = useStore();
  const [id, setId] = useState<MetricId>(initial && d?.metrics[initial] ? initial : 'restingHr');
  const [range, setRange] = useState<Range>('30d');
  if (!d) return null;
  const list = Object.values(d.metrics).filter((m) => m.id !== 'bpDia');
  // Grouped by NASA's five spaceflight hazards.
  const groupOf = (m: Metric) => (m.hazard ? hazardLabel[m.hazard] : domainLabel[m.domain]);
  const byGroup = list.reduce((acc, m) => ((acc[groupOf(m)] ??= []).push(m), acc), {} as Record<string, Metric[]>);
  const m = d.metrics[id];

  return (
    <div className="page">
      <header className="page-head">
        <h1>Trends and baseline</h1>
        <p className="lede">
          Your usual range is learned from your own readings over 21 days, leaving out the most recent week and any spell
          that was already out of range. Readings are grouped by NASA’s five spaceflight hazards.
        </p>
      </header>

      <div className="trends-layout">
        <nav className="metric-nav" aria-label="Metrics">
          {Object.keys(byGroup).map((g) => (
            <div key={g} className="mn-group">
              <h2>{g}</h2>
              {byGroup[g].map((x) => (
                <button key={x.id} className={x.id === id ? 'on' : ''} aria-current={x.id === id} onClick={() => setId(x.id)}>
                  <span className={`dot dot-${x.status}`} />
                  {x.label}
                </button>
              ))}
            </div>
          ))}
        </nav>

        <div className="trends-main">
          <Panel title={`${m.label} (${m.unit})`} icon="chart" action={<RangeTabs value={range} onChange={setRange} hourly={!!m.hourly} />}>
            <div className="trend-meta">
              <StatusChip status={m.status} small />
              <Freshness at={m.latestAt} quality={m.quality} note={m.qualityNote} />
              <ProvenanceTag p={m.provenance} />
              {m.baseline && <span className="muted small">Baseline: {m.baseline.method}</span>}
            </div>
            <TrendChart metric={m} range={range} height={320} />
            {range === '24h' && !m.hourly && <p className="muted small">This is a daily reading, so the last 7 days are shown.</p>}
          </Panel>

          {metricGuide(id) && (
            <Panel title={`About ${m.label.toLowerCase()}`} icon="info">
              <GuideCard guide={metricGuide(id)!} />
            </Panel>
          )}

          <Panel title="All readings against your baseline" icon="list">
            <div className="table-wrap">
              <table className="base-table">
                <thead>
                  <tr>
                    <th scope="col">Reading</th>
                    <th scope="col">Latest</th>
                    <th scope="col">7-day mean</th>
                    <th scope="col">Your usual</th>
                    <th scope="col">Status</th>
                    <th scope="col">Source</th>
                  </tr>
                </thead>
                <tbody>
                  {list.map((x) => (
                    <tr key={x.id} className={x.id === id ? 'sel' : ''} onClick={() => setId(x.id)}>
                      <th scope="row">{x.label}</th>
                      <td className="num">
                        {fmt(x.latest, x.decimals)} <span className="muted">{x.unit}</span>
                      </td>
                      <td className="num">{fmt(mean(x, 7), x.decimals)}</td>
                      <td className="num">{x.baseline ? `${x.baseline.low.toFixed(x.decimals)}–${x.baseline.high.toFixed(x.decimals)}` : '—'}</td>
                      <td>
                        <StatusChip status={x.status} small />
                      </td>
                      <td>
                        <ProvenanceTag p={x.provenance} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}
