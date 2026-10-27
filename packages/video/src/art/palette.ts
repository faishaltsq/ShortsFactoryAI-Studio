import type {ThemeSpec} from '../types';
import type {TimeOfDay} from '../scene-data';

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

export interface ArtPalette {
  skyTop: string;
  skyBottom: string;
  ground: string;
  groundFar: string;
  figure: string;
  figureAccent: string;
  prop: string;
  glow: string;
  ink: string;
}

const LIGHT: Record<TimeOfDay, number> = {dawn: 0.5, day: 0.8, dusk: 0.42, night: 0};

/** All art colours are derived from the theme; only black/white are mixed in. */
export const paletteFor = (theme: ThemeSpec, timeOfDay: TimeOfDay = 'night'): ArtPalette => {
  const light = LIGHT[timeOfDay];
  return {
    skyTop: mix(shade(theme.background, 0.35), theme.backgroundAccent, 0.55),
    skyBottom: mix(theme.backgroundAccent, theme.accent, light * 0.55),
    // Ground responds to time of day too: a dusk desert must not read as midnight.
    ground: mix(mix(theme.background, theme.secondary, 0.18), theme.secondary, light * 0.34),
    groundFar: mix(mix(theme.backgroundAccent, theme.secondary, 0.34), theme.accent, light * 0.18),
    figure: theme.primary,
    figureAccent: theme.accent,
    prop: mix(theme.secondary, theme.primary, 0.4),
    glow: alpha(theme.accent, 0.55),
    ink: mix(theme.background, '#000000', 0.45),
  };
};
