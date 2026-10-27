import React from 'react';
import type {CameraTransform} from '../camera';

/**
 * The stage transform for a declared camera.
 *
 * `translate` comes before `scale` so `CameraTransform.x/y` are real screen pixels regardless of
 * the shot scale — that is what makes a declared `pan` of `amplitude: 0.12` move the frame by
 * exactly 6 % of its width instead of 6 % of a zoomed width.
 *
 * This is a separate component from `art/Camera.tsx` on purpose: that one carries the renderer's
 * own per-shot moves, whose pixel values existing fixtures and measurements were taken against.
 * A scene that declares no camera must keep rendering byte-identically, so the legacy path is
 * untouched rather than re-derived here.
 */
export const DeclaredCamera: React.FC<{state: CameraTransform; children: React.ReactNode}> = ({
  state,
  children,
}) => (
  <div
    style={{
      position: 'absolute',
      inset: 0,
      transform: `translate(${state.x}px, ${state.y}px) scale(${state.scale}) rotate(${state.rotate}deg)`,
      transformOrigin: `${state.originX * 100}% ${state.originY * 100}%`,
    }}
  >
    {children}
  </div>
);
