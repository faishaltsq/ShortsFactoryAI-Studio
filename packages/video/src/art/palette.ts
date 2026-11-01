import type {ThemeSpec} from '../types';

const clamp = (value: number, low = 0, high = 1): number => Math.min(high, Math.max(low, value));

const parse = (hex: string): [number, number, number] => {
  const raw = hex.replace('#', '');
  const full = raw.length === 3 ? raw.split('').map((c) => c + c).join('') : raw.padEnd(6, '0').slice(0, 6);
  const value = Number.parseInt(full, 16);
  if (!Number.isFinite(value)) throw new Error(`Invalid theme colour: ${hex}`);
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
};

const toHex = (rgb: [number, number, number]): string =>
  '#' + rgb.map((v) => Math.round(clamp(v, 0, 255)).toString(16).padStart(2, '0')).join('');

export const mix = (a: string, b: string, t: number): string => {
  const [r1, g1, b1] = parse(a);
  const [r2, g2, b2] = parse(b);
  const k = clamp(t);
  return toHex([r1 + (r2 - r1) * k, g1 + (g2 - g1) * k, b1 + (b2 - b1) * k]);
};

export const alpha = (hex: string, a: number): string => {
  const [r, g, b] = parse(hex);
  return `rgba(${r}, ${g}, ${b}, ${clamp(a)})`;
};

export const shade = (hex: string, amount: number): string => mix(hex, '#000000', amount);
export const tint = (hex: string, amount: number): string => mix(hex, '#ffffff', amount);

/**
 * The colour vocabulary of the informative engine.
 *
 * `primary` and `accent` are the two object tones (a rack's chassis and its LEDs, a chip's
 * substrate and its die). `prop` is the third tone for supporting geometry — cable trays, struts,
 * lattice. There is deliberately no figure/character tone: nothing in this engine is a person.
 */
export interface ArtPalette {
  skyTop: string;
  skyBottom: string;
  ground: string;
  groundFar: string;
  primary: string;
  accent: string;
  prop: string;
  glow: string;
  ink: string;
}

/**
 * Backdrops an informative scene can stand an object in. Each is a rendering recipe, not a photo:
 * the scene names one and gets a consistent place, so two scenes about the same subject from
 * different scenes still look like one film.
 */
export const ENVIRONMENTS = ['dataCenter', 'circuit', 'space', 'lab', 'city', 'grid', 'abstract'] as const;
export type EnvironmentKind = (typeof ENVIRONMENTS)[number];

const ENV_LIGHT: Record<EnvironmentKind, number> = {
  dataCenter: 0.18,
  circuit: 0.34,
  space: 0,
  lab: 0.7,
  city: 0.5,
  grid: 0.45,
  abstract: 0.6,
};

/** All art colours are derived from the theme; only black/white are mixed in. */
export const paletteFor = (theme: ThemeSpec, environment: EnvironmentKind = 'abstract'): ArtPalette => {
  const light = ENV_LIGHT[environment];
  return {
    skyTop: mix(shade(theme.background, 0.4), theme.backgroundAccent, 0.5),
    skyBottom: mix(theme.backgroundAccent, theme.accent, light * 0.5),
    // Ground responds to the environment: a lab floor must not read as deep space.
    ground: mix(mix(theme.background, theme.secondary, 0.18), theme.secondary, light * 0.3),
    groundFar: mix(mix(theme.backgroundAccent, theme.secondary, 0.34), theme.accent, light * 0.16),
    primary: theme.primary,
    accent: theme.accent,
    prop: mix(theme.secondary, theme.primary, 0.4),
    glow: alpha(theme.accent, 0.55),
    ink: mix(theme.background, '#000000', 0.45),
  };
};
