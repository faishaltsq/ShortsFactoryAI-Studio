import React from 'react';
import type {SubtitleCue, ThemeSpec} from '../types';

export const Subtitles: React.FC<{cues: SubtitleCue[]; theme: ThemeSpec; currentFrame: number; fps: number; bottom?: number}> = ({
  cues,
  theme,
  currentFrame,
  fps,
  bottom = 360,
}) => {
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
        fontFamily: theme.fontHeading,
        fontSize: 58,
        lineHeight: 1.25,
        color: theme.primary,
        textShadow: '0 4px 18px rgba(0,0,0,0.85)',
      }}
    >
      <span style={{backgroundColor: 'rgba(0,0,0,0.35)', borderRadius: 12, padding: '6px 16px'}}>{active.text}</span>
    </div>
  );
};
