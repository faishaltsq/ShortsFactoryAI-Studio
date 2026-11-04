import React from 'react';
import {AbsoluteFill, Audio, Sequence, interpolate, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import type {SceneSpec, StoryboardSpec} from '../types';
import {SCENE_RENDERERS} from './registry';
import {validateSceneData} from '../scene-data';
import {resolveTheme} from '../themes/brand';
import {DEFAULT_TOKENS} from '../themes/tokens';
import {EDITORIAL_EASING} from '../components/motion';
import {Subtitles} from '../components/Subtitles';
import {TiktokCaptions} from '../components/TiktokCaptions';
import {KenBurnsContainer} from '../components/KenBurnsContainer';
import {SafeZoneOverlay} from '../components/SafeZoneOverlay';
import {DeclaredCameraScope} from '../components/DeclaredCameraScope';


const renderScene = (scene: SceneSpec, theme: StoryboardSpec['theme'], watermark?: string): React.ReactNode => {
  validateSceneData(scene);
  const Component = SCENE_RENDERERS[scene.template];
  if (!Component) throw new Error(`Template not implemented: ${scene.template}`);
  // A declared camera wraps every template: the transform is a pure function of the declared
  // camera, the frame and the named text anchor, none of which is template-specific. A scene with
  // no declared camera renders byte-identically.
  return (
    <DeclaredCameraScope scene={scene}>
      <Component scene={scene} theme={theme} watermark={watermark} />
    </DeclaredCameraScope>
  );
};

/** Applies the scene's transition as an in/out opacity (and optional slide) ramp.
 *  Editorial feel: smoothOut easing, restrained 24px slide, 1.03 zoom breath. */
const TransitionedScene: React.FC<{scene: SceneSpec; children: React.ReactNode}> = ({scene, children}) => {
  const frame = useCurrentFrame();
  if (scene.transition.type === 'none' || !scene.transition.durationInFrames) {
    return <>{children}</>;
  }
  const fade = Math.min(scene.transition.durationInFrames, Math.floor(scene.durationInFrames / 2));
  const opacity = interpolate(frame, [0, fade, scene.durationInFrames - fade, scene.durationInFrames], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: EDITORIAL_EASING.smoothOut,
  });
  const translateY =
    scene.transition.type === 'slideUp'
      ? interpolate(frame, [0, fade], [24, 0], {
          extrapolateLeft: 'clamp',
          extrapolateRight: 'clamp',
          easing: EDITORIAL_EASING.smoothOut,
        })
      : 0;
  const progress = interpolate(frame, [0, fade], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: EDITORIAL_EASING.smoothOut,
  });
  const scale = scene.transition.type === 'zoom' ? 1.03 - progress * 0.03 : 1;
  const clipPath = scene.transition.type === 'wipe' ? `inset(0 ${(1 - progress) * 100}% 0 0)` : undefined;
  return <AbsoluteFill style={{opacity, clipPath, transform: `translateY(${translateY}px) scale(${scale})`}}>{children}</AbsoluteFill>;
};

const ProgressBar: React.FC<{theme: StoryboardSpec['theme']; totalFrames: number}> = ({theme, totalFrames}) => {
  const frame = useCurrentFrame();
  const pct = interpolate(frame, [0, totalFrames], [0, 100], {extrapolateRight: 'clamp'});
  const tokens = theme.tokens ?? DEFAULT_TOKENS;
  return (
    <div style={{position: 'absolute', left: 0, bottom: 0, width: `${pct}%`, height: 6, backgroundColor: tokens.accent, opacity: 0.7}} />
  );
};

export const Short: React.FC<{storyboard: StoryboardSpec}> = ({storyboard}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const theme = resolveTheme(storyboard.theme);
  const scenes = [...storyboard.scenes].sort((a, b) => a.startFrame - b.startFrame);
  const last = scenes[scenes.length - 1];
  const totalFrames = last ? last.startFrame + last.durationInFrames : fps * 30;

  return (
    <AbsoluteFill style={{backgroundColor: theme.background}}>
      {scenes.map((scene) => (
        <Sequence key={scene.sceneId} from={scene.startFrame} durationInFrames={scene.durationInFrames} layout="none">
          <TransitionedScene scene={scene}>
            <KenBurnsContainer durationInFrames={scene.durationInFrames}>
              {renderScene(scene, theme, storyboard.watermark?.text)}
            </KenBurnsContainer>
          </TransitionedScene>
        </Sequence>
      ))}

      {storyboard.narration?.src ? (
        <Audio src={staticFile(storyboard.narration.src)} volume={storyboard.narration.volume ?? 1} />
      ) : null}

      {storyboard.captions && storyboard.captions.length > 0 ? (
        <TiktokCaptions
          words={storyboard.captions}
          highlightColor={theme.accent}
          fontFamily={theme.fontBody || theme.fontHeading}
        />
      ) : (
        <Subtitles cues={storyboard.subtitles ?? []} theme={theme} currentFrame={frame} fps={fps} />
      )}
      <div style={{position: 'absolute', left: 0, right: 0, top: 0, height: 4, backgroundColor: theme.accent, opacity: 0.9}} />
      <ProgressBar theme={theme} totalFrames={totalFrames} />
      <SafeZoneOverlay visible={Boolean((storyboard as {showSafeZone?: boolean}).showSafeZone)} />
    </AbsoluteFill>
  );
};
