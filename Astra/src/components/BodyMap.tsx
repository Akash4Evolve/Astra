import type { Domain, Status } from '../types';
import { statusText } from './ui';

const spots: { domain: Domain; x: number; y: number; label: string }[] = [
  { domain: 'sleep-behaviour', x: 100, y: 44, label: 'Sleep and behaviour' },
  { domain: 'cardiovascular', x: 108, y: 122, label: 'Cardiovascular' },
  { domain: 'immune-symptoms', x: 100, y: 184, label: 'Immune and symptoms' },
  { domain: 'musculoskeletal', x: 83, y: 300, label: 'Musculoskeletal' },
];

const color: Record<Status, string> = { normal: 'var(--normal)', watch: 'var(--watch)', review: 'var(--review)' };

function Figure({ outline }: { outline: boolean }) {
  const extra = outline ? 3 : 0;
  const fill = outline ? 'var(--body-edge)' : 'url(#bodyFill)';
  const limb = (pts: string, w: number) => (
    <polyline points={pts} fill="none" stroke={fill} strokeWidth={w + extra} strokeLinecap="round" strokeLinejoin="round" />
  );
  return (
    <g>
      <circle cx={100} cy={44} r={25 + extra / 2} fill={fill} />
      <rect x={89 - extra / 2} y={62} width={22 + extra} height={26} rx={8} fill={fill} />
      <path
        d="M58 96 Q100 80 142 96 L148 156 Q142 196 134 226 L66 226 Q58 196 52 156 Z"
        fill={fill}
        stroke={outline ? fill : 'none'}
        strokeWidth={extra}
        strokeLinejoin="round"
      />
      {limb('64,102 46,160 40,228', 19)}
      {limb('136,102 154,160 160,228', 19)}
      {limb('84,222 80,318 78,398', 27)}
      {limb('116,222 120,318 122,398', 27)}
    </g>
  );
}

export function BodyMap({ statuses }: { statuses: Partial<Record<Domain, Status>> }) {
  return (
    <svg viewBox="0 0 200 420" className="bodymap" role="img" aria-label="Body systems status">
      <defs>
        <linearGradient id="bodyFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#1d4f8f" stopOpacity="0.9" />
          <stop offset="1" stopColor="#0d2a52" stopOpacity="0.7" />
        </linearGradient>
        <radialGradient id="halo">
          <stop offset="0" stopColor="#3c8cff" stopOpacity="0.25" />
          <stop offset="1" stopColor="#3c8cff" stopOpacity="0" />
        </radialGradient>
      </defs>
      <ellipse cx={100} cy={210} rx={96} ry={205} fill="url(#halo)" />
      <Figure outline />
      <Figure outline={false} />
      <g style={{ mixBlendMode: 'screen' }}>
        <Figure outline={false} />
      </g>
      <path d="M100 70 V226 M100 96 Q86 140 100 184 Q114 140 100 96" stroke="#9cc6ff" strokeOpacity="0.35" fill="none" />
      {spots.map((s) => {
        const st = statuses[s.domain] ?? 'normal';
        return (
          <g key={s.domain} transform={`translate(${s.x} ${s.y})`}>
            <title>{`${s.label}: ${statusText[st]}`}</title>
            {st !== 'normal' && <circle r={13} fill={color[st]} opacity={0.18} className="pulse-ring" />}
            <circle r={6} fill={color[st]} stroke="#061020" strokeWidth={2} />
          </g>
        );
      })}
    </svg>
  );
}
