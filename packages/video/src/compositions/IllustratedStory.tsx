import React from 'react';
import {useCurrentFrame, useVideoConfig} from 'remotion';
import type {ThemeSpec} from '../types';
import type {IllustrationData} from '../scene-data';
import type {SceneProps} from '../components/NarrativeFrame';
import {validateSceneData} from '../scene-data';
import {resolveTheme} from '../themes/brand';
import {Watermark} from '../components/Chrome';
import {slideUp} from '../components/presets';
import {Camera, cameraAt} from '../art/Camera';
import {DeclaredCamera} from '../art/DeclaredCamera';
import {Effects} from '../art/Effects';
import {Stage} from '../art/Stage';
import {FRAMING_SCALE, shotAt} from '../art/shots';
import {paletteFor} from '../art/palette';
import {declaredCameraAt, textAnchorOf} from '../camera';
import {performanceAt, planBeats} from '../motion-beats';

/**
 * IllustratedStory — the character-driven template, and the only one that reads both a declared
 * camera and declared motion beats.
 *
 * Precedence (documented once, in `src/camera.ts`): a declared `scene.camera` owns the transform
 * and its `shot` sets the base framing; otherwise `data.shots[]` keeps doing exactly what it did.
 * Either way `data.shots[]` still selects the shot and its cut, because shot selection is not
 * camera movement.
 */
export const IllustratedStoryScene: React.FC<SceneProps> = ({scene, theme: inputTheme, watermark}) => {
  const theme: ThemeSpec = resolveTheme(inputTheme);
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  validateSceneData(scene);

  const data = scene.data as unknown as IllustrationData;
  const palette = paletteFor(theme, data.timeOfDay ?? 'night');
  const span = shotAt(data.shots, frame, scene.durationInFrames);
  const progress = span.duration <= 1 ? 1 : span.local / (span.duration - 1);
  const title = data.title ?? scene.text.find((t) => t.style.role === 'title')?.text ?? '';
  const kicker = scene.text.find((t) => t.style.role === 'kicker')?.text ?? '';
  const entrance = slideUp({frame: span.local, fps, durationInFrames: 16, intensity: 0.4});
  // An editor titles the establishing shot and lets the close-up play clean: the
  // subject is the message once the frame tightens. Keeping the title on every
  // framing buries the hero under type.
  const showTitle = span.shot.framing === 'wide';

  const beats = React.useMemo(() => planBeats(scene, data.actors), [scene, data.actors]);
  const energy = scene.motion?.energy ?? 0;
  // Beats are scene-local, so they are evaluated against the scene frame, not the shot-local one:
  // a beat at frame 150 must fire at frame 150 even when a cut lands at frame 90.
  const performances = React.useMemo(
    () =>
      data.actors.map((actor, index) =>
        performanceAt(beats, index, frame, actor, energy),
      ),
    [beats, data.actors, frame, energy],
  );

  // A declared camera overrides the per-shot move and the framing scale; `span` still decides the
  // cut. `cameraAt` keeps owning the legacy path untouched.
  const declared = scene.camera;
  const stage = declared
    ? {
        scale: 1,
        camera: declaredCameraAt(declared, frame, scene.durationInFrames, textAnchorOf(scene, declared.target), {
          width,
          height,
        }),
      }
    : {scale: FRAMING_SCALE[span.shot.framing], camera: null};

  const stageNode = (
    <Stage
      data={data}
      palette={palette}
      frame={span.local}
      sceneFrame={frame}
      // A scene that declares beats has to run the rig on the scene clock, because `atFrame` is
      // scene-local. A scene without beats keeps the shot-local clock every existing render was
      // measured against, so adding the field changes nothing for a storyboard that omits it.
      characterFrame={beats.cues.length > 0 ? frame : undefined}
      // Measured word windows are scene-local, so the mouth is driven from the scene clock — the
      // same clock the beats use — not the shot-local one.
      speech={scene.speech}
      progress={progress}
      scale={stage.scale}
      performances={performances}
    />
  );

  return (
    <div style={{position: 'absolute', inset: 0, overflow: 'hidden', background: palette.skyTop}}>
      {stage.camera ? (
        <DeclaredCamera state={stage.camera}>{stageNode}</DeclaredCamera>
      ) : (
        <Camera state={cameraAt(span.shot.camera, span.local, span.duration)}>{stageNode}</Camera>
      )}

      <Effects list={data.fx} palette={palette} frame={frame} progress={progress} />

      {watermark ? <Watermark text={watermark} theme={theme} /> : null}

      {title && showTitle ? (
        <div
          style={{
            ...entrance,
            position: 'absolute',
            top: 268,
            left: 72,
            right: 72,
            fontFamily: theme.fontHeading,
            fontSize: 64,
            lineHeight: 1.08,
            color: theme.primary,
            textShadow: '0 6px 26px rgba(0,0,0,0.65)',
            overflowWrap: 'anywhere',
          }}
        >
          {title}
        </div>
      ) : null}

      {kicker && showTitle ? (
        <div
          style={{
            position: 'absolute',
            top: 232,
            left: 72,
            fontFamily: theme.fontBody,
            fontSize: 30,
            letterSpacing: 5,
            textTransform: 'uppercase',
            color: theme.accent,
            opacity: Math.min(1, span.local / 10),
          }}
        >
          {kicker}
        </div>
      ) : null}

      {data.caption && showTitle ? (
        <div
          style={{
            position: 'absolute',
            top: 400,
            left: 72,
            right: 72,
            fontFamily: theme.fontBody,
            fontSize: 40,
            lineHeight: 1.28,
            color: theme.secondary,
            opacity: Math.min(1, span.local / 12) * 0.95,
          }}
        >
          {data.caption}
        </div>
      ) : null}
    </div>
  );
};
