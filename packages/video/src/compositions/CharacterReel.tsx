import React from 'react';
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import type {ThemeSpec} from '../types';
import type {ExpressionId, GestureId, MotionPreset, PoseId} from '../character/ids';
import {CharacterFigure} from '../character/render/CharacterFigure';
import {getCharacter, resolveCharacter} from '../character/registry';
import {paletteFor} from '../art/palette';
import {Camera, cameraAt} from '../art/Camera';
import {Effects} from '../art/Effects';
import {Environment} from '../art/Environment';
import {Figure} from '../art/Figure';
import type {IllustrationActor} from '../scene-data';

interface Beat {
  label: string;
  pose: PoseId;
  expression: ExpressionId;
  gesture: GestureId;
  preset: MotionPreset;
  framing: 'wide' | 'medium' | 'close';
  camera: 'static' | 'pushIn' | 'pullOut' | 'handheld' | 'panRight';
  fromPose?: PoseId;
  fromExpression?: ExpressionId;
}

/**
 * The reel script. Twelve beats, each 2 seconds at 30 fps, chosen so every capability
 * of the engine is visible at least once: all seven poses, five expressions, six
 * gestures, all seven motion presets, and all three framings.
 */
export const REEL_BEATS: Beat[] = [
  {label: '1 · idle, wide', pose: 'stand', expression: 'neutral', gesture: 'none', preset: 'idle', framing: 'wide', camera: 'static'},
  {label: '2 · enter, medium', pose: 'stand', expression: 'curious', gesture: 'none', preset: 'enter', framing: 'medium', camera: 'pushIn'},
  {label: '3 · talk, close', pose: 'stand', expression: 'neutral', gesture: 'openPalm', preset: 'talk', framing: 'close', camera: 'static'},
  {label: '4 · point + determined', pose: 'point', expression: 'determined', gesture: 'pointForward', preset: 'gesture', framing: 'medium', camera: 'panRight'},
  {label: '5 · pose change', pose: 'point', expression: 'happy', gesture: 'none', preset: 'poseChange', framing: 'medium', camera: 'static', fromPose: 'stand', fromExpression: 'curious'},
  {label: '6 · walk, wide', pose: 'walk', expression: 'neutral', gesture: 'none', preset: 'walk', framing: 'wide', camera: 'static'},
  {label: '7 · reaction', pose: 'lookUp', expression: 'surprised', gesture: 'none', preset: 'react', framing: 'medium', camera: 'handheld'},
  {label: '8 · both palms', pose: 'stand', expression: 'happy', gesture: 'bothOpen', preset: 'talk', framing: 'medium', camera: 'static'},
  {label: '9 · wave, close', pose: 'stand', expression: 'happy', gesture: 'wave', preset: 'gesture', framing: 'close', camera: 'static'},
  {label: '10 · think', pose: 'sit', expression: 'thinking', gesture: 'think', preset: 'idle', framing: 'medium', camera: 'static'},
  {label: '11 · concern', pose: 'shrug', expression: 'concerned', gesture: 'shrug', preset: 'talk', framing: 'medium', camera: 'pushIn'},
  {label: '12 · reach, close', pose: 'reach', expression: 'surprised', gesture: 'openPalm', preset: 'gesture', framing: 'close', camera: 'pullOut'},
];

const BEAT_FRAMES = 60;

const actorFor = (beat: Beat, character: string): IllustrationActor => ({
  pose: beat.pose,
  x: 0.5,
  ground: 0.88,
  scale: beat.framing === 'close' ? 1.3 : beat.framing === 'medium' ? 1.08 : 0.9,
  facing: 'right',
  tone: 'primary',
  silhouette: false,
  character,
  expression: beat.expression,
  gesture: beat.gesture,
  motion: {
    preset: beat.preset,
    durationInFrames: BEAT_FRAMES,
    intensity: 0.6,
    ...(beat.fromPose ? {fromPose: beat.fromPose} : {}),
    ...(beat.fromExpression ? {fromExpression: beat.fromExpression} : {}),
  },
});

// Gentle: the stage anchors at the ground line, so a larger factor crops the crown.
const FRAMING_SCALE = {wide: 1, medium: 1.06, close: 1.16} as const;

/**
 * CharacterReel — the visual QA surface.
 *
 * Each beat renders through the real pipeline (environment, camera, effects) rather
 * than on a flat card, because a character that only looks right on a white
 * background is not integrated. `compare` swaps the character renderer for the
 * procedural Figure on the same beat, which is the before/after comparison.
 */
export const CharacterReel: React.FC<{
  theme: ThemeSpec;
  characterId?: string;
  compare?: boolean;
}> = ({theme, characterId = 'maya', compare = false}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const palette = paletteFor(theme, 'day');
  const {character} = resolveCharacter(characterId);
  const manifest = character ?? getCharacter('maya')!;
  const beatIndex = Math.min(REEL_BEATS.length - 1, Math.floor(frame / BEAT_FRAMES));
  const beat = REEL_BEATS[beatIndex];
  const local = frame - beatIndex * BEAT_FRAMES;
  const camera = cameraAt(beat.camera, local, BEAT_FRAMES);
  const actor = actorFor(beat, manifest.id);

  return (
    <AbsoluteFill style={{backgroundColor: palette.skyTop}}>
      <Camera state={camera}>
        <div style={{position: 'absolute', inset: 0, transform: `scale(${FRAMING_SCALE[beat.framing]})`, transformOrigin: '50% 76%'}}>
          <Environment setting="interior" timeOfDay="day" palette={palette} progress={local / BEAT_FRAMES} />
          {compare ? (
            <Figure actor={actor} palette={palette} frame={local} index={0} />
          ) : (
            <CharacterFigure actor={actor} palette={palette} frame={local} index={0} manifest={manifest} sceneFrame={frame} />
          )}
        </div>
      </Camera>
      <Effects list={['vignette']} palette={palette} frame={frame} progress={local / BEAT_FRAMES} />
      <div
        style={{
          position: 'absolute',
          left: 40,
          bottom: 40,
          fontFamily: theme.fontBody,
          fontSize: 26,
          letterSpacing: 1,
          color: palette.figure,
          opacity: 0.75,
        }}
      >
        {compare ? 'BEFORE · procedural Figure' : 'AFTER · Character Engine V2'} — {beat.label}
      </div>
      <div
        style={{
          position: 'absolute',
          right: 40,
          bottom: 40,
          fontFamily: theme.fontBody,
          fontSize: 26,
          color: palette.figure,
          opacity: 0.55,
        }}
      >
        {String(frame).padStart(4, '0')} / {REEL_BEATS.length * BEAT_FRAMES}
      </div>
    </AbsoluteFill>
  );
};

export const REEL_DURATION = REEL_BEATS.length * BEAT_FRAMES;
