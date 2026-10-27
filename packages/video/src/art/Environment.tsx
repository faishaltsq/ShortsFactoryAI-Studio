import React from 'react';
import type {Setting, TimeOfDay} from '../scene-data';
import {alpha, mix, shade, type ArtPalette} from './palette';
import {rand} from './rng';

const W = 1080;
const H = 1920;
const HORIZON = 1180;

const Stars: React.FC<{palette: ArtPalette; count: number; seed?: number}> = ({palette, count, seed = 0}) => (
  <g>
    {Array.from({length: count}, (_, i) => {
      const x = rand(seed + i * 3 + 1) * W;
      const y = rand(seed + i * 3 + 2) * HORIZON * 0.92;
      const r = 1 + rand(seed + i * 3 + 3) * 2.6;
      return <circle key={i} cx={x} cy={y} r={r} fill={palette.figure} opacity={0.25 + rand(seed + i) * 0.55} />;
    })}
  </g>
);

const Celestial: React.FC<{palette: ArtPalette; cx: number; cy: number; r: number; crescent?: boolean; glow?: boolean}> = ({
  palette,
  cx,
  cy,
  r,
  crescent,
  glow = true,
}) => (
  <g>
    {glow ? <circle cx={cx} cy={cy} r={r * 2.6} fill={palette.glow} opacity={0.16} /> : null}
    <circle cx={cx} cy={cy} r={r} fill={palette.prop} />
    {crescent ? <circle cx={cx + r * 0.42} cy={cy - r * 0.18} r={r * 0.92} fill={palette.skyTop} /> : null}
  </g>
);

const Ridge: React.FC<{fill: string; opacity: number; y: number; amplitude: number; seed: number; drift: number}> = ({
  fill,
  opacity,
  y,
  amplitude,
  seed,
  drift,
}) => {
  const points = Array.from({length: 9}, (_, i) => {
    const x = (i / 8) * W;
    const height = amplitude * (0.45 + rand(seed + i) * 0.55);
    return `${x.toFixed(0)},${(y - height).toFixed(0)}`;
  });
  return (
    <path
      d={`M0,${H} L0,${y} L${points.join(' L')} L${W},${y} L${W},${H} Z`}
      fill={fill}
      opacity={opacity}
      transform={`translate(${drift} 0)`}
    />
  );
};

const City: React.FC<{palette: ArtPalette; drift: number}> = ({palette, drift}) => {
  const blocks = [
    {x: -60, w: 180, h: 540}, {x: 96, w: 140, h: 700}, {x: 210, w: 200, h: 460},
    {x: 386, w: 160, h: 640}, {x: 522, w: 210, h: 520}, {x: 706, w: 150, h: 720},
    {x: 836, w: 190, h: 480}, {x: 1000, w: 160, h: 600},
  ];
  return (
    <g transform={`translate(${drift} 0)`}>
      {blocks.map((b, bi) => {
        const top = HORIZON - b.h;
        const cols = Math.max(1, Math.floor((b.w - 24) / 34));
        const rows = Math.max(1, Math.floor((b.h - 40) / 44));
        return (
          <g key={bi}>
            <rect x={b.x} y={top} width={b.w} height={b.h} fill={shade(palette.ground, 0.35)} />
            {Array.from({length: cols * rows}, (_, ci) => {
              const cx = b.x + 16 + (ci % cols) * 34;
              const cy = top + 26 + Math.floor(ci / cols) * 44;
              const lit = rand(bi * 1000 + ci) > 0.45;
              return <rect key={ci} x={cx} y={cy} width={16} height={22} fill={lit ? palette.figureAccent : palette.ink} opacity={lit ? 0.72 : 0.5} />;
            })}
          </g>
        );
      })}
    </g>
  );
};

const Body: React.FC<{setting: Setting; palette: ArtPalette; progress: number; drift: number}> = ({setting, palette, progress, drift}) => {
  switch (setting) {
    case 'space':
      return (
        <g>
          <ellipse cx={W * 0.76} cy={H * 0.3} rx={320} ry={220} fill={palette.figureAccent} opacity={0.07} />
          <ellipse cx={W * 0.24} cy={H * 0.52} rx={260} ry={180} fill={palette.prop} opacity={0.06} />
          <path d={`M0,${H} Q${W * 0.5},${HORIZON - 180} ${W},${H} L${W},${H} Z`} fill={palette.ground} opacity={0.85} transform={`translate(${drift * 0.4} 0)`} />
        </g>
      );
    case 'desert':
      return (
        <g>
          <Celestial palette={palette} cx={W * 0.72} cy={H * 0.24} r={96} />
          <Ridge fill={palette.groundFar} opacity={0.55} y={HORIZON} amplitude={190} seed={11} drift={drift * 0.3} />
          <Ridge fill={palette.ground} opacity={0.95} y={HORIZON + 90} amplitude={140} seed={29} drift={drift * 0.7} />
          {[0, 1, 2].map((i) => (
            <path
              key={i}
              d={`M${120 + i * 300},${HORIZON + 210 + i * 90} q120,-26 240,0`}
              stroke={alpha(palette.figure, 0.12)}
              strokeWidth={4}
              fill="none"
            />
          ))}
        </g>
      );
    case 'city':
      return (
        <g>
          <Celestial palette={palette} cx={W * 0.78} cy={H * 0.2} r={64} crescent />
          <City palette={palette} drift={drift * 0.4} />
          <rect x={0} y={HORIZON} width={W} height={H - HORIZON} fill={shade(palette.ground, 0.5)} />
          <path d={`M0,${HORIZON + 120} L${W},${HORIZON + 40}`} stroke={alpha(palette.figure, 0.14)} strokeWidth={6} />
        </g>
      );
    case 'ocean':
      return (
        <g>
          <Celestial palette={palette} cx={W * 0.5} cy={H * 0.22} r={92} crescent />
          <rect x={0} y={HORIZON} width={W} height={H - HORIZON} fill={shade(palette.ground, 0.15)} />
          {[0, 1, 2, 3, 4].map((i) => (
            <path
              key={i}
              d={`M0,${HORIZON + 60 + i * 120} q270,-48 540,0 t540,0`}
              stroke={alpha(palette.prop, 0.28 - i * 0.04)}
              strokeWidth={8 + i * 3}
              fill="none"
              transform={`translate(${drift * (0.2 + i * 0.15)} 0)`}
            />
          ))}
          <rect x={W * 0.46} y={HORIZON} width={70} height={H - HORIZON} fill={alpha(palette.figureAccent, 0.16)} />
        </g>
      );
    case 'forest':
      return (
        <g>
          <Ridge fill={palette.groundFar} opacity={0.5} y={HORIZON + 40} amplitude={90} seed={41} drift={drift * 0.25} />
          {[0, 1, 2, 3, 4, 5].map((i) => {
            const x = 60 + i * 190 + rand(70 + i) * 60;
            const height = 260 + rand(90 + i) * 220;
            return (
              <g key={i} transform={`translate(${x + drift * 0.5} 0)`}>
                <rect x={-12} y={HORIZON - height * 0.32} width={24} height={height * 0.4} fill={shade(palette.ground, 0.45)} />
                <circle cx={0} cy={HORIZON - height * 0.62} r={height * 0.3} fill={shade(palette.groundFar, 0.2)} opacity={0.92} />
              </g>
            );
          })}
          <rect x={0} y={HORIZON + 60} width={W} height={H - HORIZON} fill={shade(palette.ground, 0.3)} />
        </g>
      );
    case 'interior':
      return (
        <g>
          <rect x={0} y={0} width={W} height={HORIZON} fill={mix(palette.skyBottom, palette.ground, 0.4)} />
          <rect x={0} y={HORIZON} width={W} height={H - HORIZON} fill={shade(palette.ground, 0.28)} />
          <rect x={W * 0.6} y={H * 0.16} width={W * 0.3} height={H * 0.3} fill={alpha(palette.figureAccent, 0.5)} />
          <path d={`M${W * 0.6},${H * 0.46} L${W * 0.2},${H} L${W * 0.9},${H} Z`} fill={alpha(palette.figureAccent, 0.12)} />
          <rect x={W * 0.06} y={H * 0.66} width={W * 0.28} height={H * 0.12} rx={18} fill={shade(palette.ground, 0.42)} />
        </g>
      );
    default:
      return (
        <g opacity={0.75}>
          {[0, 1, 2, 3].map((i) => (
            <circle
              key={i}
              cx={W * 0.5}
              cy={H * 0.46}
              r={180 + i * 150 + progress * 40}
              fill="none"
              stroke={alpha(palette.figureAccent, 0.16 - i * 0.03)}
              strokeWidth={6}
            />
          ))}
          <rect x={0} y={HORIZON + 180} width={W} height={H} fill={alpha(palette.ink, 0.35)} />
        </g>
      );
  }
};

export const Environment: React.FC<{
  setting: Setting;
  timeOfDay: TimeOfDay;
  palette: ArtPalette;
  progress: number;
}> = ({setting, timeOfDay, palette, progress}) => {
  const drift = (progress - 0.5) * 46;
  const gradientId = `sky-${setting}`;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid slice" style={{position: 'absolute', inset: 0, width: '100%', height: '100%'}} aria-hidden="true">
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={palette.skyTop} />
          <stop offset="62%" stopColor={mix(palette.skyTop, palette.skyBottom, 0.72)} />
          <stop offset="100%" stopColor={palette.skyBottom} />
        </linearGradient>
      </defs>
      <rect x={0} y={0} width={W} height={H} fill={`url(#${gradientId})`} />
      {timeOfDay === 'night' ? <Stars palette={palette} count={90} /> : null}
      <Body setting={setting} palette={palette} progress={progress} drift={drift} />
    </svg>
  );
};
