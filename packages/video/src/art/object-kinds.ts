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
};

export const isObjectKind = (value: unknown): value is ObjectKind =>
  typeof value === 'string' && (OBJECT_KINDS as readonly string[]).includes(value);
