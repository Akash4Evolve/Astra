// Shared types. These mirror the /api/v1 contract the backend will serve.
// Freeze these with the backend team before parallel development.

export type Status = 'normal' | 'watch' | 'review';

/** Where a reading came from. Every value on screen shows one of these. */
export type Provenance = 'sensor' | 'self-report' | 'simulated';

export type Quality = 'good' | 'degraded' | 'missing';

export type Domain =
  | 'cardiovascular'
  | 'sleep-behaviour'
  | 'musculoskeletal'
  | 'immune-symptoms'
  | 'radiation'
  | 'environment';

/** NASA Human Research Program's five hazards of human spaceflight. */
export type Hazard = 'radiation' | 'isolation' | 'distance' | 'gravity' | 'hostile';

export type MetricId =
  | 'restingHr'
  | 'hrv'
  | 'bpSys'
  | 'bpDia'
  | 'spo2'
  | 'bodyTemp'
  | 'respRate'
  | 'sleep'
  | 'sleepQuality'
  | 'mood'
  | 'stress'
  | 'reactionTime'
  | 'headache'
  | 'bodyMass'
  | 'boneLoss'
  | 'grip'
  | 'exercise'
  | 'radiation'
  | 'co2'
  | 'cabinTemp'
  | 'cabinNoise';

export interface Point {
  t: string; // ISO timestamp
  v: number | null; // null = no reading (sensor dropout)
}

export interface Baseline {
  mean: number;
  low: number;
  high: number;
  windowDays: number;
  method: string; // e.g. "21-day mean ± 2 SD"
}

export interface Metric {
  id: MetricId;
  label: string;
  unit: string;
  domain: Domain;
  hazard?: Hazard;
  decimals: number;
  latest: number | null;
  latestAt: string;
  status: Status;
  provenance: Provenance;
  quality: Quality;
  qualityNote?: string;
  baseline: Baseline | null;
  daily: Point[]; // one value per day, oldest first
  hourly?: Point[]; // sensor metrics only
}

export type AlertState = 'open' | 'acknowledged' | 'action-logged' | 'recheck-scheduled' | 'escalated' | 'resolved';

export interface AlertEvidence {
  metricId: MetricId;
  observed: string; // "61 bpm (4-day mean)"
  baseline: string; // "52–57 bpm"
  change: string; // "+7 bpm, +13%"
}

export interface Alert {
  id: string;
  title: string;
  status: Exclude<Status, 'normal'>;
  domain: Domain;
  hazard?: Hazard;
  createdAt: string;
  state: AlertState;
  summary: string;
  trigger: string;
  window: string;
  evidence: AlertEvidence[];
  context: string[]; // related signals, shown as association not cause
  dataQuality: string;
  confidence: 'low' | 'medium' | 'high';
  /** Steps ending in "(general guidance)" are the app's own suggestions; the rest follow `guidanceSources`. */
  nextSteps: string[];
  guidanceSources?: { label: string; url: string }[];
  escalateWhen: string;
  provenance: Provenance;
  /**
   * Set on a backend alert whose readings ended before the day shown: the time of its last
   * reading. It stays listed until acknowledged but no longer sets today's status.
   */
  endedAt?: string;
}

export type ActionKind = 'acknowledge' | 'action' | 'recheck' | 'escalate' | 'checkin' | 'measurement';

export interface ActionRecord {
  id: string;
  alertId?: string;
  kind: ActionKind;
  note: string;
  at: string;
  recheckAt?: string;
  escalateTo?: 'crew-medical-officer' | 'mission-control';
  /** Crew member the record belongs to (needed by the backend). */
  crewId?: string;
  synced: boolean;
}

export interface CheckIn {
  id: string;
  at: string;
  mood: number; // 1–5
  stress: number; // 0–10
  fatigue: number; // 0–10
  exertion: number; // Borg CR10, 0–10
  sleepQuality: number; // 1–5
  /** Hours slept last night. Older records may lack it. */
  sleepHours?: number;
  symptoms: string[];
  note: string;
  crewId?: string;
  synced: boolean;
}

export interface CrewProfile {
  id: string;
  displayName: string;
  role: string;
  missionName: string;
  missionDay: number;
  missionLength: number;
  isDemo: boolean;
}

export interface Dashboard {
  generatedAt: string;
  profile: CrewProfile;
  metrics: Record<MetricId, Metric>;
  alerts: Alert[];
  /** Mission total absorbed dose, if the source reports it. */
  cumulativeDoseMsv?: number;
  schedule: { at: string; label: string; detail: string; done: boolean }[];
}
