import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { Metric, Point, Status } from '../types';
import { utcDate, utcTime } from './ui';

const statusColor: Record<Status, string> = { normal: 'var(--normal)', watch: 'var(--watch)', review: 'var(--review)' };

/** Small inline trend with the personal baseline band behind it. */
export function Sparkline({ metric, days = 14 }: { metric: Metric; days?: number }) {
  const pts = metric.daily.slice(-days);
  const vals = pts.map((p) => p.v).filter((v): v is number => v !== null);
  const b = metric.baseline;
  let min = Math.min(...vals, b?.low ?? Infinity);
  let max = Math.max(...vals, b?.high ?? -Infinity);
  const pad = (max - min) * 0.15 || 1;
  min -= pad;
  max += pad;
  const W = 160;
  const H = 40;
  const x = (i: number) => (i / (pts.length - 1)) * W;
  const y = (v: number) => H - ((v - min) / (max - min)) * H;
  let d = '';
  pts.forEach((p, i) => {
    if (p.v === null) return;
    d += `${d && pts[i - 1]?.v !== null ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.v).toFixed(1)}`;
  });
  const lastPt = pts[pts.length - 1];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="spark" role="img" aria-label={`${metric.label}, last ${days} days`}>
      {b && <rect x={0} y={y(b.high)} width={W} height={Math.max(1, y(b.low) - y(b.high))} className="spark-band" />}
      <path d={d} fill="none" stroke={statusColor[metric.status]} strokeWidth={1.6} vectorEffect="non-scaling-stroke" />
      {lastPt.v !== null && <circle cx={x(pts.length - 1)} cy={y(lastPt.v)} r={2.6} fill={statusColor[metric.status]} />}
    </svg>
  );
}

export type Range = '24h' | '7d' | '30d';

export function seriesFor(metric: Metric, range: Range): { points: Point[]; hourly: boolean } {
  if (range === '24h') {
    if (metric.hourly) return { points: metric.hourly.slice(-25), hourly: true };
    return { points: metric.daily.slice(-7), hourly: false };
  }
  return { points: metric.daily.slice(range === '7d' ? -7 : -30), hourly: false };
}

export function TrendChart({ metric, range, height = 240 }: { metric: Metric; range: Range; height?: number }) {
  const { points, hourly } = seriesFor(metric, range);
  const b = metric.baseline;
  const data = points.map((p) => ({
    t: p.t,
    v: p.v,
    band: b ? [Number(b.low.toFixed(metric.decimals + 1)), Number(b.high.toFixed(metric.decimals + 1))] : undefined,
  }));
  const color = statusColor[metric.status];
  return (
    <div style={{ width: '100%', height }}>
      <ResponsiveContainer>
        <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -8 }}>
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis
            dataKey="t"
            tickFormatter={(t: string) => (hourly ? utcTime(t) : utcDate(t))}
            tick={{ fill: 'var(--muted)', fontSize: 12 }}
            axisLine={{ stroke: 'var(--line)' }}
            tickLine={false}
            minTickGap={28}
          />
          <YAxis
            tick={{ fill: 'var(--muted)', fontSize: 12 }}
            axisLine={false}
            tickLine={false}
            width={52}
            domain={['auto', 'auto']}
            tickFormatter={(v: number) => v.toFixed(metric.decimals)}
          />
          {b && <Area dataKey="band" stroke="none" fill="var(--band)" isAnimationActive={false} activeDot={false} name="Your usual range" />}
          {b && <ReferenceLine y={b.mean} stroke="var(--band-line)" strokeDasharray="4 4" />}
          <Line
            dataKey="v"
            stroke={color}
            strokeWidth={2}
            dot={hourly ? false : { r: 2.5, fill: color, strokeWidth: 0 }}
            activeDot={{ r: 4 }}
            connectNulls={false}
            isAnimationActive={false}
            name={metric.label}
          />
          <Tooltip
            cursor={{ stroke: 'var(--line-strong)' }}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const row = payload[0].payload as (typeof data)[number];
              return (
                <div className="tip">
                  <div className="tip-t">{hourly ? `${utcDate(row.t)} ${utcTime(row.t)} UTC` : utcDate(row.t)}</div>
                  <div className="tip-v">
                    {row.v === null ? 'No reading' : `${row.v.toFixed(metric.decimals)} ${metric.unit}`}
                  </div>
                  {b && (
                    <div className="tip-b">
                      Usual {b.low.toFixed(metric.decimals)}–{b.high.toFixed(metric.decimals)}
                    </div>
                  )}
                </div>
              );
            }}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
