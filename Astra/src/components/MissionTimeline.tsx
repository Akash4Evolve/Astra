import { useMemo, useState, type MouseEvent } from 'react';
import { MISSION_LENGTH } from '../data/crew';
import { CREW, crewHistory } from '../data/crewData';
import { statusText } from './ui';

interface Props {
  /** Crew members to show, one row each. */
  crewIds: string[];
  /** The mission day being viewed. Later days are not shown, as they haven't happened yet. */
  day: number;
  /** The crew member whose row is highlighted. */
  activeCrew?: string;
  onPick: (crewId: string, day: number) => void;
}

const TICKS = [1, 30, 60, 90, 120, 150, 180];

/**
 * The mission so far as a strip of days, one row per crew member. Bar height and colour
 * both show the day's alert status. Clicking a day opens it (a demo control: the day
 * stepper in the demo bar does the same from the keyboard).
 */
export function MissionTimeline({ crewIds, day, activeCrew, onPick }: Props) {
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const rows = useMemo(() => crewIds.map((id) => ({ crew: CREW.find((c) => c.id === id)!, days: crewHistory(id) })), [crewIds.join(',')]);
  const [hover, setHover] = useState<{ crewId: string; day: number } | null>(null);

  const cellOf = (e: MouseEvent) => {
    const el = (e.target as HTMLElement).closest<HTMLElement>('[data-day]');
    return el ? { crewId: el.dataset.crew!, day: Number(el.dataset.day) } : null;
  };

  const shown = hover ?? (activeCrew ? { crewId: activeCrew, day } : null);
  const shownRow = shown && rows.find((r) => r.crew.id === shown.crewId);
  const shownDay = shownRow?.days[shown!.day - 1];
  const future = !!shown && shown.day > day;

  return (
    <div className="mt">
      <div
        className="mt-rows"
        onMouseMove={(e) => {
          const c = cellOf(e);
          setHover((h) => (h?.day === c?.day && h?.crewId === c?.crewId ? h : c));
        }}
        onMouseLeave={() => setHover(null)}
        onClick={(e) => {
          const c = cellOf(e);
          if (c) onPick(c.crewId, c.day);
        }}
      >
        {rows.map(({ crew, days }) => {
          const past = days.slice(0, day);
          const flagged = past.filter((d) => d.status !== 'normal').length;
          return (
            <div key={crew.id} className={`mt-row${crew.id === activeCrew ? ' mt-row-on' : ''}`}>
              {rows.length > 1 && (
                <span className="mt-label">
                  <span className="num">{crew.id}</span>
                </span>
              )}
              <div
                className="mt-strip"
                role="img"
                aria-label={`${crew.name}: ${flagged} of ${past.length} mission days so far had an active alert`}
              >
                {days.map((d) => {
                  const isFuture = d.day > day;
                  return (
                    <i
                      key={d.day}
                      data-day={d.day}
                      data-crew={crew.id}
                      className={`mt-cell mt-${isFuture ? 'future' : d.status}${d.day === day ? ' mt-now' : ''}${
                        hover?.day === d.day && hover.crewId === crew.id ? ' mt-hover' : ''
                      }`}
                    />
                  );
                })}
              </div>
            </div>
          );
        })}
        <div className={`mt-axis${rows.length > 1 ? ' mt-axis-inset' : ''}`} aria-hidden="true">
          {TICKS.map((t) => (
            <span key={t} style={{ left: `${((t - 0.5) / MISSION_LENGTH) * 100}%` }}>
              {t}
            </span>
          ))}
        </div>
      </div>
      <div className="mt-foot">
        <p className="mt-read" aria-live="off">
          {shown && shownRow && shownDay ? (
            <>
              <strong>
                Day {shown.day}
                {rows.length > 1 ? `, ${shownRow.crew.id}` : ''}
              </strong>
              {future ? (
                <span className="muted">Not reached yet</span>
              ) : shownDay.alerts.length ? (
                <>
                  <span className={`mt-status mt-status-${shownDay.status}`}>{statusText[shownDay.status]}</span>
                  <span>{shownDay.alerts.map((a) => a.title).join('; ')}</span>
                </>
              ) : (
                <span className="muted">No alerts</span>
              )}
            </>
          ) : (
            <span className="muted">Point at a day to see what happened</span>
          )}
        </p>
        <ul className="mt-legend" aria-label="Key">
          <li>
            <i className="mt-key mt-normal" /> No alert
          </li>
          <li>
            <i className="mt-key mt-watch" /> Watch
          </li>
          <li>
            <i className="mt-key mt-review" /> Needs review
          </li>
        </ul>
      </div>
    </div>
  );
}
