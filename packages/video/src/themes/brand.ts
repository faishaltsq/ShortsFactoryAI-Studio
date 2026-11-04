import type {ThemeSpec} from '../types';
import type {ThemeTokens} from './tokens';
import {DEFAULT_TOKENS, ENERGY_TOKENS, SCIENCE_TOKENS, INFRASTRUCTURE_TOKENS} from './tokens';
import {FONT_ROLES} from './type';

/**
 * Builds a dark token set that keeps the warm editorial brand shell.
 * ponytail: dark themes are the exception, not the default; light is the global base.
 */
const darkTokens = (shell: {
  id: string;
  name: string;
  background: string;
  surface: string;
  elevatedSurface: string;
  textPrimary: string;
  textSecondary: string;
  textMuted: string;
  line: string;
  accent: string;
  accentDeep: string;
  accentSoft: string;
  highlight: string;
}): ThemeTokens => ({
  ...shell,
  chartColors: ['#E0975F', '#7FA89B', '#D9A85C', '#7C9BB5', '#B5839F', '#9AA38A'],
  status: {success: '#6FAE8B', warning: '#D9A85C', error: '#D97368'},
  shadow: {
    sm: '0 2px 8px rgba(0, 0, 0, 0.24)',
    md: '0 8px 24px rgba(0, 0, 0, 0.32)',
    lg: '0 20px 48px rgba(0, 0, 0, 0.40)',
    float: '0 28px 64px rgba(0, 0, 0, 0.48), 0 4px 12px rgba(0, 0, 0, 0.28)',
  },
});

export const THEMES: Record<string, ThemeSpec> = {
  // Light mode is the global default: warm parchment, espresso ink, terracotta accent.
  editorialLight: {
    id: 'editorialLight',
    background: '#FAF7F2',
    backgroundAccent: '#F3EFEA',
    primary: '#241C15',
    secondary: '#5C5248',
    accent: '#D97757',
    fontHeading: FONT_ROLES.display,
    fontBody: FONT_ROLES.body,
    fontTechnical: FONT_ROLES.technical,
    tokens: DEFAULT_TOKENS,
  },
  warmLifestyle: {
    id: 'warmLifestyle',
    background: '#FAF4EA',
    backgroundAccent: '#F3E7D8',
    primary: '#241C15',
    secondary: '#5C5248',
    accent: '#D46B38',
    fontHeading: FONT_ROLES.display,
    fontBody: FONT_ROLES.body,
    fontTechnical: FONT_ROLES.technical,
    tokens: ENERGY_TOKENS,
  },
  // Dark themes: justified exceptions (space/night/mood content), same warm shell.
  spaceDark: {
    id: 'spaceDark',
    background: '#171B22',
    backgroundAccent: '#222833',
    primary: '#F5F1EA',
    secondary: '#B8AFA2',
    accent: '#E0975F',
    fontHeading: FONT_ROLES.display,
    fontBody: FONT_ROLES.body,
    fontTechnical: FONT_ROLES.technical,
    tokens: darkTokens({
      id: 'space-dark', name: 'Space Dark',
      background: '#171B22', surface: '#222833', elevatedSurface: '#2A313D',
      textPrimary: '#F5F1EA', textSecondary: '#B8AFA2', textMuted: '#8A8175',
      line: '#333A45', accent: '#E0975F', accentDeep: '#C97E48',
      accentSoft: '#3A2E24', highlight: 'rgba(224, 151, 95, 0.16)',
    }),
  },
  midnight: {
    id: 'midnight',
    background: '#12100E',
    backgroundAccent: '#1E1A16',
    primary: '#F7F2EA',
    secondary: '#B5AA9C',
    accent: '#E8925A',
    fontHeading: FONT_ROLES.display,
    fontBody: FONT_ROLES.body,
    fontTechnical: FONT_ROLES.technical,
    tokens: darkTokens({
      id: 'midnight', name: 'Midnight',
      background: '#12100E', surface: '#1E1A16', elevatedSurface: '#272119',
      textPrimary: '#F7F2EA', textSecondary: '#B5AA9C', textMuted: '#877D70',
      line: '#332C24', accent: '#E8925A', accentDeep: '#C97842',
      accentSoft: '#38291D', highlight: 'rgba(232, 146, 90, 0.16)',
    }),
  },
  ember: {
    id: 'ember',
    background: '#1C1210',
    backgroundAccent: '#2A1B17',
    primary: '#FBEFE8',
    secondary: '#C4A99E',
    accent: '#E8694A',
    fontHeading: FONT_ROLES.display,
    fontBody: FONT_ROLES.body,
    fontTechnical: FONT_ROLES.technical,
    tokens: darkTokens({
      id: 'ember', name: 'Ember',
      background: '#1C1210', surface: '#2A1B17', elevatedSurface: '#34221C',
      textPrimary: '#FBEFE8', textSecondary: '#C4A99E', textMuted: '#9A8378',
      line: '#3D2A23', accent: '#E8694A', accentDeep: '#C95232',
      accentSoft: '#3E211A', highlight: 'rgba(232, 105, 74, 0.16)',
    }),
  },
  verdant: {
    id: 'verdant',
    background: '#0E1512',
    backgroundAccent: '#16211C',
    primary: '#F0F5F0',
    secondary: '#A8BFAF',
    accent: '#7FB08E',
    fontHeading: FONT_ROLES.display,
    fontBody: FONT_ROLES.body,
    fontTechnical: FONT_ROLES.technical,
    tokens: darkTokens({
      id: 'verdant', name: 'Verdant',
      background: '#0E1512', surface: '#16211C', elevatedSurface: '#1D2B24',
      textPrimary: '#F0F5F0', textSecondary: '#A8BFAF', textMuted: '#7E9483',
      line: '#26332C', accent: '#7FB08E', accentDeep: '#639474',
      accentSoft: '#1E3229', highlight: 'rgba(127, 176, 142, 0.16)',
    }),
  },
  // Contract palette names (ArtDirectionSpec) that previously fell back silently.
  circuitDark: {
    id: 'circuitDark',
    background: '#131418',
    backgroundAccent: '#1E2026',
    primary: '#F4F2EE',
    secondary: '#A9A69E',
    accent: '#D98E5F',
    fontHeading: FONT_ROLES.display,
    fontBody: FONT_ROLES.body,
    fontTechnical: FONT_ROLES.technical,
    tokens: darkTokens({
      id: 'circuit-dark', name: 'Circuit Dark',
      background: '#131418', surface: '#1E2026', elevatedSurface: '#262930',
      textPrimary: '#F4F2EE', textSecondary: '#A9A69E', textMuted: '#837F78',
      line: '#2C2F36', accent: '#D98E5F', accentDeep: '#BC744C',
      accentSoft: '#33271E', highlight: 'rgba(217, 142, 95, 0.16)',
    }),
  },
  oceanFloor: {
    id: 'oceanFloor',
    background: '#0E161C',
    backgroundAccent: '#17242D',
    primary: '#EFF4F6',
    secondary: '#A3B4BE',
    accent: '#6FA8B8',
    fontHeading: FONT_ROLES.display,
    fontBody: FONT_ROLES.body,
    fontTechnical: FONT_ROLES.technical,
    tokens: darkTokens({
      id: 'ocean-floor', name: 'Ocean Floor',
      background: '#0E161C', surface: '#17242D', elevatedSurface: '#1E2E38',
      textPrimary: '#EFF4F6', textSecondary: '#A3B4BE', textMuted: '#7C8D97',
      line: '#27353F', accent: '#6FA8B8', accentDeep: '#568B99',
      accentSoft: '#1B2E36', highlight: 'rgba(111, 168, 184, 0.16)',
    }),
  },
  // Python StoryboardArtifact default theme name; now resolves intentionally.
  dusk: {
    id: 'dusk',
    background: '#1A1512',
    backgroundAccent: '#262019',
    primary: '#F6F0E8',
    secondary: '#B8AC9C',
    accent: '#D9885C',
    fontHeading: FONT_ROLES.display,
    fontBody: FONT_ROLES.body,
    fontTechnical: FONT_ROLES.technical,
    tokens: darkTokens({
      id: 'dusk', name: 'Dusk',
      background: '#1A1512', surface: '#262019', elevatedSurface: '#2F2820',
      textPrimary: '#F6F0E8', textSecondary: '#B8AC9C', textMuted: '#8C8070',
      line: '#3A3128', accent: '#D9885C', accentDeep: '#BE6F47',
      accentSoft: '#382B20', highlight: 'rgba(217, 136, 92, 0.16)',
    }),
  },
};

export const TYPE = {heading: 64, body: 40, detail: 30, kicker: 30, number: 68} as const;
export const SPACE = {small: 12, card: 24, section: 36, radius: 20} as const;

export const DEFAULT_THEME = THEMES.editorialLight;

export const resolveTheme = (theme?: Partial<ThemeSpec>): ThemeSpec => {
  const key = theme?.id && theme.id in THEMES ? theme.id : 'editorialLight';
  const base = THEMES[key] ?? DEFAULT_THEME;
  const merged: ThemeSpec = {
    ...base,
    ...Object.fromEntries(Object.entries(theme ?? {}).filter(([, value]) => value != null)),
  };
  // Tokens always attached: a dark theme must never render with light tokens.
  merged.tokens = merged.tokens ?? base.tokens ?? DEFAULT_TOKENS;
  return merged;
};

export const TOPIC_THEME_TOKENS = {
  energy: ENERGY_TOKENS,
  science: SCIENCE_TOKENS,
  infrastructure: INFRASTRUCTURE_TOKENS,
};
