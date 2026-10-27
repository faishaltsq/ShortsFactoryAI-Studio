import React from 'react';
import type {CameraMove} from '../scene-data';

export interface CameraState {scale: number; x: number; y: number; rotate: number}

const smooth = (t: number): number => {
  const p = Math.min(1, Math.max(0, t));
  return p * p * (3 - 2 * p);
};

export const cameraAt = (
  move: CameraMove,
  frame: number,
  durationInFrames: number,
  strength = 1,
): CameraState => {
  const t = durationInFrames <= 1 ? 1 : smooth(frame / (durationInFrames - 1));
  switch (move) {
    case 'pushIn':
      return {scale: 1 + 0.12 * t * strength, x: 0, y: 0, rotate: 0};
    case 'pullOut':
      return {scale: 1.12 - 0.12 * t * strength, x: 0, y: 0, rotate: 0};
    case 'panLeft':
      return {scale: 1.08, x: 64 * (1 - t) * strength, y: 0, rotate: 0};
    case 'panRight':
      return {scale: 1.08, x: -64 * (1 - t) * strength, y: 0, rotate: 0};
    case 'tiltUp':
      return {scale: 1.06, x: 0, y: 72 * (1 - t) * strength, rotate: 0};
    case 'handheld': {
      // Two incommensurate sines read as organic drift and stay perfectly deterministic.
      const sway = Math.sin(frame / 17) * 5 + Math.sin(frame / 6.3) * 2.2;
      return {
        scale: 1.05,
        x: sway * strength,
        y: Math.cos(frame / 13) * 3.4 * strength,
        rotate: Math.sin(frame / 23) * 0.18,
      };
    }
    default:
      return {scale: 1, x: 0, y: 0, rotate: 0};
  }
};

export const Camera: React.FC<{state: CameraState; children: React.ReactNode}> = ({state, children}) => (
  <div
    style={{
      position: 'absolute',
      inset: 0,
      transform: `scale(${state.scale}) translate(${state.x}px, ${state.y}px) rotate(${state.rotate}deg)`,
      transformOrigin: '50% 54%',
    }}
  >
    {children}
  </div>
);
