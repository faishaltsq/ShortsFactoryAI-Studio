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
        color: '#ffffff',
        textShadow: '0 2px 8px rgba(0,0,0,0.6)',
      }}
    >
      <span style={{backgroundColor: 'rgba(15, 23, 42, 0.72)', borderRadius: 14, padding: '8px 20px'}}>{active.text}</span>
    </div>
  );
};
