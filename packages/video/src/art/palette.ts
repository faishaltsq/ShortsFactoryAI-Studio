import type {ThemeTokens} from '../themes/tokens';
import {DEFAULT_TOKENS} from '../themes/tokens';

export interface ThemeSpec {
  id?: string;
  background: string;
  backgroundAccent: string;
  primary: string;
  secondary: string;
  accent: string;
  fontHeading?: string;
  fontBody?: string;
  fontTechnical?: string;
  tokens?: ThemeTokens;
}

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

export const isLight = (hex: string): boolean => {
  try {
    const [r, g, b] = parse(hex);
    return 0.299 * r + 0.587 * g + 0.114 * b > 135;
  } catch {
    return false;
  }
};
/**
 * The colour vocabulary of the informative engine.
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

export const DEFAULT_PALETTE: ArtPalette = {
  skyTop: '#FAF7F2',
  skyBottom: '#F3EFEA',
  ground: '#E6DFD5',
  groundFar: '#EDE6DC',
  primary: '#241C15',
  accent: '#D97757',
  prop: '#5C5248',
  glow: 'rgba(217, 119, 87, 0.22)',
  ink: '#241C15',
};

/**
 * Backdrops an informative scene can stand an object in. Each is a rendering recipe, not a photo:
 * the scene names one and gets a consistent place, so two scenes about the same subject from
 * different scenes still look like one film.
 */
export const ENVIRONMENTS = [
  'dataCenter',
  'circuit',
  'space',
  'lab',
  'city',
  'grid',
  'abstract',
  'oceanFloor',
  'kitchen',
] as const;
export type EnvironmentKind = (typeof ENVIRONMENTS)[number];

const ENV_LIGHT: Record<EnvironmentKind, number> = {
  dataCenter: 0.18,
  circuit: 0.34,
  space: 0,
  lab: 0.7,
  city: 0.5,
  grid: 0.45,
  abstract: 0.6,
  oceanFloor: 0.25,
  kitchen: 0.8,
};
/** All art colours are derived from the theme; only black/white are mixed in. */
export const paletteFor = (theme: ThemeSpec, environment: EnvironmentKind = 'abstract'): ArtPalette => {
  const light = ENV_LIGHT[environment] ?? 0.5;
  const bg = theme.background || theme.tokens?.background || DEFAULT_TOKENS.background;
  const lightTheme = isLight(bg);

  if (theme.tokens) {
    const t = theme.tokens;
    if (lightTheme) {
      return {
        skyTop: t.background,
        skyBottom: t.surface,
        ground: mix(t.surface, t.line, 0.35 + light * 0.3),
        groundFar: mix(t.surface, t.background, 0.4),
        primary: t.textPrimary,
        accent: t.accent,
        prop: t.textSecondary,
        glow: alpha(t.accent, 0.22),
        ink: t.textPrimary,
      };
    }
    return {
      skyTop: t.background,
      skyBottom: t.surface,
      ground: mix(t.surface, t.line, 0.4 + light * 0.2),
      groundFar: mix(t.surface, t.background, 0.5),
      primary: t.textPrimary,
      accent: t.accent,
      prop: t.textSecondary,
      glow: alpha(t.accent, 0.38),
      ink: t.textPrimary,
    };
  }

  // Fallback when tokens not provided on theme
  const t = DEFAULT_TOKENS;
  if (lightTheme) {
    return {
      skyTop: theme.background || t.background,
      skyBottom: theme.backgroundAccent || t.surface,
      ground: mix(theme.backgroundAccent || t.surface, theme.secondary || t.line, 0.35 + light * 0.3),
      groundFar: mix(theme.backgroundAccent || t.surface, theme.background || t.background, 0.4),
      primary: theme.primary || t.textPrimary,
      accent: theme.accent || t.accent,
      prop: theme.secondary || t.textSecondary,
      glow: alpha(theme.accent || t.accent, 0.22),
      ink: theme.primary || t.textPrimary,
    };
  }

  return {
    skyTop: theme.background,
    skyBottom: theme.backgroundAccent,
    ground: mix(theme.backgroundAccent, theme.secondary, 0.4 + light * 0.2),
    groundFar: mix(theme.backgroundAccent, theme.background, 0.5),
    primary: theme.primary,
    accent: theme.accent,
    prop: theme.secondary,
    glow: alpha(theme.accent, 0.38),
    ink: theme.primary,
  };
};
