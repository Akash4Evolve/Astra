import type { ReactNode } from 'react';
import type { Provenance, Quality, Status } from '../types';
import { nowMs } from '../store';

// ---------- formatting ----------
export const fmt = (v: number | null | undefined, d = 0) => (v === null || v === undefined ? '—' : v.toFixed(d));

export function ago(iso: string) {
  const s = Math.max(0, Math.round((nowMs() - new Date(iso).getTime()) / 1000));
  if (s < 60) return 'just now';
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} h ago`;
  return `${Math.round(h / 24)} d ago`;
}

export const utcTime = (iso: string) =>
  new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' });
export const utcDate = (iso: string) =>
  new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' });

/** Minutes after which a reading is shown as stale. */
export const STALE_MIN = 6 * 60;
export const isStale = (iso: string) => (nowMs() - new Date(iso).getTime()) / 60000 > STALE_MIN;

// ---------- icons (24px stroke) ----------
const paths: Record<string, ReactNode> = {
  heart: <path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z" />,
  pulse: <path d="M3 12h4l2-5 4 10 2-5h6" />,
  drop: <path d="M12 3s6 6.4 6 11a6 6 0 0 1-12 0c0-4.6 6-11 6-11z" />,
  o2: (
    <>
      <circle cx="9" cy="11" r="5" />
      <path d="M16 15.5c0-1 2.5-1.6 2.5-.1 0 1-2.5 2.6-2.5 3.6h3" />
    </>
  ),
  thermo: (
    <>
      <path d="M10 13.5V5a2 2 0 0 1 4 0v8.5a4 4 0 1 1-4 0z" />
      <path d="M12 9v7" />
    </>
  ),
  radiation: (
    <>
      <circle cx="12" cy="12" r="1.6" />
      <path d="M12 3.5a8.5 8.5 0 0 1 7.4 4.3L14 11M4.6 7.8A8.5 8.5 0 0 1 12 3.5M10 11 4.6 7.8M10.6 14.2 7.8 19.6a8.5 8.5 0 0 0 8.4 0l-2.8-5.4M4.6 7.8 10 11" />
    </>
  ),
  moon: <path d="M19 14.5A7.5 7.5 0 1 1 9.5 5a6 6 0 0 0 9.5 9.5z" />,
  brain: <path d="M9 4a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 6 1V5a2 2 0 0 0-3-1zm6 0a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-6 1" />,
  bone: <path d="M7 4.5a2.5 2.5 0 0 0-2.4 3.2A2.5 2.5 0 1 0 7.7 11L13 16.3a2.5 2.5 0 1 0 3.3 3.1 2.5 2.5 0 1 0 3.1-3.3L14 11 8.8 5.7A2.5 2.5 0 0 0 7 4.5z" />,
  shield: <path d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6l7-3z" />,
  wind: <path d="M3 8h11a3 3 0 1 0-3-3M3 12h16a3 3 0 1 1-3 3M3 16h7" />,
  home: <path d="M4 11l8-7 8 7v9h-5v-6H9v6H4z" />,
  chart: <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />,
  bell: <path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4zM10 20a2 2 0 0 0 4 0" />,
  check: <path d="M5 12l4 4 10-10" />,
  clipboard: (
    <>
      <rect x="5" y="4" width="14" height="17" rx="2" />
      <path d="M9 4V3h6v1M9 11h6M9 15h4" />
    </>
  ),
  list: <path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01" />,
  sat: <path d="M12 21a9 9 0 0 1-9-9M12 17a5 5 0 0 1-5-5M14 6l4 4M13 3l8 8-3 3-8-8z" />,
  database: (
    <>
      <ellipse cx="12" cy="5" rx="7" ry="3" />
      <path d="M5 5v14c0 1.7 3 3 7 3s7-1.3 7-3V5M5 12c0 1.7 3 3 7 3s7-1.3 7-3" />
    </>
  ),
  warn: <path d="M12 3l9.5 17h-19zM12 10v4M12 17.5v.01" />,
  info: <path d="M12 21a9 9 0 1 1 0-18 9 9 0 0 1 0 18zM12 11v6M12 7.5v.01" />,
  arrow: <path d="M5 12h14M13 6l6 6-6 6" />,
  back: <path d="M19 12H5M11 6l-6 6 6 6" />,
  clock: <path d="M12 21a9 9 0 1 1 0-18 9 9 0 0 1 0 18zM12 7v5l3 2" />,
  up: <path d="M12 19V5M6 11l6-6 6 6" />,
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  person: <path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0" />,
  play: <path d="M7 5v14l12-7z" />,
  pause: <path d="M8 5v14M16 5v14" />,
  users: <path d="M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM2.5 20a6.5 6.5 0 0 1 13 0M16 4.3a3.5 3.5 0 0 1 0 6.4M18 14.2a6.5 6.5 0 0 1 3.5 5.8" />,
  download: <path d="M12 4v11M7 11l5 5 5-5M5 20h14" />,
  copy: (
    <>
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M5 15V6a2 2 0 0 1 2-2h9" />
    </>
  ),
  flag: <path d="M5 21V4M5 5h11l-2 4 2 4H5" />,
  dumbbell: <path d="M6 7v10M3 9v6M18 7v10M21 9v6M6 12h12" />,
};

export function Icon({ name, size = 20, className }: { name: keyof typeof paths | string; size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className}
    >
      {paths[name] ?? paths.info}
    </svg>
  );
}

// ---------- status / provenance / quality ----------
export const statusText: Record<Status, string> = { normal: 'Normal', watch: 'Watch', review: 'Needs review' };
const statusIcon: Record<Status, string> = { normal: 'check', watch: 'info', review: 'warn' };

export function StatusChip({ status, small }: { status: Status; small?: boolean }) {
  return (
    <span className={`chip chip-${status}${small ? ' chip-sm' : ''}`}>
      <Icon name={statusIcon[status]} size={small ? 12 : 14} />
      {statusText[status]}
    </span>
  );
}

const provText: Record<Provenance, string> = { sensor: 'Sensor', 'self-report': 'Self-reported', simulated: 'Simulated' };
export function ProvenanceTag({ p }: { p: Provenance }) {
  return (
    <span className={`prov prov-${p}`} title={p === 'simulated' ? 'Synthetic demo data, not a real reading' : undefined}>
      {provText[p]}
    </span>
  );
}

export function Freshness({ at, quality, note }: { at: string; quality?: Quality; note?: string }) {
  const stale = isStale(at);
  const degraded = quality && quality !== 'good';
  return (
    <span className={`fresh${stale || degraded ? ' fresh-warn' : ''}`} title={note}>
      <Icon name={degraded ? 'warn' : 'clock'} size={12} />
      {stale ? `Stale, ${ago(at)}` : ago(at)}
      {degraded && <span className="fresh-note">{note ?? 'Partial data'}</span>}
    </span>
  );
}

export function Panel({
  title,
  icon,
  action,
  children,
  className = '',
  id,
}: {
  title: string;
  icon?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <section className={`panel ${className}`} aria-labelledby={id}>
      <header className="panel-head">
        <h2 id={id}>
          {icon && <Icon name={icon} size={18} className="panel-icon" />}
          {title}
        </h2>
        {action}
      </header>
      {children}
    </section>
  );
}

/** Ring showing how many readings are normal, in the colour of the overall status. */
export function CountRing({ normal, total, status, size = 96 }: { normal: number; total: number; status: Status; size?: number }) {
  const r = 42;
  const c = 2 * Math.PI * r;
  const frac = total ? normal / total : 0;
  return (
    <div className={`ring ring-${status}`} style={{ width: size, height: size }} role="img" aria-label={`${normal} of ${total} readings normal`}>
      <svg viewBox="0 0 100 100" aria-hidden="true">
        <circle cx="50" cy="50" r={r} className="ring-track" />
        <circle cx="50" cy="50" r={r} className="ring-fill" strokeDasharray={`${c * frac} ${c}`} transform="rotate(-90 50 50)" />
      </svg>
      <span className="ring-text">
        <span className="num">{normal}</span>
        <span className="ring-of">of {total}</span>
      </span>
    </div>
  );
}
