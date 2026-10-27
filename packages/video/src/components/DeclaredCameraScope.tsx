import React from 'react';
import {useCurrentFrame, useVideoConfig} from 'remotion';
import type {SceneSpec} from '../types';
import {declaredCameraAt, textAnchorOf, type CameraTransform} from '../camera';
import {DeclaredCamera} from '../art/DeclaredCamera';

/**
 * Declared camera for any template, not just `IllustratedStory`.
 *
 * `IllustratedStory` consumes `scene.camera` inline because it also blends it with the per-shot
 * legacy path. Every other composition has no such legacy: their content components were written
 * before `SceneSpec.camera` existed, so wiring the declared camera there meant either editing six
 * components identically or wrapping them once. The wrapper is the one place to read the rule.
 *
 * Precedence lives in `src/camera.ts` and is unchanged: a scene that declares no camera renders its
 * children untouched, byte-identically — this component must never invent a move the model did not
 * author, because an unmotivated camera move is a validation error at the contract, not a default.
 *
 * The transform is pure in `(scene, frame)`, so Remotion's out-of-order frame rendering produces
 * the same picture regardless of the order frames arrive.
 */
export const DeclaredCameraScope: React.FC<{
  scene: SceneSpec;
  children: React.ReactNode;
}> = ({scene, children}) => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();

  if (!scene.camera) return <>{children}</>;

  const sceneFrame = frame - scene.startFrame;
  const anchor = textAnchorOf(scene, scene.camera.target);
  let state: CameraTransform;
  try {
    state = declaredCameraAt(scene.camera, sceneFrame, scene.durationInFrames, anchor, {
      width,
      height,
    });
  } catch {
    // An invalid camera is a contract error, not a render-time event: the Python validator and
    // `adaptCamera` both reject bad values before pixels. Reaching here means a hand-written props
    // file bypassed both, and rendering the unmoving base state is more honest than a 500.
    return <>{children}</>;
  }
  return <DeclaredCamera state={state}>{children}</DeclaredCamera>;
};
