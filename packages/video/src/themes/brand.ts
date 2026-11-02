import type {ThemeSpec} from '../types';

export const THEMES: Record<string, ThemeSpec> = {
  editorialLight: {
    id: 'editorialLight',
    background: '#F8F7F0',
    backgroundAccent: '#EAF3F4',
    primary: '#232B35',
    secondary: '#596674',
    accent: '#36B6B2',
    fontHeading: '"Inter", "Nunito Sans", "Segoe UI", sans-serif',
    fontBody: '"Inter", "Segoe UI", sans-serif',
  },
  warmLifestyle: {
    id: 'warmLifestyle',
    background: '#FFF1D8',
    backgroundAccent: '#F3DDC0',
    primary: '#342D2A',
    secondary: '#75685E',
    accent: '#E97762',
    fontHeading: '"Inter", "Nunito Sans", "Segoe UI", sans-serif',
    fontBody: '"Inter", "Segoe UI", sans-serif',
  },
  spaceDark: {
    id: 'spaceDark',
    background: '#172744',
    backgroundAccent: '#223456',
    primary: '#F7F8FA',
    secondary: '#BFCBE0',
    accent: '#54C2C8',
    fontHeading: '"Inter", "Segoe UI", sans-serif',
    fontBody: '"Inter", "Segoe UI", sans-serif',
  },
  midnight: {
    id: 'midnight',
    background: '#0b1020',
    backgroundAccent: '#141b34',
    primary: '#f5f7ff',
    secondary: '#9fb0d8',
    accent: '#ffb02e',
    fontHeading: '"Inter", "Arial Black", "Segoe UI", sans-serif',
    fontBody: '"Segoe UI", Arial, sans-serif',
  },
  ember: {
    id: 'ember',
    background: '#1a0f0d',
    backgroundAccent: '#2a1713',
    primary: '#fff6ef',
    secondary: '#d9b3a5',
    accent: '#ff5a3c',
    fontHeading: '"Inter", "Arial Black", "Segoe UI", sans-serif',
    fontBody: '"Segoe UI", Arial, sans-serif',
  },
  verdant: {
    id: 'verdant',
    background: '#071410',
    backgroundAccent: '#0d231b',
    primary: '#f0fff8',
    secondary: '#8fc7ae',
    accent: '#38e08a',
    fontHeading: '"Inter", "Arial Black", "Segoe UI", sans-serif',
    fontBody: '"Segoe UI", Arial, sans-serif',
  },
};

export const TYPE = {heading: 64, body: 40, detail: 30, kicker: 30, number: 68} as const;
export const SPACE = {small: 12, card: 24, section: 36, radius: 20} as const;

export const DEFAULT_THEME = THEMES.editorialLight;

export const resolveTheme = (theme?: Partial<ThemeSpec>): ThemeSpec => {
  const key = theme?.id && theme.id in THEMES ? theme.id : 'editorialLight';
  const base = THEMES[key] ?? DEFAULT_THEME;
  return {
    ...base,
    ...Object.fromEntries(Object.entries(theme ?? {}).filter(([, value]) => value != null)),
  };
};
