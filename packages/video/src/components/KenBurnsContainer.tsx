import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';

export interface KenBurnsContainerProps {
  children: React.ReactNode;
  maxScale?: number;
  durationInFrames?: number;
}

export const KenBurnsContainer: React.FC<KenBurnsContainerProps> = ({
  children,
  maxScale = 1.07,
  durationInFrames: customDuration,
}) => {
  const frame = useCurrentFrame();
  const {durationInFrames: configDuration} = useVideoConfig();
  const duration = Math.max(1, customDuration ?? configDuration);

  const scale = interpolate(frame, [0, duration], [1, maxScale], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill
      style={{
        transform: `scale(${scale})`,
        transformOrigin: 'center center',
        overflow: 'hidden',
      }}
    >
      {children}
    </AbsoluteFill>
  );
};
