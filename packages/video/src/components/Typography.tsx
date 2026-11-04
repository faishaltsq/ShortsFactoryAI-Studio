import React from 'react';
import {DEFAULT_TOKENS, type ThemeTokens} from '../themes/tokens';
import {TYPE_SCALE, type TypeStyle} from '../themes/type';

/**
 * Pure typography components consuming semantic design tokens.
 *
 * Targets: Warm editorial identity, 1080x1920 mobile viewport.
 * Pure React: zero dependency on legacy themes/brand.ts, zero Remotion hook coupling.
 *
 * ponytail: prop-drilled tokens; add ThemeContext / useTokens() hook when compositions are migrated in a later pass.
 */

export type EmphasisKind = 'none' | 'italic' | 'bold' | 'accent';

export interface BaseTypographyProps {
  readonly children?: React.ReactNode;
  readonly tokens?: ThemeTokens;
  readonly style?: React.CSSProperties;
  readonly color?: string;
  readonly align?: 'left' | 'center' | 'right';
  readonly emphasis?: EmphasisKind;
  readonly as?: React.ElementType;
}

const resolveEmphasisStyle = (
  emphasis: EmphasisKind | undefined,
  tokens: ThemeTokens,
  baseStyle: TypeStyle
): React.CSSProperties => {
  if (!emphasis || emphasis === 'none') return {};
  switch (emphasis) {
    case 'italic':
      return {fontStyle: 'italic'};
    case 'bold':
      return {fontWeight: Math.min(900, baseStyle.fontWeight + 200)};
    case 'accent':
      return {color: tokens.accentDeep};
  }
};

const buildBaseStyle = (
  typeStyle: TypeStyle,
  tokens: ThemeTokens,
  color: string,
  align?: 'left' | 'center' | 'right',
  emphasis?: EmphasisKind
): React.CSSProperties => ({
  fontSize: typeStyle.fontSize,
  fontWeight: typeStyle.fontWeight,
  fontFamily: typeStyle.fontFamily,
  letterSpacing: typeStyle.letterSpacing,
  lineHeight: typeStyle.lineHeight,
  color,
  textAlign: align,
  margin: 0,
  padding: 0,
  ...(typeStyle.textTransform ? {textTransform: typeStyle.textTransform} : {}),
  ...resolveEmphasisStyle(emphasis, tokens, typeStyle),
});

export interface DisplayProps extends BaseTypographyProps {
  /** When true, scales up to displayXl (116px) for single-word hero moments */
  readonly oversized?: boolean;
}

/**
 * Editorial Display serif (Fraunces).
 * Used for hero hooks, massive section breakers, and single-word anchors.
 */
export const Display: React.FC<DisplayProps> = ({
  children,
  tokens = DEFAULT_TOKENS,
  style,
  color,
  align = 'left',
  emphasis = 'none',
  oversized = false,
  as: Component = 'h1',
}) => {
  const typeStyle = oversized ? TYPE_SCALE.displayXl : TYPE_SCALE.displayLg;
  const textColor = color ?? tokens.textPrimary;
  return (
    <Component
      style={{
        ...buildBaseStyle(typeStyle, tokens, textColor, align, emphasis),
        ...style,
      }}
    >
      {children}
    </Component>
  );
};

export type HeadlineProps = BaseTypographyProps;

/**
 * Editorial Headline serif (Fraunces 88px).
 * Main narrative scene headlines conforming to ADR-0012 title band.
 */
export const Headline: React.FC<HeadlineProps> = ({
  children,
  tokens = DEFAULT_TOKENS,
  style,
  color,
  align = 'left',
  emphasis = 'none',
  as: Component = 'h2',
}) => {
  const typeStyle = TYPE_SCALE.displayLg;
  const textColor = color ?? tokens.textPrimary;
  return (
    <Component
      style={{
        ...buildBaseStyle(typeStyle, tokens, textColor, align, emphasis),
        ...style,
      }}
    >
      {children}
    </Component>
  );
};

export type TitleProps = BaseTypographyProps;

/**
 * Editorial Title serif (Fraunces 64px).
 * Scene section titles, card headers, and narrative beats.
 */
export const Title: React.FC<TitleProps> = ({
  children,
  tokens = DEFAULT_TOKENS,
  style,
  color,
  align = 'left',
  emphasis = 'none',
  as: Component = 'h3',
}) => {
  const typeStyle = TYPE_SCALE.heading;
  const textColor = color ?? tokens.textPrimary;
  return (
    <Component
      style={{
        ...buildBaseStyle(typeStyle, tokens, textColor, align, emphasis),
        ...style,
      }}
    >
      {children}
    </Component>
  );
};

export type SubheadingProps = BaseTypographyProps;

/**
 * Subheading sans (Manrope 48px).
 * Supporting takeaways, thesis lines, and key takeaway phrases.
 */
export const Subheading: React.FC<SubheadingProps> = ({
  children,
  tokens = DEFAULT_TOKENS,
  style,
  color,
  align = 'left',
  emphasis = 'none',
  as: Component = 'h4',
}) => {
  const typeStyle = TYPE_SCALE.subheading;
  const textColor = color ?? tokens.textSecondary;
  return (
    <Component
      style={{
        ...buildBaseStyle(typeStyle, tokens, textColor, align, emphasis),
        ...style,
      }}
    >
      {children}
    </Component>
  );
};

export interface BodyProps extends BaseTypographyProps {
  readonly small?: boolean;
}

/**
 * Body text sans (Manrope 40px / 34px).
 * Explanatory narrative, multi-line exposition, card content.
 */
export const Body: React.FC<BodyProps> = ({
  children,
  tokens = DEFAULT_TOKENS,
  style,
  color,
  align = 'left',
  emphasis = 'none',
  small = false,
  as: Component = 'p',
}) => {
  const typeStyle = small ? TYPE_SCALE.bodySmall : TYPE_SCALE.body;
  const textColor = color ?? tokens.textPrimary;
  return (
    <Component
      style={{
        ...buildBaseStyle(typeStyle, tokens, textColor, align, emphasis),
        ...style,
      }}
    >
      {children}
    </Component>
  );
};

export type CaptionProps = BaseTypographyProps;

/**
 * Subtitle / caption text (Manrope 38px semi-bold).
 * Burned-in speech subtitles, lower thirds, guaranteed legible at mobile distance.
 */
export const Caption: React.FC<CaptionProps> = ({
  children,
  tokens = DEFAULT_TOKENS,
  style,
  color,
  align = 'center',
  emphasis = 'none',
  as: Component = 'span',
}) => {
  const typeStyle = TYPE_SCALE.caption;
  const textColor = color ?? tokens.textSecondary;
  return (
    <Component
      style={{
        ...buildBaseStyle(typeStyle, tokens, textColor, align, emphasis),
        ...style,
      }}
    >
      {children}
    </Component>
  );
};

export type KickerProps = BaseTypographyProps;

/**
 * Kicker / supertitle (Manrope 24px bold uppercase tracked).
 * Category pills, topic labels, supertitles above headlines.
 */
export const Kicker: React.FC<KickerProps> = ({
  children,
  tokens = DEFAULT_TOKENS,
  style,
  color,
  align = 'left',
  as: Component = 'div',
}) => {
  const typeStyle = TYPE_SCALE.micro;
  const textColor = color ?? tokens.accentDeep;
  return (
    <Component
      style={{
        ...buildBaseStyle(typeStyle, tokens, textColor, align, 'none'),
        ...style,
      }}
    >
      {children}
    </Component>
  );
};

export interface MetricProps extends BaseTypographyProps {
  readonly prefix?: string;
  readonly suffix?: string;
  readonly change?: 'positive' | 'negative' | 'neutral';
  readonly size?: 'md' | 'lg' | 'xl';
}

/**
 * Technical numeric metric (IBM Plex Mono).
 * Numbers, percentages, financial shifts, tabular layout.
 */
export const Metric: React.FC<MetricProps> = ({
  children,
  tokens = DEFAULT_TOKENS,
  style,
  color,
  align = 'left',
  prefix,
  suffix,
  change = 'neutral',
  size = 'lg',
  as: Component = 'span',
}) => {
  const sizeMap = {
    md: 40,
    lg: 60,
    xl: 84,
  };

  const statusColor =
    change === 'positive'
      ? tokens.status.success
      : change === 'negative'
        ? tokens.status.error
        : tokens.textPrimary;

  const textColor = color ?? statusColor;

  return (
    <Component
      style={{
        fontFamily: TYPE_SCALE.techLabel.fontFamily,
        fontSize: sizeMap[size],
        fontWeight: 600,
        letterSpacing: '-0.02em',
        lineHeight: 1.1,
        color: textColor,
        fontVariantNumeric: 'tabular-nums',
        textAlign: align,
        display: 'inline-flex',
        alignItems: 'baseline',
        gap: '4px',
        ...style,
      }}
    >
      {prefix ? (
        <span style={{fontSize: '0.65em', opacity: 0.85, fontWeight: 500}}>
          {prefix}
        </span>
      ) : null}
      <span>{children}</span>
      {suffix ? (
        <span style={{fontSize: '0.65em', opacity: 0.85, fontWeight: 500}}>
          {suffix}
        </span>
      ) : null}
    </Component>
  );
};

export type LabelProps = BaseTypographyProps;

/**
 * Technical / metadata label (IBM Plex Mono 32px).
 * Chart axis labels, metadata tags, timestamp markers.
 */
export const Label: React.FC<LabelProps> = ({
  children,
  tokens = DEFAULT_TOKENS,
  style,
  color,
  align = 'left',
  as: Component = 'span',
}) => {
  const typeStyle = TYPE_SCALE.techLabel;
  const textColor = color ?? tokens.textMuted;
  return (
    <Component
      style={{
        ...buildBaseStyle(typeStyle, tokens, textColor, align, 'none'),
        ...style,
      }}
    >
      {children}
    </Component>
  );
};

export interface HighlightProps {
  readonly children: React.ReactNode;
  readonly tokens?: ThemeTokens;
  readonly variant?: 'wash' | 'underline' | 'accent';
  readonly color?: string;
  readonly textColor?: string;
  readonly style?: React.CSSProperties;
}

/**
 * Selective inline highlight for editorial emphasis.
 * Supports:
 * - 'wash': tinted rounded background bar behind text
 * - 'underline': warm editorial bottom border highlight bar
 * - 'accent': accent colored text
 */
export const Highlight: React.FC<HighlightProps> = ({
  children,
  tokens = DEFAULT_TOKENS,
  variant = 'wash',
  color,
  textColor,
  style,
}) => {
  if (variant === 'accent') {
    return (
      <span
        style={{
          color: color ?? tokens.accentDeep,
          ...style,
        }}
      >
        {children}
      </span>
    );
  }

  if (variant === 'underline') {
    const barColor = color ?? tokens.accent;
    return (
      <span
        style={{
          position: 'relative',
          display: 'inline-block',
          boxShadow: `inset 0 -8px 0 ${barColor}`,
          paddingBottom: '2px',
          color: textColor ?? 'inherit',
          ...style,
        }}
      >
        {children}
      </span>
    );
  }

  // variant === 'wash'
  const bg = color ?? tokens.highlight;
  const fg = textColor ?? tokens.accentDeep;
  return (
    <span
      style={{
        backgroundColor: bg,
        color: fg,
        padding: '2px 14px',
        borderRadius: 8,
        display: 'inline-block',
        ...style,
      }}
    >
      {children}
    </span>
  );
};

export interface StackedLayoutProps {
  readonly children: React.ReactNode;
  readonly gap?: number;
  readonly align?: 'flex-start' | 'center' | 'flex-end';
  readonly style?: React.CSSProperties;
}

/**
 * Stacked vertical layout container for multi-line editorial headlines and descriptions.
 */
export const StackedLayout: React.FC<StackedLayoutProps> = ({
  children,
  gap = 20,
  align = 'flex-start',
  style,
}) => (
  <div
    style={{
      display: 'flex',
      flexDirection: 'column',
      gap: `${gap}px`,
      alignItems: align,
      ...style,
    }}
  >
    {children}
  </div>
);
