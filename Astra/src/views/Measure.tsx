// Log a measurement by hand (blood sugar, blood pressure, temperature, heart rate, SpO₂)
// and get an immediate, explained result. Saved locally and queued like other records.

import { useState } from 'react';
import { GuideCard, metricGuide } from '../components/Explain';
import { Icon, Panel, StatusChip, utcDate, utcTime } from '../components/ui';
import { LIMITS } from '../data/crew';
import { GLUCOSE } from '../data/guide';
import { go } from '../router';
import { useStore } from '../store';
import type { Dashboard, Metric, Status } from '../types';

type Kind = 'glucose' | 'bp' | 'temp' | 'hr' | 'spo2';
type Meal = 'fasting' | 'after-meal' | 'random';

const KINDS: { id: Kind; label: string; unit: string }[] = [
  { id: 'glucose', label: 'Blood sugar', unit: 'mg/dL' },
  { id: 'bp', label: 'Blood pressure', unit: 'mmHg' },
  { id: 'temp', label: 'Body temperature', unit: '°C' },
  { id: 'hr', label: 'Resting heart rate', unit: 'bpm' },
  { id: 'spo2', label: 'Blood oxygen (SpO₂)', unit: '%' },
];

interface Result {
  status: Status;
  headline: string;
  advice: string;
}

function vsBaseline(m: Metric | undefined, v: number, unit: string, d = 0): Result {
  const b = m?.baseline;
  if (!b) return { status: 'normal', headline: `${v.toFixed(d)} ${unit} recorded.`, advice: 'Not enough history yet to compare with your usual range.' };
  const usual = `${b.low.toFixed(d)}–${b.high.toFixed(d)} ${unit}`;
  if (v > b.high) return { status: 'watch', headline: `Above your usual range (${usual}).`, advice: 'Rest for 5 minutes and measure again. If it is still high, log it and keep an eye on it.' };
  if (v < b.low) return { status: 'watch', headline: `Below your usual range (${usual}).`, advice: 'Measure again after resting. If it is still low, log it and keep an eye on it.' };
  return { status: 'normal', headline: `Within your usual range (${usual}).`, advice: 'No action needed.' };
}

function evaluate(kind: Kind, a: number, b: number, meal: Meal, d: Dashboard): Result {
  switch (kind) {
    case 'glucose': {
      if (a < GLUCOSE.lowReview) return { status: 'review', headline: 'Very low blood sugar.', advice: 'Take fast-acting sugar now, recheck in 15 minutes, and contact the crew medical officer.' };
      if (a < GLUCOSE.lowWatch) return { status: 'watch', headline: 'Low blood sugar.', advice: 'Eat or drink something sugary and recheck in 15 minutes.' };
      const fasting = meal === 'fasting';
      const review = fasting ? GLUCOSE.fastingHighReview : GLUCOSE.randomHighReview;
      const watch = fasting ? GLUCOSE.fastingHighWatch : GLUCOSE.randomHighWatch;
      if (a >= review) return { status: 'review', headline: `High blood sugar for a ${fasting ? 'fasting' : 'non-fasting'} reading.`, advice: 'Recheck later today. Tell the crew medical officer if it stays this high.' };
      if (a >= watch) return { status: 'watch', headline: `Slightly high for a ${fasting ? 'fasting' : 'non-fasting'} reading.`, advice: 'Recheck tomorrow under the same conditions.' };
      return { status: 'normal', headline: 'In the typical range.', advice: 'No action needed.' };
    }
    case 'temp':
      if (a >= LIMITS.feverC) return { status: 'review', headline: 'Fever (38.0 °C or higher).', advice: 'Rest, drink fluids, recheck in 4 hours and tell the crew medical officer.' };
      return vsBaseline(d.metrics.bodyTemp, a, '°C', 1);
    case 'spo2':
      if (a <= LIMITS.spo2ReviewPct) return { status: 'review', headline: 'Low blood oxygen.', advice: 'Repeat with a warm finger. If still low or you feel breathless, contact the crew medical officer now.' };
      if (a < LIMITS.spo2WatchPct) return { status: 'watch', headline: 'Blood oxygen below the usual limit.', advice: 'Repeat the reading at rest with a warm finger.' };
      return vsBaseline(d.metrics.spo2, a, '%', 1);
    case 'hr':
      return vsBaseline(d.metrics.restingHr, a, 'bpm');
    case 'bp': {
      const s = vsBaseline(d.metrics.bpSys, a, 'mmHg');
      const di = vsBaseline(d.metrics.bpDia, b, 'mmHg');
      if (s.status === 'normal' && di.status === 'normal') return { status: 'normal', headline: 'Within your usual range.', advice: 'No action needed.' };
      const lower = (t: string) => t.charAt(0).toLowerCase() + t.slice(1);
      const parts = [s.status !== 'normal' && `Top number ${lower(s.headline)}`, di.status !== 'normal' && `Bottom number ${lower(di.headline)}`].filter(Boolean);
      return { status: 'watch', headline: parts.join(' '), advice: 'Sit for 5 minutes, arm at heart level, and measure again.' };
    }
  }
}

const guideFor = (k: Kind) =>
  k === 'glucose' ? GLUCOSE.guide : metricGuide(k === 'bp' ? 'bpSys' : k === 'temp' ? 'bodyTemp' : k === 'hr' ? 'restingHr' : 'spo2');

export function Measure() {
  const { dashboard: d, record, actions } = useStore();
  const [kind, setKind] = useState<Kind>('glucose');
  const [a, setA] = useState('');
  const [b, setB] = useState('');
  const [meal, setMeal] = useState<Meal>('fasting');
  const [result, setResult] = useState<(Result & { text: string }) | null>(null);
  if (!d) return null;
  const k = KINDS.find((x) => x.id === kind)!;
  const va = Number(a);
  const vb = Number(b);
  const valid = a !== '' && va > 0 && (kind !== 'bp' || (b !== '' && vb > 0));
  const logged = actions.filter((x) => x.kind === 'measurement');
  const guide = guideFor(kind);

  return (
    <div className="page narrow">
      <button className="back" onClick={() => go('/checkin')}>
        <Icon name="back" size={16} /> Check-in
      </button>
      <header className="page-head">
        <h1>Log a measurement</h1>
        <p className="lede">Enter a reading you took yourself. Astra checks it straight away and explains what it means.</p>
      </header>

      <Panel title="New measurement" icon="clipboard">
        <form
          className="measure"
          onSubmit={(e) => {
            e.preventDefault();
            if (!valid) return;
            const r = evaluate(kind, va, vb, meal, d);
            const value = kind === 'bp' ? `${va}/${vb}` : `${va}`;
            const text = `${k.label} ${value} ${k.unit}${kind === 'glucose' ? ` (${meal.replace('-', ' ')})` : ''}`;
            record({ kind: 'measurement', note: `${text}: ${r.headline}` });
            setResult({ ...r, text });
            setA('');
            setB('');
          }}
        >
          <fieldset className="pills" aria-label="Measurement">
            {KINDS.map((x) => (
              <button
                type="button"
                key={x.id}
                className={`pill${kind === x.id ? ' on' : ''}`}
                aria-pressed={kind === x.id}
                onClick={() => {
                  setKind(x.id);
                  setResult(null);
                }}
              >
                {x.label}
              </button>
            ))}
          </fieldset>

          <div className="measure-row">
            <label className="field">
              <span>{kind === 'bp' ? 'Top number (systolic)' : k.label}</span>
              <input inputMode="decimal" type="number" step="any" value={a} onChange={(e) => setA(e.target.value)} placeholder={k.unit} required />
            </label>
            {kind === 'bp' && (
              <label className="field">
                <span>Bottom number (diastolic)</span>
                <input inputMode="decimal" type="number" step="any" value={b} onChange={(e) => setB(e.target.value)} placeholder="mmHg" required />
              </label>
            )}
            {kind === 'glucose' && (
              <label className="field">
                <span>When</span>
                <select value={meal} onChange={(e) => setMeal(e.target.value as Meal)}>
                  <option value="fasting">Fasting (no food for 8 h)</option>
                  <option value="after-meal">After a meal</option>
                  <option value="random">Any time</option>
                </select>
              </label>
            )}
          </div>
          <button className="btn btn-primary" type="submit" disabled={!valid}>
            Check and save
          </button>
        </form>

        {result && (
          <div className={`measure-result mr-${result.status}`} role="status">
            <StatusChip status={result.status} />
            <div>
              <strong>{result.text}</strong>
              <p>{result.headline}</p>
              <p className="muted">{result.advice}</p>
            </div>
          </div>
        )}
      </Panel>

      {guide && (
        <Panel title={`About ${k.label.toLowerCase()}`} icon="info">
          <GuideCard guide={guide} />
          {kind === 'glucose' && <p className="note">Blood sugar ranges are general clinical references, not spaceflight-specific. Confirm with your flight surgeon.</p>}
        </Panel>
      )}

      {logged.length > 0 && (
        <Panel title="Your logged measurements" icon="list">
          <ol className="history">
            {logged.slice(0, 10).map((x) => (
              <li key={x.id}>
                <span className="h-time">
                  {utcDate(x.at)} {utcTime(x.at)}
                </span>
                <span>{x.note}</span>
                <span className={`sync ${x.synced ? 'ok' : ''}`}>{x.synced ? 'Sent' : 'Queued'}</span>
              </li>
            ))}
          </ol>
        </Panel>
      )}
    </div>
  );
}
