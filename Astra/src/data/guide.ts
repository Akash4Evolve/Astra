// Plain-language explanations shown to the crew: what each body system does, how
// spaceflight affects it, and what each reading means. Written from NASA's Human
// Research Program pages listed in the challenge resources. This is guidance for a
// prototype, not medical advice: real steps must come from approved onboard procedures.

import type { Domain, Hazard, MetricId } from '../types';

export interface Source {
  label: string;
  url: string;
}

const HAZARDS: Source = { label: 'NASA HRP: 5 Hazards of Human Spaceflight', url: 'https://www.nasa.gov/hrp/hazards/' };
const RISKS: Source = { label: 'NASA HRP: Risks of Human Spaceflight', url: 'https://www.nasa.gov/hrp/risks/' };
const CSA_RAD: Source = {
  label: 'CSA: Monitoring Radiation for Astronaut Health',
  url: 'https://www.asc-csa.gc.ca/eng/news/articles/2026/2026-02-26-monitoring-radiation-astronaut-health.asp',
};
const ADA: Source = { label: 'American Diabetes Association: Standards of Care (glucose ranges)', url: 'https://diabetesjournals.org/care/issue/48/Supplement_1' };

export interface SystemGuide {
  function: string;
  inSpace: string;
  hazards: Hazard[];
  selfCare: string[];
  sources: Source[];
}

export const SYSTEMS: Record<Domain, SystemGuide> = {
  cardiovascular: {
    function: 'Your heart and blood vessels move oxygen and nutrients around the body and keep blood pressure steady when you change position.',
    inSpace:
      'Without gravity, blood and body fluids shift towards the head, and the heart and blood vessels adapt to the lighter load. NASA lists cardiovascular adaptation as a spaceflight risk, as it can raise the chance of cardiovascular events and of feeling faint when gravity returns.',
    hazards: ['gravity', 'hostile'],
    selfCare: ['Keep up your scheduled aerobic and resistance exercise', 'Drink enough fluids', 'Take resting readings at the same time and in the same position each day'],
    sources: [RISKS],
  },
  'sleep-behaviour': {
    function: 'Sleep restores body and brain. Mood, stress and reaction speed show how well you are coping with workload and living conditions.',
    inSpace:
      'Isolation, confinement, constant work demands and an irregular day–night cycle disturb sleep and the body clock. NASA lists inadequate sleep, irregular schedules and behavioural changes as spaceflight risks, and they feed into each other.',
    hazards: ['isolation', 'distance'],
    selfCare: ['Follow your sleep protocol: lights, noise and a regular sleep window', 'Raise workload or team tensions at your private conference with the flight surgeon', 'Keep in touch with family and friends during scheduled calls'],
    sources: [HAZARDS, RISKS],
  },
  musculoskeletal: {
    function: 'Bones and muscles carry your weight, protect organs and let you move and work, including on spacewalks.',
    inSpace:
      'Without gravity, bones break down and become more brittle, raising the chance of painful breaks, and muscles weaken. Daily exercise, diet and sometimes medication are used to slow these losses.',
    hazards: ['gravity'],
    selfCare: ['Complete your daily exercise, including resistance training', 'Eat your full meal plan, including calcium and vitamin D', 'Report any new joint or back pain'],
    sources: [RISKS],
  },
  'immune-symptoms': {
    function: 'Your immune system fights infection. Body temperature and symptoms such as headache are early signs that something is wrong.',
    inSpace:
      'The stresses of spaceflight can change immune responses and wake up dormant viruses, which can cause rashes and other symptoms. Microbes on the skin and in the gut also change, and in a closed cabin an illness can spread to the crew.',
    hazards: ['hostile', 'isolation'],
    selfCare: ['Record symptoms in your daily check-in, even mild ones', 'Wash hands and follow cabin hygiene routines', 'Rest and drink fluids when you feel unwell'],
    sources: [RISKS],
  },
  radiation: {
    function: 'This tracks how much space radiation your body has absorbed, today and over the mission.',
    inSpace:
      'Space radiation is invisible and is one of the most hazardous parts of spaceflight. Exposure builds up over a career and raises the long-term risk of cancer. Solar particle events can deliver a large dose in hours, so crews move to a shielded area when warned.',
    hazards: ['radiation'],
    selfCare: ['Wear your personal dosimeter', 'Go to the radiation shelter promptly when told', 'Log time spent in the shelter'],
    sources: [HAZARDS, RISKS, CSA_RAD],
  },
  environment: {
    function: 'The cabin is your life-support environment: the air you breathe, temperature and noise.',
    inSpace:
      'A spacecraft is both home and machine. NASA lists temperature, pressure, lighting, noise and microbes as habitability factors. Raised carbon dioxide is linked to headaches, poorer sleep and slower thinking.',
    hazards: ['hostile'],
    selfCare: ['Report CO₂ or temperature readings outside limits to mission control', 'Rest in a well-ventilated module when CO₂ is raised', 'Use hearing protection in noisy areas'],
    sources: [HAZARDS],
  },
};

export interface MetricGuide {
  what: string;
  howToMeasure: string;
  whyInSpace: string;
  getHelp: string;
  sources: Source[];
}

export const METRICS: Partial<Record<MetricId, MetricGuide>> = {
  restingHr: {
    what: 'How many times your heart beats per minute when you are fully at rest.',
    howToMeasure: 'Sit or lie still for 5 minutes after waking, before exercise or caffeine, then take the reading.',
    whyInSpace: 'Fluid shifts and loss of fitness change how hard the heart works. A rise over several days can also be an early sign of illness, poor sleep or stress.',
    getHelp: 'Tell the crew medical officer if it stays above your usual range for several days, or straight away with chest pain, dizziness or breathlessness.',
    sources: [RISKS],
  },
  hrv: {
    what: 'Heart rate variability: the small changes in time between heartbeats. Higher usually means better recovery.',
    howToMeasure: 'Measured overnight or in a short morning reading, lying still.',
    whyInSpace: 'HRV drops with stress, poor sleep and illness, so it is a useful early warning alongside sleep and mood.',
    getHelp: 'Look at it together with sleep and symptoms. Tell the crew medical officer if it stays low for several days.',
    sources: [RISKS],
  },
  bpSys: {
    what: 'Blood pressure: the force of blood against artery walls. The top number is when the heart beats, the bottom when it rests.',
    howToMeasure: 'Seated, arm at heart level, after 5 minutes of rest, using the onboard cuff.',
    whyInSpace: 'Weightlessness changes how the heart and blood vessels work, and blood pressure control is tested when gravity returns.',
    getHelp: 'Tell the crew medical officer about readings well outside your usual range, or with headache, vision changes or fainting.',
    sources: [RISKS],
  },
  spo2: {
    what: 'Blood oxygen saturation: how much of your blood’s capacity to carry oxygen is in use.',
    howToMeasure: 'Clip the pulse oximeter to a warm finger and keep still for 30 seconds.',
    whyInSpace: 'Cabin air problems and spacewalk procedures can lower oxygen levels (NASA lists hypoxia as a risk). Illness can lower it too.',
    getHelp: 'Normal is about 95–100%. Repeat the reading. If it is 92% or lower, or you feel short of breath, contact the crew medical officer straight away.',
    sources: [RISKS],
  },
  bodyTemp: {
    what: 'Your core body temperature.',
    howToMeasure: 'Use the onboard thermometer at the same time each morning.',
    whyInSpace: 'Core temperature runs slightly higher in microgravity, so Astra compares it with your own usual range. A fever (38.0 °C or higher) can mean infection, which matters in a shared, closed cabin.',
    getHelp: 'Tell the crew medical officer about a fever of 38.0 °C or higher, especially with a raised heart rate, low oxygen or feeling unwell.',
    sources: [RISKS],
  },
  respRate: {
    what: 'How many breaths you take per minute at rest.',
    howToMeasure: 'Count breaths for 1 minute while resting, or read it from the vitals monitor.',
    whyInSpace: 'It rises with illness, raised cabin CO₂ and low oxygen.',
    getHelp: 'Tell the crew medical officer if it is raised and you feel breathless.',
    sources: [RISKS],
  },
  sleep: {
    what: 'How many hours you slept last night.',
    howToMeasure: 'Recorded automatically by your wrist sensor (actigraphy).',
    whyInSpace: 'NASA lists chronic sleep loss and irregular schedules as a spaceflight risk. Short sleep slows reactions and affects mood and health.',
    getHelp: 'Raise ongoing short sleep with the flight surgeon at your private conference.',
    sources: [RISKS],
  },
  sleepQuality: {
    what: 'How rested you felt, rated by you from 1 to 10.',
    howToMeasure: 'Answered in your daily check-in.',
    whyInSpace: 'How you feel can differ from hours slept, and both matter.',
    getHelp: 'Raise ongoing poor sleep quality with the flight surgeon.',
    sources: [RISKS],
  },
  mood: {
    what: 'How you feel overall today, from 1 (very low) to 5 (very good).',
    howToMeasure: 'Answered in your daily check-in.',
    whyInSpace: 'Isolation, confinement and distance from Earth can take a toll on mental health. Tracking mood helps spot changes early.',
    getHelp: 'Talk to the flight surgeon or a crewmate if low mood lasts several days.',
    sources: [HAZARDS, RISKS],
  },
  stress: {
    what: 'How stressed you feel today, from 0 to 10.',
    howToMeasure: 'Answered in your daily check-in.',
    whyInSpace: 'Constant work demands, isolation and events such as equipment faults raise stress, which affects sleep, HRV and performance.',
    getHelp: 'Raise ongoing high stress or workload with the flight surgeon.',
    sources: [RISKS],
  },
  reactionTime: {
    what: 'How fast you react on a 3-minute attention test (PVT).',
    howToMeasure: 'Take the test at the same time each day.',
    whyInSpace: 'Reactions slow with sleep loss, fatigue and raised CO₂, which matters for safety-critical tasks.',
    getHelp: 'Avoid safety-critical tasks and tell the commander if your reactions are much slower than usual.',
    sources: [RISKS],
  },
  headache: {
    what: 'Days on which you reported a headache.',
    howToMeasure: 'Recorded in your daily check-in.',
    whyInSpace: 'Headaches in space are linked to fluid shifts and raised cabin CO₂, and can come with illness.',
    getHelp: 'Tell the crew medical officer about a sudden or severe headache, or one with vision changes or confusion.',
    sources: [HAZARDS],
  },
  bodyMass: {
    what: 'Your body mass, measured on the onboard mass device.',
    howToMeasure: 'Measured at the same time of day, before eating.',
    whyInSpace: 'Weight loss can mean you are not eating enough. NASA lists inadequate food and nutrition as a risk.',
    getHelp: 'Raise steady weight loss with the flight surgeon and nutrition team.',
    sources: [RISKS],
  },
  boneLoss: {
    what: 'Estimated loss of hip bone density since launch. Modelled, not measured: bone scans need equipment not carried onboard.',
    howToMeasure: 'Estimated from time in flight. Measured with a scan before and after the mission.',
    whyInSpace: 'Without gravity, bones break down and become brittle, raising the risk of fractures later.',
    getHelp: 'Keep up exercise and nutrition. The flight surgeon reviews bone health.',
    sources: [RISKS],
  },
  grip: {
    what: 'Grip strength compared with your preflight test.',
    howToMeasure: 'Squeeze the hand dynamometer three times and take the best.',
    whyInSpace: 'A simple sign of overall muscle strength, which falls in weightlessness.',
    getHelp: 'Raise a steady drop with the flight surgeon so exercise can be adjusted.',
    sources: [RISKS],
  },
  exercise: {
    what: 'Minutes of exercise completed today.',
    howToMeasure: 'Logged by the exercise equipment.',
    whyInSpace: 'Daily exercise is the main way astronauts protect bone, muscle and heart fitness. It is skipped on spacewalk days.',
    getHelp: 'Tell the crew medical officer if pain or illness stops you exercising.',
    sources: [RISKS],
  },
  radiation: {
    what: 'The radiation dose you absorbed today, in millisieverts (mSv).',
    howToMeasure: 'Recorded by your personal and cabin dosimeters.',
    whyInSpace:
      'Space radiation is one of the most hazardous parts of spaceflight. NASA limits a career dose to under 600 mSv and a solar particle event to under 250 mSv (NASA-STD-3001 Vol. 1 Rev B). A sudden spike usually means a solar particle event.',
    getHelp: 'Follow mission control’s instructions during a solar particle event, and report nausea or unusual fatigue.',
    sources: [HAZARDS, CSA_RAD, { label: 'NASA-STD-3001 Vol. 1 Rev B', url: 'https://www.nasa.gov/wp-content/uploads/2020/10/2022-01-05_nasa-std-3001_vol.1_rev._b_final_draft_with_signature_010522.pdf' }],
  },
  co2: {
    what: 'The level of carbon dioxide in the cabin air.',
    howToMeasure: 'Measured continuously by the cabin sensors.',
    whyInSpace:
      'CO₂ can build up in a closed cabin. NASA’s standard limits the 1-hour average to 3 mmHg. NASA’s CO₂ brief reports headaches at 2.8–4.5 mmHg, and fatigue, poorer sleep and nausea above 4.5 mmHg.',
    getHelp: 'Report readings above 3 mmHg to mission control, and tell the crew medical officer about headaches or confusion.',
    sources: [HAZARDS, { label: 'NASA OCHMO CO₂ technical brief', url: 'https://www.nasa.gov/wp-content/uploads/2023/12/ochmo-tb-004-carbon-dioxide.pdf' }],
  },
  cabinTemp: {
    what: 'Air temperature in the cabin.',
    howToMeasure: 'Measured continuously by the cabin sensors.',
    whyInSpace: 'Temperature is a key habitability factor. Too warm affects sleep and comfort.',
    getHelp: 'Report readings outside the normal range to mission control.',
    sources: [HAZARDS],
  },
  cabinNoise: {
    what: 'Background noise level in the cabin.',
    howToMeasure: 'Measured by cabin sound monitors.',
    whyInSpace: 'Constant fan and equipment noise can affect sleep and, over time, hearing.',
    getHelp: 'Use hearing protection and report persistent high noise.',
    sources: [HAZARDS],
  },
};

/** Blood glucose bands in mg/dL. General clinical reference ranges, not spaceflight-specific: confirm with the flight surgeon. */
export const GLUCOSE = {
  lowReview: 54,
  lowWatch: 70,
  fastingHighWatch: 100,
  fastingHighReview: 126,
  randomHighWatch: 140,
  randomHighReview: 200,
  guide: {
    what: 'Blood sugar (glucose): the amount of sugar in your blood, your body’s main fuel, in mg/dL.',
    howToMeasure: 'Prick a finger with the onboard glucose meter. Note whether you have eaten in the last 8 hours.',
    whyInSpace: 'Diet, stress hormones and inactivity can affect how the body handles sugar, and NASA lists inadequate nutrition as a spaceflight risk. Low blood sugar can cause shakiness, confusion and fainting.',
    getHelp: 'If it is low, eat or drink something sugary and recheck in 15 minutes. Tell the crew medical officer about very low or very high readings.',
    sources: [RISKS, ADA],
  } satisfies MetricGuide,
};

export const ALL_SOURCES = [HAZARDS, RISKS, CSA_RAD, ADA];
