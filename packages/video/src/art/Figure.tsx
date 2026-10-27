import React from 'react';
import {interpolate, spring, useVideoConfig} from 'remotion';
import type {IllustrationActor, Pose} from '../scene-data';
import {alpha, shade, tint, type ArtPalette} from './palette';

interface Joints {torso: number; head: number; armL: number; armR: number; legL: number; legR: number; hipY: number}

const POSES: Record<Pose, Joints> = {
  stand: {torso: 0, head: 0, armL: 8, armR: -8, legL: 4, legR: -4, hipY: 0},
  point: {torso: -3, head: -6, armL: 10, armR: -95, legL: 5, legR: -5, hipY: 0},
  reach: {torso: -8, head: -10, armL: 14, armR: -140, legL: 6, legR: -6, hipY: -4},
  walk: {torso: 4, head: 2, armL: 26, armR: -30, legL: 20, legR: -20, hipY: -2},
  lookUp: {torso: -2, head: -18, armL: 10, armR: -10, legL: 4, legR: -4, hipY: 0},
  shrug: {torso: 0, head: 4, armL: 62, armR: -62, legL: 6, legR: -6, hipY: 0},
  sit: {torso: 6, head: 2, armL: 30, armR: -30, legL: 84, legR: 76, hipY: 26},
};

const SHOULDER = {left: {x: 74, y: 176}, right: {x: 126, y: 176}};
const HIP = {left: {x: 86, y: 286}, right: {x: 114, y: 286}};

/** angle 0 points straight down; positive swings toward the viewer's left. */
const limbEnd = (from: {x: number; y: number}, length: number, angle: number) => {
  const rad = Math.PI / 2 + (angle * Math.PI) / 180;
  return {x: from.x + Math.cos(rad) * length, y: from.y + Math.sin(rad) * length};
};

const Limb: React.FC<{
  from: {x: number; y: number};
  upper: number;
  lower: number;
  angle: number;
  width: number;
  color: string;
  cap: 'hand' | 'foot';
  capColor: string;
}> = ({from, upper, lower, angle, width, color, cap, capColor}) => {
  const knee = limbEnd(from, upper, angle);
  const tip = limbEnd(knee, lower, angle * 0.6);
  return (
    <g>
      <g stroke={color} strokeWidth={width} strokeLinecap="round" fill="none">
        <line x1={from.x} y1={from.y} x2={knee.x} y2={knee.y} />
        <line x1={knee.x} y1={knee.y} x2={tip.x} y2={tip.y} />
      </g>
      {cap === 'foot' ? (
        // Shoe: a sole plus a toe box, so the leg does not end in a bare stroke.
        <g fill={capColor}>
          <ellipse cx={tip.x} cy={tip.y + width * 0.18} rx={width * 0.86} ry={width * 0.36} />
          <rect x={tip.x - width * 0.5} y={tip.y - width * 0.2} width={width * 1.05} height={width * 0.42} rx={width * 0.2} />
        </g>
      ) : (
        // Mitten: palm plus a thumb nub reads as a hand at 1080px wide.
        <g fill={capColor}>
          <circle cx={tip.x} cy={tip.y} r={width * 0.78} />
          <ellipse cx={tip.x - width * 0.55} cy={tip.y + width * 0.34} rx={width * 0.34} ry={width * 0.5} transform={`rotate(-30 ${tip.x} ${tip.y})`} />
        </g>
      )}
    </g>
  );
};

export const Figure: React.FC<{
  actor: IllustrationActor;
  palette: ArtPalette;
  frame: number;
  index: number;
  /**
   * 'frame' (default) places the figure in 1080x1920 stage coordinates, which is what
   * Stage needs. 'box' places it relative to its parent, for embedding in a panel.
   */
  fit?: 'frame' | 'box';
  /** Multiplier on the figure's own opacity. `motion.beats[].kind: 'exit'` uses it; default 1. */
  opacity?: number;
}> = ({actor, palette, frame, index, fit = 'frame', opacity: opacityScale = 1}) => {
  const {fps} = useVideoConfig();
  const pose = POSES[actor.pose] ?? POSES.stand;
  const walk = actor.pose === 'walk' ? Math.sin(frame / 5.4) * 24 : 0;
  const breathe = Math.sin(frame / 26 + index) * 1.6;
  const sway = Math.sin(frame / 19 + index) * 0.7;

  // spring() with a negative frame is undefined behaviour; clamp before calling it.
  const enterRaw = spring({frame: Math.max(0, frame - index * 4), fps, config: {damping: 14, stiffness: 130, mass: 0.9}});
  const enter = Number.isFinite(enterRaw) ? Math.min(1, Math.max(0, enterRaw)) : 1;
  const entranceOpacity = interpolate(frame, [0, 10], [0, 1], {extrapolateRight: 'clamp'});

  const body = actor.tone === 'accent' ? palette.figureAccent : actor.tone === 'secondary' ? palette.prop : palette.figure;
  const ink = actor.silhouette ? shade(palette.ink, 0.1) : body;
  const limbColor = actor.silhouette ? ink : shade(body, 0.18);
  const skin = actor.silhouette ? ink : tint(body, 0.18);
  const rim = alpha(tint(palette.figure, 0.7), 0.55);

  const blink = (frame + index * 37) % 97 < 4;
  const heightPx = 0.52 * 1920 * actor.scale;
  const widthPx = (heightPx * 200) / 430;
  const placement =
    fit === 'box'
      ? {left: `${actor.x * 100}%`, top: `${actor.ground * 100}%`, width: '100%', height: '100%', transform: 'translate(-50%, -100%)'}
      : {left: actor.x * 1080 - widthPx / 2, top: actor.ground * 1920 - heightPx, width: widthPx, height: heightPx};

  return (
    <div
      style={{
        position: 'absolute',
        ...placement,
        opacity: entranceOpacity * enter * opacityScale,
        transform: `${placement.transform ?? ''} translateY(${(1 - enter) * 40}px) rotate(${sway}deg) scaleX(${actor.facing === 'left' ? -1 : 1})`,
        transformOrigin: '50% 100%',
      }}
    >
      <svg viewBox="0 0 200 430" style={{width: '100%', height: '100%'}} aria-hidden="true">
        <ellipse cx={100} cy={418} rx={54} ry={9} fill={alpha(palette.ink, 0.38)} />
        <g transform={`translate(0 ${pose.hipY + breathe})`}>
          <Limb from={HIP.left} upper={68} lower={66} angle={pose.legL + walk} width={22} color={limbColor} cap="foot" capColor={shade(body, 0.42)} />
          <Limb from={HIP.right} upper={68} lower={66} angle={pose.legR - walk} width={22} color={limbColor} cap="foot" capColor={shade(body, 0.42)} />
          <rect x={66} y={152} width={68} height={140} rx={30} fill={ink} transform={`rotate(${pose.torso} 100 290)`} />
          {/* Rim light from the scene's key light keeps a flat figure from reading as a sticker. */}
          <rect x={66} y={152} width={12} height={140} rx={6} fill={rim} transform={`rotate(${pose.torso} 100 290)`} />
          <Limb from={SHOULDER.left} upper={64} lower={58} angle={pose.armL - walk * 0.7} width={20} color={limbColor} cap="hand" capColor={skin} />
          <Limb from={SHOULDER.right} upper={64} lower={58} angle={pose.armR + walk * 0.7} width={20} color={limbColor} cap="hand" capColor={skin} />
          <g transform={`rotate(${pose.torso + pose.head} 100 152)`}>
            <circle cx={100} cy={116} r={42} fill={ink} />
            {/* Hair: a single cap that hugs the skull. The earlier crescent read as a glitch. */}
            <path d="M59 108 A41 41 0 0 1 141 108 Q120 92 100 92 Q80 92 59 108Z" fill={shade(body, 0.34)} />
            {/* Rim light: a short arc on the key-light edge only, never across the face. */}
            <path d="M63 100 A40 40 0 0 1 92 77" stroke={rim} strokeWidth={5} fill="none" strokeLinecap="round" />
            {actor.silhouette ? null : (
              <g>
                {blink ? (
                  <g stroke={palette.ink} strokeWidth={4} strokeLinecap="round">
                    <line x1={82} y1={112} x2={92} y2={112} />
                    <line x1={108} y1={112} x2={118} y2={112} />
                  </g>
                ) : (
                  <g fill={palette.ink}>
                    <ellipse cx={87} cy={111} rx={5} ry={6.5} />
                    <ellipse cx={113} cy={111} rx={5} ry={6.5} />
                  </g>
                )}
                <path d="M90 132 Q100 140 110 132" stroke={palette.ink} strokeWidth={4} strokeLinecap="round" fill="none" />
              </g>
            )}
          </g>
        </g>
      </svg>
    </div>
  );
};
