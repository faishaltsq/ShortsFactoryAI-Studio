/**
 * The object vocabulary, kept free of JSX.
 *
 * `scene-data.ts` needs these lists to validate a storyboard, and the adapter test loads that file
 * through Node's type stripping, which cannot execute `.tsx`. Keeping the vocabulary in a plain
 * module is what lets one file serve the bundler and the test runner alike.
 */

export const OBJECT_KINDS = [
  'gpu',
  'wafer',
  'serverRack',
  'dataCenter',
  'neuralNet',
  'database',
  'satellite',
  'antenna',
  'turbine',
  'solarPanel',
  'coolingFan',
  'phone',
  'drone',
  'rocket',
  'building',
  'meshTopology',
  'claySculpt',
  'cloudArch',
  'cpuProcessor',
  'quantumProcessor',
  'opticalFiber',
  'subseaCableCutaway',
  'ramenBowl',
  'cookingPot',
  'planetEarth',
  'microscope',
  'lightBulb',
  'factory',
  'stockChart',
] as const;
export type ObjectKind = (typeof OBJECT_KINDS)[number];

/** Human-readable name, used for the object's default label and for prompt vocabulary. */
export const OBJECT_LABELS: Record<ObjectKind, string> = {
  gpu: 'GPU',
  wafer: 'Silicon Wafer',
  serverRack: 'Server Rack',
  dataCenter: 'Data Center',
  neuralNet: 'Neural Network',
  database: 'Database',
  satellite: 'Satellite',
  antenna: 'Broadcast Tower',
  turbine: 'Wind Turbine',
  solarPanel: 'Solar Array',
  coolingFan: 'Cooling Fan',
  phone: 'Smartphone',
  drone: 'Drone',
  rocket: 'Rocket',
  building: 'Corporate HQ',
  meshTopology: 'Mesh 3D',
  claySculpt: 'Clay Sculpt',
  cloudArch: 'Cloud Architecture',
  cpuProcessor: 'CPU Processor',
  quantumProcessor: 'Quantum Processor',
  opticalFiber: 'Optical Fiber',
  subseaCableCutaway: 'Kabel Bawah Laut (Cross-Section)',
  ramenBowl: 'Mangkok Mi',
  cookingPot: 'Panci Masak',
  planetEarth: 'Planet Bumi',
  microscope: 'Mikroskop Sains',
  lightBulb: 'Bohlam Inovasi',
  factory: 'Pabrik Industri',
  stockChart: 'Grafik Pasar / Tren',
};
/**
 * Where each object's base sits inside its 400x400 box, 0..1.
 *
 * A caption placed at the bottom of the box floats under a satellite and overlaps the shadow of a
 * rack. These are the measured feet of the drawings in `objects.tsx`, so a label always sits on the
 * object's ground line rather than at a constant offset that happens to be right for one of them.
 */
export const OBJECT_CAPTION_Y: Record<ObjectKind, number> = {
  gpu: 0.92,
  wafer: 0.95,
  serverRack: 0.94,
  dataCenter: 0.83,
  neuralNet: 0.86,
  database: 0.93,
  satellite: 0.66,
  antenna: 0.95,
  turbine: 0.95,
  solarPanel: 0.88,
  coolingFan: 0.9,
  phone: 0.94,
  drone: 0.88,
  rocket: 0.92,
  building: 0.95,
  meshTopology: 0.92,
  claySculpt: 0.94,
  cloudArch: 0.92,
  cpuProcessor: 0.92,
  quantumProcessor: 0.92,
  opticalFiber: 0.92,
  subseaCableCutaway: 0.94,
  ramenBowl: 0.94,
  cookingPot: 0.94,
  planetEarth: 0.94,
  microscope: 0.94,
  lightBulb: 0.94,
  factory: 0.95,
  stockChart: 0.92,
};
export const isObjectKind = (value: unknown): value is ObjectKind =>
  typeof value === 'string' && (OBJECT_KINDS as readonly string[]).includes(value);
