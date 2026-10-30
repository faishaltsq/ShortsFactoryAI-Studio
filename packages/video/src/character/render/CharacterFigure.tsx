import React from 'react';
import {useVideoConfig} from 'remotion';
import type {IllustrationActor} from '../../scene-data';
import {mouthShapeFor} from '../ids';
import {speechAt} from '../../speech';
import type {ArtPalette} from '../../art/palette';
import {alpha, mix, tint} from '../../art/palette';
import {characterFrameAt} from '../motion';
import {applyMatrix, indexRig, matrixToSvg, multiply, solveRig} from '../rig';
import type {ClothingVariant} from '../ids';
import type {CharacterFrame, CharacterManifest, CharacterPaint, LayerSpec, ShapeSpec} from '../types';
import type {SpeechWindow} from '../../speech';
import type {MouthShape} from '../ids';
import {Face} from './Face';
import {Hand} from './Hand';

/**
 * Resolve a character's paint roles against the scene palette.
 *
 * Skin, hair, trousers and shoes are identity and stay fixed. Jacket and accent
 * are derived from the scene palette so the character sits inside the film's colour
 * design instead of fighting it — which is also what stops a character library from
 * looking like stickers imported from different projects.
 */
/**
 * Character paint. Identity comes from the manifest's own palette, full stop.
 *
 * The theme colors the environment, the text and the props — never the character's clothing.
 * Recolouring identity clothing per scene made the same character a different character in every
 * shot, which broke per-scene identity hashing and any QC that compared them. ``figureAccent``
 * remains available to the *scene* (props, UI accents), not to the body.
 */
const paintFor = (manifest: CharacterManifest, _palette: ArtPalette): CharacterPaint => {
  const p = manifest.palette;
  return {
    skin: p.skin,
    skinShade: p.skinShade,
    hair: p.hair,
    hairShade: p.hairShade,
    jacket: p.jacket,
    jacketShade: p.jacketShade,
    jacketLight: p.jacketLight,
    shirt: p.shirt,
    shirtShade: p.shirtShade,
    trousers: p.trousers,
    trousersShade: p.trousersShade,
    shoe: p.shoe,
    shoeSole: p.shoeSole,
    ink: p.ink,
    accent: p.accent,
  };
};

/**
 * The layer tree for a clothing variant. `default` is the manifest's own tree; any other declared
 * variant must resolve to real art, and a variant the manifest does not declare falls back to
 * `default` rather than rendering a half-dressed character.
 */
const variantLayers = (manifest: CharacterManifest, variant: ClothingVariant): LayerSpec[] => {
  if (!manifest.clothingVariants.includes(variant)) return manifest.layers;
  if (variant === 'default') return manifest.layers;
  const override = manifest.variantLayers;
  const layers = override?.[variant];
  return layers && layers.length > 0 ? layers : manifest.layers;
};

const renderShape = (shape: ShapeSpec, paint: CharacterPaint, key: string): React.ReactNode => {
  const common = {
    key,
    fill: shape.fill && shape.fill !== 'none' ? paint[shape.fill] : 'none',
    stroke: shape.stroke ? paint[shape.stroke] : undefined,
    strokeWidth: shape.strokeWidth,
    opacity: shape.opacity,
    strokeLinejoin: 'round' as const,
    strokeLinecap: 'round' as const,
  };
  switch (shape.kind) {
    case 'path':
      return <path d={shape.d} {...common} />;
    case 'ellipse':
      return <ellipse cx={shape.cx} cy={shape.cy} rx={shape.rx} ry={shape.ry} {...common} />;
    case 'rect':
      return <rect x={shape.x} y={shape.y} width={shape.width} height={shape.height} rx={shape.rx} {...common} />;
    default:
      return null;
  }
};

/**
 * CharacterFigure — the rigged renderer.
 *
 * Placement contract matches the procedural `Figure` so `Stage` can swap between
 * them without touching camera, shots or safe areas: `x` and `ground` are fractions
 * of the 1080×1920 frame, `scale` multiplies a 0.52·1920 reference height.
 */
export const CharacterFigure: React.FC<{
  actor: IllustrationActor;
  palette: ArtPalette;
  frame: number;
  index: number;
  manifest: CharacterManifest;
  /** Scene-absolute frame, so an actor's blink phase does not reset per shot. */
  sceneFrame?: number;
  fit?: 'frame' | 'box';
  /** Multiplier on the figure's own opacity. `motion.beats[].kind: 'exit'` uses it; default 1. */
  opacity?: number;
  /** Measured word windows, scene-local. Drives the mouth; absent means it stays closed. */
  speech?: readonly SpeechWindow[];
}> = ({actor, palette, frame, index, manifest, sceneFrame, fit = 'frame', opacity = 1, speech}) => {
  const {fps} = useVideoConfig();
  const rig = React.useMemo(() => indexRig(manifest.rig), [manifest]);
  // The selected clothing variant is part of identity: it picks which art tree renders, so a
  // `shirt` Maya is a different garment on the same rig rather than a recoloured `default`.
  const layers = React.useMemo(
    () => (actor.clothing_variant && actor.clothing_variant !== 'default'
      ? variantLayers(manifest, actor.clothing_variant)
      : manifest.layers),
    [manifest, actor.clothing_variant],
  );
  const paint = React.useMemo(() => paintFor(manifest, palette), [manifest, palette]);
  const clipId = `cf-${manifest.id}-${index}`.replace(/[^a-zA-Z0-9_-]/g, '-');

  const renderLayer = (layer: LayerSpec): React.ReactNode => {
    const matrix = world.get(layer.bone);
    if (!matrix) return null;
    return (
      <g transform={matrixToSvg(matrix)} opacity={layer.opacity}>
        {layer.shapes.map((shape, shapeIndex) => renderShape(shape, paint, `${layer.id}-${shapeIndex}`))}
        {layer.far
          ? layer.shapes.map((shape, shapeIndex) =>
              renderShape({...shape, fill: 'ink', stroke: undefined, opacity: 0.1}, paint, `${layer.id}-far-${shapeIndex}`),
            )
          : null}
        {layer.bone === 'head' && layer.id === 'head' && manifest.face ? (
          <Face
            expression={characterFrame.expression}
            anchor={manifest.face.anchor}
            width={manifest.face.width}
            height={manifest.face.height}
            turn={manifest.face.turn ?? 0}
            palette={{ink: paint.ink, skinShade: paint.skinShade, blush: tint(paint.accent, 0.15), sclera: '#fbf6ef'}}
            mouthShape={mouthShape}
          />
        ) : null}
      </g>
    );
  };

  // The mouth shape is a rendering of the measured envelope: the same amplitude that opens the
  // mouth also selects its band. Outside speech the shape is `closed`, which is the only honest
  // answer when there is no measurement to render.
  const mouthShape: MouthShape = mouthShapeFor(speechAt(speech ?? [], sceneFrame ?? frame, fps).weight);
  const characterFrame: CharacterFrame = characterFrameAt({
    input: {
      pose: actor.pose,
      expression: actor.expression ?? 'neutral',
      gesture: actor.gesture ?? 'none',
      motion: actor.motion,
      // Deterministic per-actor offset: two characters in one shot never blink,
      // breathe or sway in lockstep.
      seed: index * 37 + (sceneFrame ?? 0) * 0.0001,
      speech,
      // The windows are scene-local and so is `sceneFrame`, so the envelope is evaluated against
      // the scene clock. Using the shot-local `frame` here would re-open the mouth on every cut.
      speechFrame: sceneFrame ?? frame,
    },
    frame,
    fps,
    durationInFrames: actor.motion?.durationInFrames ?? 300,
    pivot: (bone) => rig.pivots.get(bone),
  });

  const world = solveRig(
    rig,
    characterFrame.angles,
    {x: characterFrame.hips.x, y: characterFrame.hips.y - characterFrame.lift},
    characterFrame.lean,
  );

  // Sole position: the lower of the two feet, in world space. A sit or a step must
  // not leave the shadow behind at the rest position.
  const shadow = (() => {
    const soles = (['footNear', 'footFar'] as const).map((bone) => {
      const matrix = world.get(bone);
      const pivot = rig.pivots.get(bone);
      if (!matrix || !pivot) return null;
      return applyMatrix(matrix, {x: pivot.x, y: pivot.y + 44});
    }).filter((point): point is {x: number; y: number} => point !== null);
    if (soles.length === 0) return {x: manifest.viewBox.width / 2, y: manifest.groundY};
    return {
      x: soles.reduce((sum, point) => sum + point.x, 0) / soles.length,
      y: Math.min((manifest.viewBox.minY ?? 0) + manifest.viewBox.height + 8, Math.max(...soles.map((point) => point.y)) + 2),
    };
  })();

  const heightPx = 0.52 * 1920 * actor.scale;
  const widthPx = (heightPx * manifest.viewBox.width) / manifest.viewBox.height;
  const placement =
    fit === 'box'
      ? {left: `${actor.x * 100}%`, top: `${actor.ground * 100}%`, width: '100%', height: '100%', transform: 'translate(-50%, -100%)'}
      : {left: actor.x * 1080 - widthPx / 2, top: actor.ground * 1920 - heightPx, width: widthPx, height: heightPx};

  const handArt = (bone: 'handNear' | 'handFar'): React.ReactNode => {
    const matrix = world.get(bone);
    if (!matrix || !manifest.hands) return null;
    // Hand art is authored at the wrist origin pointing down +y, so the bone matrix
    // is composed with a translation to the pivot before it is applied.
    const pivot = rig.pivots.get(bone)!;
    // Hand art is authored hanging straight down from the wrist. The bone matrix
    // already carries the arm's rotation, so the art only needs the pivot shift.
    return (
      <g transform={matrixToSvg(multiply(matrix, [1, 0, 0, 1, pivot.x, pivot.y]))}>
        <Hand
          pose={bone === 'handNear' ? characterFrame.hands.near : characterFrame.hands.far}
          length={manifest.hands.length}
          width={manifest.hands.width}
          skin={paint.skin}
          shade={paint.skinShade}
          ink={paint.ink}
        />
      </g>
    );
  };

  // Layers and hands share one z-sorted draw list, so the near hand can paint over
  // the sleeve while the far hand still sits behind the torso.
  const drawables: {z: number; node: React.ReactNode; key: string}[] = [
    ...layers.map((layer) => ({z: layer.z, key: layer.id, node: renderLayer(layer)})),
    ...(manifest.hands
      ? [
          {z: manifest.hands.zFar, key: 'hand-far', node: handArt('handFar')},
          {z: manifest.hands.zNear, key: 'hand-near', node: handArt('handNear')},
        ]
      : []),
  ].sort((a, b) => a.z - b.z);

  return (
    <div
      style={{
        position: 'absolute',
        ...placement,
        opacity: characterFrame.opacity * opacity,
        transform: `${placement.transform ?? ''} scaleX(${actor.facing === 'left' ? -1 : 1})`,
        transformOrigin: '50% 100%',
      }}
    >
      <svg
        viewBox={`${manifest.viewBox.minX ?? 0} ${manifest.viewBox.minY ?? 0} ${manifest.viewBox.width} ${manifest.viewBox.height}`}
        style={{width: '100%', height: '100%', overflow: 'visible'}}
        aria-hidden="true"
      >
        <defs>
          <clipPath id={`${clipId}-body`}>
            <rect
              x={manifest.viewBox.minX ?? 0}
              y={manifest.viewBox.minY ?? 0}
              width={manifest.viewBox.width}
              height={manifest.viewBox.height}
            />
          </clipPath>
        </defs>
        {/* Contact shadow follows the planted soles, so a sit or a step never leaves
            the shadow behind at the rest position. */}
        <ellipse
          cx={shadow.x}
          cy={shadow.y}
          rx={manifest.viewBox.width * 0.17}
          ry={manifest.viewBox.height * 0.011}
          fill={alpha(palette.ink, 0.4)}
        />
        <g clipPath={`url(#${clipId}-body)`}>
          {drawables.map((entry) => <React.Fragment key={entry.key}>{entry.node}</React.Fragment>)}
        </g>
      </svg>
    </div>
  );
};
