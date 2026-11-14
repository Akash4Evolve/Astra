import { useEffect, useRef, useState, type PointerEvent, type ReactNode } from 'react';
import type { Domain, Status } from '../types';
import type { MarkerHit, Mounted, Statuses } from './three/scenes';
import { statusText } from './ui';

export type MarkerInfo = Partial<Record<Domain, { title: string; detail: string; status: Status }>>;

interface Props {
  model: 'body' | 'station';
  statuses?: Statuses;
  className?: string;
  /** Shown only if the 3D model can't load (no WebGL, or the file failed). */
  fallback?: ReactNode;
  /** Show a loading animation while the model loads. */
  showLoader?: boolean;
  label?: string;
  /** Text for the hover label on each body marker. */
  markerInfo?: MarkerInfo;
  /** Called when a body marker is clicked or tapped. */
  onSelect?: (domain: Domain) => void;
}

/** Loads three.js as the canvas nears the screen; pauses when it scrolls well away. */
export function Model3D({ model, statuses, className, fallback, label, markerInfo, showLoader = false, onSelect }: Props) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const mounted = useRef<Mounted | null>(null);
  const latest = useRef(statuses);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const [tip, setTip] = useState<MarkerHit | null>(null);

  // Hover on desktop, tap on touch screens.
  const probe = (e: PointerEvent<HTMLDivElement>) => {
    const el = canvas.current;
    if (!el || !markerInfo) return;
    const r = el.getBoundingClientRect();
    const hit = mounted.current?.markerAt?.(e.clientX - r.left, e.clientY - r.top) ?? null;
    setTip((t) => (t?.domain === hit?.domain && t?.x === hit?.x ? t : hit));
    return hit;
  };
  const info = tip && markerInfo?.[tip.domain];

  useEffect(() => {
    latest.current = statuses;
    if (statuses) mounted.current?.setStatuses?.(statuses);
  }, [statuses]);

  useEffect(() => {
    const el = canvas.current;
    if (!el) return;
    let cancelled = false;
    let loading = false;
    let visible = false;
    const io = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      mounted.current?.setActive(visible);
      if (!visible || loading) return;
      loading = true;
      import('./three/scenes')
        .then(async (s) => {
          if (cancelled) return;
          const m = model === 'body' ? await s.mountBody(el, latest.current ?? {}) : s.mountStation(el);
          if (cancelled) {
            m.dispose();
            return;
          }
          mounted.current = m;
          m.setStatuses?.(latest.current ?? {});
          m.setActive(visible);
          setReady(true);
        })
        .catch((e: unknown) => {
          // No WebGL or the chunk failed: show the fallback instead.
          console.warn(`3D ${model} model unavailable`, e);
          if (!cancelled) setFailed(true);
        });
    }, { rootMargin: '400px' });
    io.observe(el);
    return () => {
      cancelled = true;
      io.disconnect();
      mounted.current?.dispose();
      mounted.current = null;
    };
  }, [model]);

  return (
    <div
      className={`model3d ${className ?? ''}${tip ? ' pointing' : ''}`}
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      onPointerMove={ready ? probe : undefined}
      onPointerDown={
        ready
          ? (e) => {
              const hit = probe(e);
              if (hit) onSelect?.(hit.domain);
            }
          : undefined
      }
      onPointerLeave={() => setTip(null)}
    >
      {failed && fallback}
      {!ready && !failed && showLoader && (
        <div className="model-loading" role="status">
          <span className="ml-orbit" aria-hidden="true">
            <span className="ml-core" />
          </span>
          <span className="ml-text">Loading 3D model</span>
        </div>
      )}
      <canvas ref={canvas} className={ready ? 'on' : ''} />
      {tip && info && (
        <div className={`marker-tip tip-${info.status}`} style={{ left: tip.x, top: tip.y }}>
          <strong>{info.title}</strong>
          <span className="tip-status">{statusText[info.status]}</span>
          <span className="tip-detail">{info.detail}</span>
        </div>
      )}
    </div>
  );
}
