/**
 * Semantic color token system for ShortsFactoryAI video engine.
 * Target: Warm editorial light mode ("Claude-like") for 1080x1920 YouTube Shorts.
 *
 * Soft cream parchment, warm sand, muted terracotta/amber, deep warm espresso text.
 * Restrained contrast, subtle depth, premium minimalism.
 *
 * ponytail: fixed light-mode tokens; add dark mode / dynamic theme injection when multi-theme render is scheduled.
 */

export interface StatusTokens {
  readonly success: string;
  readonly warning: string;
  readonly error: string;
}

export interface ShadowTokens {
  readonly sm: string;
  readonly md: string;
  readonly lg: string;
  readonly float: string;
}

export interface TopicTokens {
  readonly accent: string;
  readonly accentDeep: string;
  readonly accentSoft: string;
  readonly highlight: string;
}

export interface ThemeTokens {
  readonly id: string;
  readonly name: string;
  readonly background: string;
  readonly surface: string;
  readonly elevatedSurface: string;
  readonly textPrimary: string;
  readonly textSecondary: string;
  readonly textMuted: string;
  readonly accent: string;
  readonly accentDeep: string;
  readonly accentSoft: string;
  readonly line: string;
  readonly highlight: string;
  readonly chartColors: readonly [string, string, string, string, string, string];
  readonly status: StatusTokens;
  readonly shadow: ShadowTokens;
  readonly topic?: TopicTokens;
}

/**
 * Shared editorial brand shell.
 * Guaranteed consistent across all video topics: only topic accents shift.
 */
const BRAND_SHELL = {
  background: '#FAF7F2',       // Warm parchment cream
  surface: '#F3EFEA',          // Warm linen / subtle slab
  elevatedSurface: '#FFFFFF',  // Pure card white on parchment
  textPrimary: '#241C15',      // Deep warm espresso (contrast > 15:1)
  textSecondary: '#5C5248',    // Warm charcoal stone (contrast > 7:1)
  textMuted: '#8C8175',        // Warm taupe gray (contrast > 3.5:1)
  line: '#E6DFD5',             // Refined warm border / rule line
  status: {
    success: '#3A7D5C',        // Restrained forest pine
    warning: '#C27D23',        // Warm ochre gold
    error: '#BD3E33',          // Editorial brick crimson
  },
  shadow: {
    sm: '0 2px 8px rgba(36, 28, 21, 0.04)',
    md: '0 8px 24px rgba(36, 28, 21, 0.06)',
    lg: '0 20px 48px rgba(36, 28, 21, 0.08)',
    float: '0 28px 64px rgba(36, 28, 21, 0.12), 0 4px 12px rgba(36, 28, 21, 0.04)',
  },
} as const;

export type TopicKind = 'energy' | 'science' | 'infrastructure';

/**
 * Topic-supporting accents per brief:
 * - energy -> amber / terracotta
 * - science -> restrained slate / sage
 * - infrastructure -> muted olive / blue-gray
 */
export const TOPIC_ACCENTS: Record<TopicKind, TopicTokens> = {
  energy: {
    accent: '#D46B38',         // Warm terracotta amber
    accentDeep: '#A84A1C',     // Deep burnt sienna
    accentSoft: '#FBECE4',     // Soft peach blush wash
    highlight: 'rgba(212, 107, 56, 0.14)',
  },
  science: {
    accent: '#4B7268',         // Restrained eucalyptus sage
    accentDeep: '#34534B',     // Deep slate forest
    accentSoft: '#EBF2EE',     // Pale sage wash
    highlight: 'rgba(75, 114, 104, 0.14)',
  },
  infrastructure: {
    accent: '#486581',         // Muted slate blue / steel
    accentDeep: '#2E4861',     // Deep ocean slate
    accentSoft: '#E8EEF5',     // Cool mist blue wash
    highlight: 'rgba(72, 101, 129, 0.14)',
  },
} as const;

/**
 * Editorial Light global default tokens.
 * Warm Claude terracotta accent on parchment cream.
 */
export const DEFAULT_TOKENS: ThemeTokens = {
  id: 'editorial-light',
  name: 'Editorial Light',
  ...BRAND_SHELL,
  accent: '#D97757',           // Editorial Claude terracotta
  accentDeep: '#B85838',       // Deep terracotta for high legibility
  accentSoft: '#FBECE4',       // Warm terracotta tint
  highlight: 'rgba(217, 119, 87, 0.14)',
  chartColors: [
    '#D97757', // 1: Terracotta
    '#4B7268', // 2: Sage
    '#D29C44', // 3: Warm Amber / Ochre
    '#486581', // 4: Slate Blue
    '#935F7E', // 5: Muted Mulberry
    '#758063', // 6: Moss Olive
  ],
  topic: TOPIC_ACCENTS.energy,
};

export const ENERGY_TOKENS: ThemeTokens = {
  ...DEFAULT_TOKENS,
  id: 'editorial-energy',
  name: 'Editorial Energy',
  accent: TOPIC_ACCENTS.energy.accent,
  accentDeep: TOPIC_ACCENTS.energy.accentDeep,
  accentSoft: TOPIC_ACCENTS.energy.accentSoft,
  highlight: TOPIC_ACCENTS.energy.highlight,
  chartColors: [
    '#D46B38', // Amber terracotta
    '#D29C44', // Ochre
    '#758063', // Olive
    '#486581', // Slate
    '#935F7E', // Mulberry
    '#A84A1C', // Deep sienna
  ],
  topic: TOPIC_ACCENTS.energy,
};

export const SCIENCE_TOKENS: ThemeTokens = {
  ...DEFAULT_TOKENS,
  id: 'editorial-science',
  name: 'Editorial Science',
  accent: TOPIC_ACCENTS.science.accent,
  accentDeep: TOPIC_ACCENTS.science.accentDeep,
  accentSoft: TOPIC_ACCENTS.science.accentSoft,
  highlight: TOPIC_ACCENTS.science.highlight,
  chartColors: [
    '#4B7268', // Sage
    '#486581', // Slate blue
    '#D97757', // Terracotta
    '#D29C44', // Ochre
    '#758063', // Moss
    '#34534B', // Deep forest
  ],
  topic: TOPIC_ACCENTS.science,
};

export const INFRASTRUCTURE_TOKENS: ThemeTokens = {
  ...DEFAULT_TOKENS,
  id: 'editorial-infrastructure',
  name: 'Editorial Infrastructure',
  accent: TOPIC_ACCENTS.infrastructure.accent,
  accentDeep: TOPIC_ACCENTS.infrastructure.accentDeep,
  accentSoft: TOPIC_ACCENTS.infrastructure.accentSoft,
  highlight: TOPIC_ACCENTS.infrastructure.highlight,
  chartColors: [
    '#486581', // Slate steel
    '#758063', // Muted olive
    '#D97757', // Terracotta
    '#D29C44', // Ochre
    '#4B7268', // Sage
    '#2E4861', // Deep slate
  ],
  topic: TOPIC_ACCENTS.infrastructure,
};

export const TOPIC_TOKENS: Record<TopicKind, ThemeTokens> = {
  energy: ENERGY_TOKENS,
  science: SCIENCE_TOKENS,
  infrastructure: INFRASTRUCTURE_TOKENS,
} as const;

/**
 * Resolves theme tokens by topic string or returns default warm editorial tokens.
 */
export const resolveTokens = (topic?: string): ThemeTokens => {
  if (topic && topic in TOPIC_TOKENS) {
    return TOPIC_TOKENS[topic as TopicKind];
  }
  return DEFAULT_TOKENS;
};
