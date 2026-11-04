import React from 'react';
import type {SubtitleCue, ThemeSpec} from '../types';
import {DEFAULT_TOKENS, type ThemeTokens} from '../themes/tokens';
import {Caption} from './Typography';
import {alpha} from '../art/palette';

export interface SubtitlesProps {
  cues: SubtitleCue[];
  theme: ThemeSpec;
  currentFrame: number;
  fps: number;
  bottom?: number;
  tokens?: ThemeTokens;
}

export const Subtitles: React.FC<SubtitlesProps> = ({
  cues,
  theme,
  currentFrame,
  fps,
  bottom = 360,
  tokens: tokensProp,
}) => {
  const tokens = tokensProp ?? theme?.tokens ?? DEFAULT_TOKENS;
  const tMs = (currentFrame / fps) * 1000;
  const active = cues.find((c) => tMs >= c.startMs && tMs < c.endMs);
  if (!active) return null;
  return (
    <div
      style={{
        position: 'absolute',
        bottom,
        left: 90,
        right: 90,
        textAlign: 'center',
        pointerEvents: 'none',
      }}
    >
      <span
        style={{
          display: 'inline-block',
          backgroundColor: alpha(tokens.surface, 0.92),
          boxShadow: tokens.shadow.md,
          border: `1px solid ${alpha(tokens.line, 0.7)}`,
          borderRadius: 14,
          padding: '10px 24px',
          maxWidth: '100%',
        }}
      >
        <Caption tokens={tokens} color={tokens.textPrimary}>
          {active.text}
        </Caption>
      </span>
    </div>
  );
};

