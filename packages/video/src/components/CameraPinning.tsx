import React from 'react';
import type {CameraTransform} from '../camera';
import {invertCamera} from '../camera';

/**
 * The declared camera state for the scene an overlay sits in.
 *
 * `DeclaredCameraScope` is the single camera authority: it resolves `scene.camera` once per frame
 * and provides the result here. A scene that declares no camera provides ``null`` — overlays then
 * render with no counter-transform, exactly as before the camera existed.
 */
export const CameraStateContext = React.createContext<CameraTransform | null>(null);

/** True when the nearest scope declared a moving camera, so a pinned overlay must counter it. */
export const hasCamera = (): boolean => React.useContext(CameraStateContext) !== null;

/**
 * Style that keeps an overlay where the storyboard placed it while the camera moves the stage.
 *
 * The overlay still sits *inside* the camera's transformed element (that is what makes it clip
 * with the stage when the camera pans), so the counter-transform must be the camera's inverse
 * about the same origin, not a plain negative translate. `invertCamera` computes it; this hook
 * turns it into the style the overlay applies.
 */
export const pinnedOverlayStyle = (): React.CSSProperties => {
  const state = React.useContext(CameraStateContext);
  if (!state) return {};
  const inverse = invertCamera(state);
  return {
    transform: `translate(${inverse.x}px, ${inverse.y}px) scale(${inverse.scale}) rotate(${inverse.rotate}deg)`,
    transformOrigin: `${state.originX * 100}% ${state.originY * 100}%`,
  };
};
