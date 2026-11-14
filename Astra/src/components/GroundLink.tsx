import { DEMO_MODE } from '../api/client';
import { useStore } from '../store';
import { Icon, utcTime } from './ui';

type Phase = 'down' | 'acquiring' | 'up';

/** Ground link status and control: a station-to-Earth beam that lights up and carries queued records. */
export function GroundLink() {
  // The connecting step lives in the store, so it finishes even if this page is left.
  const { linkUp, acquiring, connectLink: connect, dropLink: drop, pending, syncing, lastSync, syncError } = useStore();

  const phase: Phase = linkUp ? 'up' : acquiring ? 'acquiring' : 'down';
  const sending = linkUp && (syncing || pending > 0);

  const headline = { down: 'No signal', acquiring: 'Acquiring signal…', up: sending ? 'Transmitting' : 'Link established' }[phase];
  const detail =
    phase === 'up'
      ? sending
        ? `Sending ${pending} record${pending === 1 ? '' : 's'} to the ground…`
        : 'Everything recorded on board has been sent to the ground.'
      : pending
        ? `${pending} record${pending === 1 ? '' : 's'} saved on board, waiting to send.`
        : 'Nothing waiting. New records will be saved on board until the link is back.';

  return (
    <div className={`gl gl-${phase}${sending ? ' gl-sending' : ''}`}>
      <svg className="gl-viz" viewBox="0 0 320 96" aria-hidden="true">
        <defs>
          <radialGradient id="glEarth" cx="35%" cy="30%">
            <stop offset="0" stopColor="#5fa8ff" />
            <stop offset="0.6" stopColor="#1d5bb8" />
            <stop offset="1" stopColor="#0a2550" />
          </radialGradient>
        </defs>
        {/* station */}
        <g className="gl-station" transform="translate(34 48)">
          <rect x="-14" y="-5" width="28" height="10" rx="3" />
          <rect x="-30" y="-12" width="12" height="24" rx="1.5" className="gl-panel" />
          <rect x="18" y="-12" width="12" height="24" rx="1.5" className="gl-panel" />
        </g>
        {/* signal arcs from the station */}
        <g className="gl-arcs" fill="none">
          <path d="M60 36 a16 16 0 0 1 0 24" />
          <path d="M68 30 a24 24 0 0 1 0 36" />
          <path d="M76 24 a32 32 0 0 1 0 48" />
        </g>
        {/* beam to Earth */}
        <line className="gl-beam" x1="92" y1="48" x2="252" y2="48" />
        <g className="gl-packets">
          <circle cx="92" cy="48" r="3.5" />
          <circle cx="92" cy="48" r="3.5" />
          <circle cx="92" cy="48" r="3.5" />
        </g>
        {/* Earth */}
        <circle className="gl-earth" cx="282" cy="48" r="28" fill="url(#glEarth)" />
        <circle className="gl-ground" cx="258" cy="40" r="4" />
      </svg>

      <div className="gl-body">
        <div className="gl-status" role="status" aria-live="polite">
          <span className="gl-light" aria-hidden="true" />
          <span className="gl-head">{headline}</span>
        </div>
        <p className="gl-detail">{detail}</p>
        <p className="gl-meta">
          {phase === 'up'
            ? `In contact with the ground${lastSync ? `. Last records sent ${utcTime(lastSync)} UTC` : ''}.`
            : lastSync
              ? `Last contact with the ground ${utcTime(lastSync)} UTC.`
              : 'No contact with the ground yet this session.'}
          {syncError && pending > 0 && <span className="gl-err"> Last send failed; retrying automatically.</span>}
        </p>

        {phase === 'up' ? (
          <button type="button" className="gl-btn gl-btn-drop" onClick={drop}>
            <Icon name="sat" size={18} /> Drop link
          </button>
        ) : (
          <button type="button" className="gl-btn" onClick={connect} disabled={phase === 'acquiring'}>
            <Icon name="sat" size={20} /> {phase === 'acquiring' ? 'Connecting…' : 'Establish ground link'}
          </button>
        )}
        {DEMO_MODE && <p className="muted small">Demo control. Drop the link to see records queue on board, then reconnect to send them.</p>}
      </div>
    </div>
  );
}
