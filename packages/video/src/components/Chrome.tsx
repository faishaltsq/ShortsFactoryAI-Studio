import React from 'react';
import {useCurrentFrame} from 'remotion';
import type {ThemeSpec} from '../types';

export const Background: React.FC<{theme: ThemeSpec; variant?: 'gradient' | 'radial' | 'split'}> = ({
  theme,
  variant = 'gradient',
}) => {
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
          background: `radial-gradient(circle at 50% ${y.toFixed(2)}%, ${theme.backgroundAccent} 0%, ${theme.background} 62%)`,
        }}
      />
    );
  }
  if (variant === 'split') {
    const y1 = 62 + Math.sin(frame / 45) * 1.5;
    const y2 = 44 + Math.cos(frame / 40) * 1.5;
    return (
      <div style={{position: 'absolute', inset: 0, background: theme.background}}>
        <div
          style={{
            position: 'absolute',
            inset: 0,
            background: theme.backgroundAccent,
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
        background: `linear-gradient(${angle.toFixed(2)}deg, ${theme.backgroundAccent} 0%, ${theme.background} 55%, ${theme.backgroundAccent} 100%)`,
      }}
    />
  );
};

export const SafeArea: React.FC<{children: React.ReactNode; top?: number; bottom?: number}> = ({children, top = 260, bottom = 320}) => (
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

export const AccentBar: React.FC<{theme: ThemeSpec; width?: number}> = ({theme, width = 180}) => (
  <div style={{width, height: 14, borderRadius: 7, backgroundColor: theme.accent}} />
);

export const Watermark: React.FC<{text: string; theme: ThemeSpec; opacity?: number}> = ({text, theme, opacity = 0.55}) => (
  <div
    style={{
      position: 'absolute',
      top: 150,
      left: 72,
      fontFamily: theme.fontBody,
      fontSize: 34,
      letterSpacing: 4,
      textTransform: 'uppercase',
      color: theme.secondary,
      opacity,
    }}
  >
    {text}
  </div>
);
