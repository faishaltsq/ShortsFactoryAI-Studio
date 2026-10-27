import type {ThemeSpec} from '../types';

export const THEMES: Record<string, ThemeSpec> = {
  midnight: {
    id: 'midnight',
    background: '#0b1020',
    backgroundAccent: '#141b34',
    primary: '#f5f7ff',
    secondary: '#9fb0d8',
    accent: '#ffb02e',
    fontHeading: '"Arial Black", "Segoe UI", sans-serif',
    fontBody: '"Segoe UI", Arial, sans-serif',
  },
  ember: {
    id: 'ember',
    background: '#1a0f0d',
    backgroundAccent: '#2a1713',
    primary: '#fff6ef',
    secondary: '#d9b3a5',
    accent: '#ff5a3c',
    fontHeading: '"Arial Black", "Segoe UI", sans-serif',
    fontBody: '"Segoe UI", Arial, sans-serif',
  },
  verdant: {
    id: 'verdant',
    background: '#071410',
    backgroundAccent: '#0d231b',
    primary: '#f0fff8',
    secondary: '#8fc7ae',
    accent: '#38e08a',
    fontHeading: '"Arial Black", "Segoe UI", sans-serif',
    fontBody: '"Segoe UI", Arial, sans-serif',
  },
};

export const TYPE = {heading: 64, body: 40, detail: 30, kicker: 30, number: 68} as const;
export const SPACE = {small: 12, card: 24, section: 36, radius: 20} as const;

export const DEFAULT_THEME = THEMES.midnight;

export const resolveTheme = (theme?: Partial<ThemeSpec>): ThemeSpec => ({
  ...(THEMES[theme?.id ?? 'midnight'] ?? DEFAULT_THEME),
  ...Object.fromEntries(Object.entries(theme ?? {}).filter(([, value]) => value != null)),
});
