import React from 'react';
import {useCurrentFrame} from 'remotion';
import type {ThemeSpec} from '../types';
import {DEFAULT_TOKENS, type ThemeTokens} from '../themes/tokens';
import {Kicker, Label} from './Typography';
import {pinnedOverlayStyle} from './CameraPinning';

export const Background: React.FC<{
  theme: ThemeSpec;
  variant?: 'gradient' | 'radial' | 'split';
  tokens?: ThemeTokens;
}> = ({
  theme,
  variant = 'gradient',
  tokens: tokensProp,
}) => {
  const tokens = tokensProp ?? theme?.tokens ?? DEFAULT_TOKENS;
  let frame = 0;
  try {
    frame = useCurrentFrame();
  } catch {
    // Outside Remotion composition context, fallback to 0
  }
  if (variant === 'radial') {
    const y = 32 + Math.sin(frame / 45) * 2;
    return (
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background: `radial-gradient(circle at 50% ${y.toFixed(2)}%, ${tokens.surface} 0%, ${tokens.background} 62%)`,
        }}
      />
    );
  }
  if (variant === 'split') {
    const y1 = 62 + Math.sin(frame / 45) * 1.5;
    const y2 = 44 + Math.cos(frame / 40) * 1.5;
    return (
      <div style={{position: 'absolute', inset: 0, background: tokens.background}}>
        <div
          style={{
            position: 'absolute',
            inset: 0,
            background: tokens.surface,
            clipPath: `polygon(0 ${y1.toFixed(2)}%, 100% ${y2.toFixed(2)}%, 100% 100%, 0 100%)`,
          }}
        />
      </div>
    );
  }
  const angle = 160 + Math.sin(frame / 50) * 4;
  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        background: `linear-gradient(${angle.toFixed(2)}deg, ${tokens.surface} 0%, ${tokens.background} 55%, ${tokens.surface} 100%)`,
      }}
    />
  );
};

export const SafeArea: React.FC<{children: React.ReactNode; top?: number; bottom?: number}> = ({children, top = 260, bottom = 420}) => (
  <div
    style={{
      position: 'absolute',
      top,
      bottom,
      left: 72,
      right: 72,
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'center',
    }}
  >
    {children}
  </div>
);

export const AccentBar: React.FC<{
  theme: ThemeSpec;
  width?: number;
  label?: string;
  tokens?: ThemeTokens;
}> = ({theme, width = 180, label, tokens: tokensProp}) => {
  const tokens = tokensProp ?? theme?.tokens ?? DEFAULT_TOKENS;
  const bar = <div style={{width, height: 14, borderRadius: 7, backgroundColor: tokens.accent}} />;
  if (!label) return bar;
  return (
    <div style={{display: 'inline-flex', alignItems: 'center', gap: 12}}>
      {bar}
      <Label tokens={tokens}>{label}</Label>
    </div>
  );
};

export const Watermark: React.FC<{
  text: string;
  theme: ThemeSpec;
  opacity?: number;
  tokens?: ThemeTokens;
}> = ({text, theme, opacity = 0.55, tokens: tokensProp}) => {
  const tokens = tokensProp ?? theme?.tokens ?? DEFAULT_TOKENS;
  // The watermark is an annotation like the title band: pinned to the frame while the camera
  // moves the stage, so it cannot slide off-screen on a pan.
  const pinned = pinnedOverlayStyle();
  return (
    <Kicker
      tokens={tokens}
      color={tokens.textMuted}
      style={{
        position: 'absolute',
        top: 230,
        left: 72,
        opacity,
        ...pinned,
      }}
    >
      {text}
    </Kicker>
  );
};
