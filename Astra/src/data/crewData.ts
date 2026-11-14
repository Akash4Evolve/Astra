// The simulated crew dataset, bundled with the app so it works offline.
import csv from './astronaut_health_simulated.csv?raw';
import { buildCrewDashboard, crewList, missionHistory, parseCrewCsv } from './crew';

export const CREW_ROWS = parseCrewCsv(csv);
export const CREW = crewList(CREW_ROWS);

/** Shortcuts to the planted events, for demos. The alert rules don't use these. */
export const SCENARIOS = [
  { label: 'Solar particle event (whole crew)', crewId: 'CDR-01', day: 62 },
  { label: 'CO₂ scrubber fault', crewId: 'MS-03', day: 97 },
  { label: 'Sleep disruption', crewId: 'MS-03', day: 125 },
  { label: 'Mild infection in the crew medical officer', crewId: 'FE-02', day: 143 },
  { label: 'EVA day (no alert expected)', crewId: 'CDR-01', day: 110 },
];

/** Alert status of every mission day for one crew member (see `missionHistory`). */
export const crewHistory = (crewId: string) => missionHistory(CREW_ROWS, crewId);

/** Every crew member's dashboard for the same mission day, for the crew view. */
export const crewDashboards = (day: number) => CREW.map((c) => buildCrewDashboard(CREW_ROWS, c.id, day));
