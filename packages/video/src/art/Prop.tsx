import React from 'react';
import {alpha, isLight, mix, shade, type ArtPalette} from './palette';

/**
 * The three landscape shapes `ParallaxStory` layers, at 100x100 local units.
 *
 * These are geography, not characters: a ridge, a skyline, and a moon. Anything that needs to be
 * *explained* (a chip, a rack, a satellite) belongs in `art/objects.tsx`, where it can animate its
 * own parts. This file is deliberately limited to the shapes a depth stack is made of.
 */

export type LandscapeShape = 'ridge' | 'city' | 'circle';

const BOX = 100;

const Ridge: React.FC<{palette: ArtPalette}> = ({palette: p}) => {
  const light = isLight(p.skyTop);
  return (
    <g>
      <path
        d="M0 100 L0 62 L18 40 L34 58 L52 26 L70 54 L84 38 L100 60 L100 100 Z"
        fill={light ? mix(p.groundFar, p.prop, 0.25) : shade(p.groundFar, 0.15)}
      />
      <path
        d="M0 100 L0 78 L22 56 L44 76 L64 52 L86 74 L100 66 L100 100 Z"
        fill={light ? mix(p.ground, p.prop, 0.15) : shade(p.ground, 0.1)}
      />
    </g>
  );
};

const City: React.FC<{palette: ArtPalette}> = ({palette: p}) => {
  const light = isLight(p.skyTop);
  return (
    <g>
      {[
        [4, 52, 14],
        [22, 34, 12],
        [38, 62, 10],
        [52, 24, 16],
        [72, 44, 12],
        [88, 56, 10],
      ].map(([x, y, w], i) => (
        <g key={i}>
          <rect
            x={x}
            y={y}
            width={w}
            height={BOX - y}
            fill={light ? mix(p.ground, p.prop, 0.35 + (i % 3) * 0.1) : shade(p.primary, 0.35 + (i % 3) * 0.08)}
          />
          {Array.from({length: Math.floor((BOX - y) / 12)}, (_, r) => (
            <rect
              key={r}
              x={(x as number) + 2}
              y={(y as number) + 5 + r * 12}
              width={(w as number) - 4}
              height={4}
              fill={alpha(p.accent, 0.55)}
            />
          ))}
        </g>
      ))}
    </g>
  );
};

const Disc: React.FC<{palette: ArtPalette}> = ({palette: p}) => (
  <g>
    <circle cx={50} cy={50} r={46} fill={p.glow} />
    <circle cx={50} cy={50} r={30} fill={p.prop} />
  </g>
);

const SHAPES: Record<LandscapeShape, React.FC<{palette: ArtPalette}>> = {
  ridge: Ridge,
  city: City,
  circle: Disc,
};

export const Prop: React.FC<{
  shape: LandscapeShape;
  palette: ArtPalette;
  /** Fill the parent box rather than the whole frame. A parallax layer is always in a box. */
  fit?: 'frame' | 'box';
}> = ({shape, palette}) => {
  const Shape = SHAPES[shape] ?? Disc;
  return (
    <div style={{position: 'absolute', inset: 0}}>
      <svg viewBox={`0 0 ${BOX} ${BOX}`} preserveAspectRatio="none" style={{width: '100%', height: '100%'}} aria-hidden="true">
        <Shape palette={palette} />
      </svg>
    </div>
  );
};
