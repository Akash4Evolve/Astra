import { useEffect, useState } from 'react';
import { Icon, Panel } from '../components/ui';
import { go } from '../router';
import { DRAFT_KEY as DRAFT, nowMs, useStore } from '../store';

const symptomsList = ['Headache', 'Congestion', 'Nausea', 'Back pain', 'Eye strain', 'Dizziness', 'Sore throat', 'Skin irritation'];
const moods = ['Very low', 'Low', 'Okay', 'Good', 'Very good'];

interface Draft {
  mood: number | null;
  stress: number | null;
  fatigue: number | null;
  exertion: number | null;
  sleepQuality: number | null;
  sleepHours: number | null;
  symptoms: string[];
  note: string;
}
const blank: Draft = { mood: null, stress: null, fatigue: null, exertion: null, sleepQuality: null, sleepHours: null, symptoms: [], note: '' };

function loadDraft(): Draft {
  try {
    const raw = localStorage.getItem(DRAFT);
    return raw ? { ...blank, ...(JSON.parse(raw) as Draft) } : blank;
  } catch {
    return blank;
  }
}

function Scale({ label, hint, value, onChange, min, max, ends }: { label: string; hint?: string; value: number | null; onChange: (v: number) => void; min: number; max: number; ends: [string, string] }) {
  const opts = Array.from({ length: max - min + 1 }, (_, i) => i + min);
  return (
    <fieldset className="scale">
      <legend>
        {label}
        {hint && <span className="muted small"> {hint}</span>}
      </legend>
      <div className="scale-row" style={{ gridTemplateColumns: `repeat(${opts.length}, 1fr)` }}>
        {opts.map((n) => (
          <button type="button" key={n} className={value === n ? 'on' : ''} aria-pressed={value === n} onClick={() => onChange(n)}>
            {n}
          </button>
        ))}
      </div>
      <div className="scale-ends">
        <span>{ends[0]}</span>
        <span>{ends[1]}</span>
      </div>
    </fieldset>
  );
}

export function CheckIn() {
  const { submitCheckin, linkUp, checkins } = useStore();
  const [f, setF] = useState<Draft>(loadDraft);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    try {
      localStorage.setItem(DRAFT, JSON.stringify(f));
    } catch {
      /* ignore */
    }
  }, [f]);

  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setF((s) => ({ ...s, [k]: v }));
  const missing = (['mood', 'stress', 'fatigue', 'sleepQuality', 'sleepHours'] as const).filter((k) => f[k] === null);
  const today = new Date(nowMs()).toISOString().slice(0, 10);
  const checkedInToday = checkins.some((c) => c.at.startsWith(today));
  const hasDraft = JSON.stringify(f) !== JSON.stringify(blank);

  if (saved)
    return (
      <div className="page narrow">
        <Panel title="Check-in saved" icon="check">
          <p>
            Saved on this device.{' '}
            {linkUp ? 'It is being sent to the ground now.' : 'It will be sent when the ground link is back.'}
          </p>
          <div className="row-gap">
            <button className="btn btn-primary" onClick={() => go('/overview')}>
              Back to overview
            </button>
            <button className="btn" onClick={() => go('/log')}>
              View log
            </button>
          </div>
        </Panel>
      </div>
    );

  return (
    <div className="page narrow">
      <header className="page-head">
        <h1>Daily check-in</h1>
        <p className="lede">
          About a minute. Your answers sit alongside sensor readings so changes are easier to explain.
          {checkedInToday && ' You have already checked in today; this adds another entry.'}
        </p>
        {hasDraft && <p className="muted small">Draft saved on this device.</p>}
        <p>
          <button type="button" className="link" onClick={() => go('/measure')}>
            Took a reading yourself? Log a measurement, such as blood sugar or blood pressure →
          </button>
        </p>
      </header>

      <form
        className="checkin"
        onSubmit={(e) => {
          e.preventDefault();
          if (missing.length) return;
          submitCheckin({
            mood: f.mood!,
            stress: f.stress!,
            fatigue: f.fatigue!,
            exertion: f.exertion ?? 0,
            sleepQuality: f.sleepQuality!,
            sleepHours: f.sleepHours!,
            symptoms: f.symptoms,
            note: f.note,
          });
          try {
            localStorage.removeItem(DRAFT);
          } catch {
            /* ignore */
          }
          setSaved(true);
        }}
      >
        <fieldset className="scale">
          <legend>How is your mood?</legend>
          <div className="scale-row moods">
            {moods.map((m, i) => (
              <button type="button" key={m} className={f.mood === i + 1 ? 'on' : ''} aria-pressed={f.mood === i + 1} onClick={() => set('mood', i + 1)}>
                <span className="num">{i + 1}</span>
                <span className="small">{m}</span>
              </button>
            ))}
          </div>
        </fieldset>
        <Scale label="Stress" value={f.stress} onChange={(v) => set('stress', v)} min={0} max={10} ends={['None', 'Extreme']} />
        <Scale label="Fatigue" value={f.fatigue} onChange={(v) => set('fatigue', v)} min={0} max={10} ends={['Fully rested', 'Exhausted']} />
        <label className="field">
          <span>Hours slept last night</span>
          <input
            type="number"
            inputMode="decimal"
            min={0}
            max={24}
            step={0.25}
            value={f.sleepHours ?? ''}
            onChange={(e) => {
              const v = e.target.value === '' ? null : Number(e.target.value);
              set('sleepHours', v === null || Number.isNaN(v) ? null : Math.min(24, Math.max(0, v)));
            }}
          />
        </label>
        <Scale label="Sleep quality last night" value={f.sleepQuality} onChange={(v) => set('sleepQuality', v)} min={1} max={5} ends={['Very poor', 'Very good']} />
        <Scale label="Effort of today’s exercise" hint="(Borg CR10, optional)" value={f.exertion} onChange={(v) => set('exertion', v)} min={0} max={10} ends={['Rest', 'Maximal']} />

        <fieldset className="scale">
          <legend>Any symptoms?</legend>
          <div className="pills">
            {symptomsList.map((s) => {
              const on = f.symptoms.includes(s);
              return (
                <button
                  type="button"
                  key={s}
                  className={`pill${on ? ' on' : ''}`}
                  aria-pressed={on}
                  onClick={() => set('symptoms', on ? f.symptoms.filter((x) => x !== s) : [...f.symptoms, s])}
                >
                  {on && <Icon name="check" size={14} />}
                  {s}
                </button>
              );
            })}
          </div>
        </fieldset>

        <label className="field">
          <span>Anything else? (optional)</span>
          <textarea rows={3} value={f.note} onChange={(e) => set('note', e.target.value)} />
        </label>

        <div className="form-foot">
          {missing.length > 0 && <p className="muted small">Answer mood, stress, fatigue, hours slept and sleep quality to save.</p>}
          <button className="btn btn-primary" type="submit" disabled={missing.length > 0}>
            Save check-in
          </button>
        </div>
      </form>
    </div>
  );
}
