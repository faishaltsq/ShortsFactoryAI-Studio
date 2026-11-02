/**
 * The object library: the visual vocabulary of the informative engine.
 *
 * Every object draws inside a 400x400 local box, uses only theme-derived colours from
 * `palette.ts`, and animates from the frame count it is handed. Nothing here knows about
 * characters, rigs, faces, or narration — an object explains itself and the motion explains the
 * object.
 *
 * The contract for an entry is deliberately narrow: `(palette, frame) -> SVG`. That is what lets a
 * storyboard name `gpu` and get a GPU on screen, and what lets a new object be added without
 * touching a single composition.
 */

import React from 'react';
import {alpha, shade, tint, type ArtPalette} from './palette';
import {OBJECT_KINDS, type ObjectKind} from './object-kinds';

export {OBJECT_CAPTION_Y, OBJECT_KINDS, OBJECT_LABELS, isObjectKind} from './object-kinds';
export type {ObjectKind} from './object-kinds';

/** The one contract every entry satisfies: `(palette, frame) -> SVG`. */
export interface ObjectProps {
  palette: ArtPalette;
  frame: number;
  /** 0..1 within the scene. Used for one-shot arrivals rather than loops. */
  progress: number;
}

/** 0 or 1, flipping every `period` frames, offset by `phase` so neighbours never blink in sync. */
const toggle = (frame: number, period: number, phase: number): number =>
  Math.floor(frame / period + phase) % 2;

/** 0..1 that rises once and holds. `delay` is in frames. */
const arrive = (frame: number, delay: number, span = 18): number => {
  const raw = (frame - delay) / span;
  if (raw <= 0) return 0;
  if (raw >= 1) return 1;
  return raw;
};

/** Rounded-corner rectangle as a path, so a corner radius never depends on `rx` support. */
const panel = (x: number, y: number, w: number, h: number, r: number): string =>
  `M${x + r} ${y} H${x + w - r} Q${x + w} ${y} ${x + w} ${y + r} ` +
  `V${y + h - r} Q${x + w} ${y + h} ${x + w - r} ${y + h} ` +
  `H${x + r} Q${x} ${y + h} ${x} ${y + h - r} ` +
  `V${y + r} Q${x} ${y} ${x + r} ${y} Z`;

const bezel = (p: ArtPalette): string => shade(p.primary, 0.22);
const shell = (p: ArtPalette): string => shade(p.primary, 0.08);
const metal = (p: ArtPalette): string => tint(p.ink, 0.16);
const dark = (p: ArtPalette): string => shade(p.primary, 0.5);

/** A lit indicator. `on` is 0..1 so a dim state still reads as an unlit indicator. */
const Led: React.FC<{x: number; y: number; r: number; on: number; color: string; off: string}> = ({
  x,
  y,
  r,
  on,
  color,
  off,
}) => (
  <g>
    <circle cx={x} cy={y} r={r} fill={off} />
    <circle cx={x} cy={y} r={r} fill={color} opacity={0.25 + 0.75 * on} />
    <circle cx={x} cy={y} r={r * 2.4} fill={color} opacity={0.12 * on} />
  </g>
);

// ---------------------------------------------------------------------------------------------
// Computing
// ---------------------------------------------------------------------------------------------

/**
 * A GPU package: substrate, die, memory stacks, pins. The scan band crosses the die so the object
 * reads as *working* rather than as a picture of a chip.
 */
const Gpu: React.FC<ObjectProps> = ({palette: p, frame}) => {
  const scan = 0.5 + 0.5 * Math.sin(frame / 11);
  const dieTop = 118;
  const dieH = 164;
  return (
    <svg viewBox="0 0 400 400" width="100%" height="100%" aria-hidden="true">
      <ellipse cx={200} cy={352} rx={128} ry={18} fill={alpha(p.ink, 0.34)} />
      {/* substrate */}
      <path d={panel(64, 92, 272, 236, 16)} fill={bezel(p)} />
      <path d={panel(80, 106, 240, 208, 12)} fill={shell(p)} />
      {/* pin rows */}
      {Array.from({length: 11}, (_, i) => {
        const x = 96 + i * 20;
        return (
          <g key={`pin-${i}`}>
            <rect x={x} y={78} width={10} height={16} rx={3} fill={metal(p)} />
            <rect x={x} y={306} width={10} height={16} rx={3} fill={metal(p)} />
          </g>
        );
      })}
      {/* die */}
      <rect x={122} y={dieTop} width={156} height={dieH} rx={6} fill={dark(p)} />
      <rect x={132} y={dieTop + 10} width={136} height={dieH - 20} rx={4} fill={shade(p.accent, 0.12)} />
      {/* the scan band: the die is busy */}
      <rect
        x={132}
        y={dieTop + 10 + (dieH - 20) * scan - 12}
        width={136}
        height={24}
        fill={tint(p.accent, 0.55)}
        opacity={0.55}
      />
      {/* memory stacks either side of the die */}
      {[0, 1, 2].map((i) => (
        <g key={`vram-${i}`}>
          <rect x={92} y={148 + i * 34} width={22} height={24} rx={3} fill={metal(p)} />
          <rect x={286} y={148 + i * 34} width={22} height={24} rx={3} fill={metal(p)} />
        </g>
      ))}
      <Led x={104} y={98} r={4} on={toggle(frame, 9, 0)} color={p.accent} off={dark(p)} />
      <Led x={296} y={98} r={4} on={toggle(frame, 9, 1)} color={p.accent} off={dark(p)} />
    </svg>
  );
};

/** A rack of server units with blinking activity LEDs and air moving through the front. */
const ServerRack: React.FC<ObjectProps> = ({palette: p, frame}) => {
  const units = 8;
  const drift = (frame / 90) % 1;
  return (
    <svg viewBox="0 0 400 400" width="100%" height="100%" aria-hidden="true">
      <ellipse cx={200} cy={372} rx={104} ry={14} fill={alpha(p.ink, 0.32)} />
      <path d={panel(104, 24, 192, 344, 12)} fill={bezel(p)} />
      <path d={panel(114, 34, 172, 324, 8)} fill={shade(p.primary, 0.34)} />
      {Array.from({length: units}, (_, i) => {
        const y = 44 + i * 39;
        const active = toggle(frame, 6 + i, i * 1.7);
        const busy = toggle(frame, 4 + (i % 3), i * 0.9);
        return (
          <g key={`unit-${i}`}>
            <rect x={122} y={y} width={156} height={32} rx={4} fill={shell(p)} />
            {/* vent slots */}
            {Array.from({length: 9}, (_, k) => (
              <rect key={`v-${k}`} x={130 + k * 9} y={y + 7} width={4} height={18} rx={2} fill={shade(p.primary, 0.55)} />
            ))}
            <Led x={258} y={y + 10} r={3.4} on={active} color={p.accent} off={dark(p)} />
            <Led x={270} y={y + 10} r={3.4} on={busy} color={tint(p.accent, 0.4)} off={dark(p)} />
          </g>
        );
      })}
      {/* airflow: a soft band that travels down the front, so the rack is not a still picture */}
      <rect x={122} y={44 + drift * 300} width={156} height={26} fill={tint(p.accent, 0.6)} opacity={0.14} />
    </svg>
  );
};

/** An isometric data hall: a floor, two rows of racks, a cable tray, and roaming packets. */
const DataCenter: React.FC<ObjectProps> = ({palette: p, frame}) => {
  const rack = (x: number, y: number, phase: number): React.ReactNode => (
    <g key={`rack-${x}-${y}`}>
      <path d={panel(x, y, 52, 74, 4)} fill={bezel(p)} />
      {Array.from({length: 6}, (_, i) => (
        <rect key={i} x={x + 6} y={y + 8 + i * 10} width={40} height={6} rx={2} fill={shade(p.primary, 0.38)} />
      ))}
      <Led x={x + 44} y={y + 8} r={2.6} on={toggle(frame, 8 + phase, phase)} color={p.accent} off={dark(p)} />
    </g>
  );
  return (
    <svg viewBox="0 0 400 400" width="100%" height="100%" aria-hidden="true">
      {/* floor plate */}
      <path d="M40 250 L200 178 L360 250 L200 322 Z" fill={shade(p.primary, 0.3)} />
      <path d="M40 250 L200 178 L200 322 Z" fill={shade(p.primary, 0.4)} />
      {/* back row, smaller: depth cue */}
      {[0, 1, 2, 3].map((i) => rack(74 + i * 62, 196, i))}
      {/* front row */}
      {[0, 1, 2].map((i) => rack(96 + i * 66, 244, i + 4))}
      {/* cable tray arcing overhead */}
      <path
        d="M60 176 Q200 116 340 176"
        fill="none"
        stroke={metal(p)}
        strokeWidth={7}
        strokeLinecap="round"
        opacity={0.9}
      />
      {/* packets travelling the tray */}
      {Array.from({length: 4}, (_, i) => {
        const t = ((frame / 44) + i / 4) % 1;
        const x = 60 + t * 280;
        const y = 176 - Math.sin(t * Math.PI) * 60;
        return <circle key={`pkt-${i}`} cx={x} cy={y} r={5} fill={p.accent} opacity={0.85} />;
      })}
    </svg>
  );
};

/** A chip die close-up: the object a GPU explainer cuts to when the narration says "transistor". */
const Wafer: React.FC<ObjectProps> = ({palette: p, frame}) => {
  const sweep = (frame / 70) % 1;
  return (
    <svg viewBox="0 0 400 400" width="100%" height="100%" aria-hidden="true">
      <defs>
        <clipPath id="wafer-clip">
          <circle cx={200} cy={200} r={150} />
        </clipPath>
      </defs>
      <circle cx={200} cy={200} r={150} fill={shade(p.primary, 0.2)} />
      <g clipPath="url(#wafer-clip)">
        {Array.from({length: 9}, (_, r) =>
          Array.from({length: 9}, (_, c) => {
            const done = (r * 9 + c) / 81 < 0.92;
            return (
              <rect
                key={`d-${r}-${c}`}
                x={62 + c * 31}
                y={62 + r * 31}
                width={27}
                height={27}
                rx={2}
                fill={done ? shade(p.accent, 0.05 + (r + c) * 0.012) : dark(p)}
              />
            );
          }),
        )}
        {/* inspection sweep */}
        <rect x={50} y={50 + sweep * 300} width={300} height={16} fill={tint(p.accent, 0.7)} opacity={0.5} />
      </g>
      <circle cx={200} cy={200} r={150} fill="none" stroke={metal(p)} strokeWidth={5} />
      <path d="M200 350 L200 372" stroke={metal(p)} strokeWidth={6} strokeLinecap="round" />
    </svg>
  );
};

// ---------------------------------------------------------------------------------------------
// Networks and data
// ---------------------------------------------------------------------------------------------

/** Three layers of nodes with pulses travelling forward: the shape of an inference pass. */
const NeuralNet: React.FC<ObjectProps> = ({palette: p, frame}) => {
  const layers = [
    {x: 76, n: 4},
    {x: 200, n: 6},
    {x: 324, n: 3},
  ];
  const nodeY = (layer: {x: number; n: number}, i: number): number => 200 + (i - (layer.n - 1) / 2) * 58;
  const pulse = (frame / 26) % 1;
  return (
    <svg viewBox="0 0 400 400" width="100%" height="100%" aria-hidden="true">
      {layers.slice(0, -1).map((layer, li) => {
        const next = layers[li + 1];
        return Array.from({length: layer.n}, (_, i) =>
          Array.from({length: next.n}, (_, j) => {
            const active = Math.abs(((i + j) / (layer.n + next.n)) - pulse) < 0.12;
            return (
              <line
                key={`e-${li}-${i}-${j}`}
                x1={layer.x}
                y1={nodeY(layer, i)}
                x2={next.x}
                y2={nodeY(next, j)}
                stroke={active ? tint(p.accent, 0.35) : alpha(p.prop, 0.5)}
                strokeWidth={active ? 3 : 1.4}
              />
            );
          }),
        );
      })}
      {layers.map((layer, li) =>
        Array.from({length: layer.n}, (_, i) => {
          const lit = (Math.sin(frame / 9 + i + li) + 1) / 2;
          return (
            <g key={`n-${li}-${i}`}>
              <circle cx={layer.x} cy={nodeY(layer, i)} r={17} fill={shade(p.primary, 0.3)} />
              <circle cx={layer.x} cy={nodeY(layer, i)} r={11} fill={p.accent} opacity={0.45 + 0.55 * lit} />
            </g>
          );
        }),
      )}
    </svg>
  );
};

/** A stacked database with packets dropping in from above. */
const Database: React.FC<ObjectProps> = ({palette: p, frame}) => {
  const discs = [110, 190, 270];
  return (
    <svg viewBox="0 0 400 400" width="100%" height="100%" aria-hidden="true">
      <ellipse cx={200} cy={356} rx={104} ry={16} fill={alpha(p.ink, 0.3)} />
      {discs.map((y, i) => (
        <g key={`disc-${i}`}>
          <path d={`M96 ${y} V${y + 52} A104 30 0 0 0 304 ${y + 52} V${y} Z`} fill={shade(p.primary, 0.24 + i * 0.06)} />
          <ellipse cx={200} cy={y} rx={104} ry={30} fill={shell(p)} />
          <ellipse cx={200} cy={y} rx={104} ry={30} fill="none" stroke={metal(p)} strokeWidth={2} opacity={0.5} />
        </g>
      ))}
      {Array.from({length: 5}, (_, i) => {
        const t = ((frame / 30) + i / 5) % 1;
        const y = 20 + t * 90;
        return (
          <g key={`drop-${i}`} opacity={1 - t}>
            <rect x={192} y={y} width={16} height={12} rx={2} fill={p.accent} />
          </g>
        );
      })}
      <Led x={196} y={110} r={4} on={toggle(frame, 7, 0)} color={p.accent} off={dark(p)} />
    </svg>
  );
};

// ---------------------------------------------------------------------------------------------
// Infrastructure and space
// ---------------------------------------------------------------------------------------------

/** A satellite: bus, two solar wings, a dish that sweeps. */
const Satellite: React.FC<ObjectProps> = ({palette: p, frame}) => {
  const wing = Math.sin(frame / 40) * 4;
  const dish = Math.sin(frame / 26) * 12;
  return (
    <svg viewBox="0 0 400 400" width="100%" height="100%" aria-hidden="true">
      <g transform={`rotate(${wing} 200 200)`}>
        {/* solar wings */}
        {[-1, 1].map((side) => (
          <g key={side}>
            <rect x={side < 0 ? 24 : 264} y={168} width={112} height={64} rx={4} fill={shade(p.accent, 0.25)} />
            {Array.from({length: 4}, (_, i) => (
              <line
                key={i}
                x1={(side < 0 ? 24 : 264) + 22 + i * 22}
                y1={168}
                x2={(side < 0 ? 24 : 264) + 22 + i * 22}
                y2={232}
                stroke={shade(p.primary, 0.35)}
                strokeWidth={2}
              />
            ))}
          </g>
        ))}
      </g>
      {/* bus */}
      <path d={panel(156, 150, 88, 100, 8)} fill={shell(p)} />
      <rect x={166} y={162} width={68} height={26} rx={3} fill={dark(p)} />
      <rect x={166} y={196} width={68} height={16} rx={3} fill={metal(p)} />
      <Led x={230} y={238} r={4} on={toggle(frame, 11, 0)} color={tint(p.accent, 0.5)} off={dark(p)} />
      {/* dish */}
      <g transform={`rotate(${dish} 200 150)`}>
        <path d="M200 150 L200 108" stroke={metal(p)} strokeWidth={5} />
        <ellipse cx={200} cy={96} rx={40} ry={14} fill={tint(p.primary, 0.2)} />
        <ellipse cx={200} cy={96} rx={40} ry={14} fill="none" stroke={metal(p)} strokeWidth={3} />
      </g>
    </svg>
  );
};

/** A broadcast tower emitting rings, for anything that arrives over the air. */
const Antenna: React.FC<ObjectProps> = ({palette: p, frame}) => {
  return (
    <svg viewBox="0 0 400 400" width="100%" height="100%" aria-hidden="true">
      <ellipse cx={200} cy={368} rx={70} ry={12} fill={alpha(p.ink, 0.3)} />
      {/* lattice */}
      <path d="M176 366 L194 96 L206 96 L224 366 Z" fill={shade(p.primary, 0.28)} />
      {Array.from({length: 7}, (_, i) => {
        const y = 130 + i * 34;
        const half = 10 + (i + 1) * 1.6;
        return (
          <path
            key={`cross-${i}`}
            d={`M${200 - half} ${y} L${200 + half} ${y - 26} M${200 + half} ${y} L${200 - half} ${y - 26}`}
            stroke={metal(p)}
            strokeWidth={3}
            opacity={0.7}
          />
        );
      })}
      <rect x={192} y={86} width={16} height={16} rx={3} fill={p.accent} />
      {/* rings */}
      {[0, 1, 2].map((i) => {
        const t = ((frame / 40) + i / 3) % 1;
        return (
          <circle
            key={`ring-${i}`}
            cx={200}
            cy={92}
            r={24 + t * 130}
            fill="none"
            stroke={p.accent}
            strokeWidth={4}
            opacity={(1 - t) * 0.6}
          />
        );
      })}
    </svg>
  );
};

/** A wind turbine, for energy and sustainability angles. */
const Turbine: React.FC<ObjectProps> = ({palette: p, frame}) => {
  const spin = frame * 2.6;
  return (
    <svg viewBox="0 0 400 400" width="100%" height="100%" aria-hidden="true">
      <ellipse cx={200} cy={372} rx={64} ry={11} fill={alpha(p.ink, 0.28)} />
      <path d="M192 372 L196 120 L204 120 L208 372 Z" fill={tint(p.primary, 0.28)} />
      <g transform={`rotate(${spin} 200 118)`}>
        {[0, 120, 240].map((a) => (
          <path
            key={a}
            d="M200 118 Q206 76 200 30 Q194 76 200 118 Z"
            fill={tint(p.primary, 0.42)}
            transform={`rotate(${a} 200 118)`}
          />
        ))}
      </g>
      <circle cx={200} cy={118} r={9} fill={metal(p)} />
    </svg>
  );
};

/** A solar array with a glint travelling across the cells. */
const SolarPanel: React.FC<ObjectProps> = ({palette: p, frame}) => {
  const glint = (frame / 46) % 1;
  return (
    <svg viewBox="0 0 400 400" width="100%" height="100%" aria-hidden="true">
      <ellipse cx={200} cy={340} rx={140} ry={16} fill={alpha(p.ink, 0.26)} />
      <path d="M120 320 L140 320 L172 214 L152 214 Z" fill={metal(p)} />
      <g transform="rotate(-12 200 190)">
        <rect x={60} y={110} width={280} height={160} rx={6} fill={shade(p.primary, 0.18)} />
        <rect x={68} y={118} width={264} height={144} rx={4} fill={shade(p.accent, 0.35)} />
        {Array.from({length: 4}, (_, r) =>
          Array.from({length: 7}, (_, c) => (
            <rect
              key={`c-${r}-${c}`}
              x={74 + c * 37}
              y={124 + r * 34}
              width={32}
              height={29}
              rx={2}
              fill={shade(p.accent, 0.22)}
            />
          )),
        )}
        <rect x={68 + glint * 264} y={118} width={26} height={144} fill={tint(p.accent, 0.7)} opacity={0.28} />
      </g>
    </svg>
  );
};

/** A cooling fan — the unglamorous half of every data centre story. */
const CoolingFan: React.FC<ObjectProps> = ({palette: p, frame}) => {
  const spin = frame * 7;
  return (
    <svg viewBox="0 0 400 400" width="100%" height="100%" aria-hidden="true">
      <circle cx={200} cy={200} r={148} fill={shade(p.primary, 0.26)} />
      <circle cx={200} cy={200} r={132} fill={shade(p.primary, 0.38)} />
      <g transform={`rotate(${spin} 200 200)`}>
        {[0, 72, 144, 216, 288].map((a) => (
          <path
            key={a}
            d="M200 200 Q246 168 244 112 Q212 140 200 200 Z"
            fill={tint(p.primary, 0.2)}
            transform={`rotate(${a} 200 200)`}
          />
        ))}
      </g>
      <circle cx={200} cy={200} r={26} fill={metal(p)} />
      {[0, 1, 2, 3].map((i) => (
        <circle
          key={`holes-${i}`}
          cx={200 + Math.cos((i * Math.PI) / 2) * 128}
          cy={200 + Math.sin((i * Math.PI) / 2) * 128}
          r={7}
          fill={dark(p)}
        />
      ))}
    </svg>
  );
};

// ---------------------------------------------------------------------------------------------
// Devices
// ---------------------------------------------------------------------------------------------

/** A phone whose UI scrolls, so the object visibly does something. */
const Phone: React.FC<ObjectProps> = ({palette: p, frame}) => {
  const scroll = (frame / 2.4) % 120;
  return (
    <svg viewBox="0 0 400 400" width="100%" height="100%" aria-hidden="true">
      <ellipse cx={200} cy={372} rx={84} ry={12} fill={alpha(p.ink, 0.28)} />
      <path d={panel(116, 18, 168, 344, 26)} fill={bezel(p)} />
      <path d={panel(126, 30, 148, 320, 20)} fill={shade(p.primary, 0.42)} />
      <rect x={176} y={40} width={48} height={8} rx={4} fill={dark(p)} />
      <g>
        {Array.from({length: 7}, (_, i) => {
          const y = 66 + ((i * 46 - scroll + 322) % 322);
          return (
            <g key={`row-${i}`}>
              <rect x={138} y={y} width={124} height={34} rx={8} fill={alpha(p.accent, 0.5)} />
              <rect x={146} y={y + 8} width={62} height={6} rx={3} fill={tint(p.accent, 0.5)} />
              <rect x={146} y={y + 20} width={92} height={5} rx={2.5} fill={alpha(p.accent, 0.6)} />
            </g>
          );
        })}
      </g>
      <rect x={126} y={30} width={148} height={320} rx={20} fill="none" stroke={metal(p)} strokeWidth={2} opacity={0.4} />
    </svg>
  );
};

/** A drone: rotors spinning, body hovering on a slow sine. */
const Drone: React.FC<ObjectProps> = ({palette: p, frame}) => {
  const lift = Math.sin(frame / 14) * 6;
  const spin = frame * 26;
  const rotor = (x: number, y: number, dir: number): React.ReactNode => (
    <g key={`r-${x}-${y}`}>
      <circle cx={x} cy={y} r={34} fill={alpha(p.accent, 0.18)} />
      <g transform={`rotate(${spin * dir} ${x} ${y})`}>
        <rect x={x - 34} y={y - 4} width={68} height={8} rx={4} fill={metal(p)} opacity={0.85} />
      </g>
      <circle cx={x} cy={y} r={6} fill={dark(p)} />
    </g>
  );
  return (
    <svg viewBox="0 0 400 400" width="100%" height="100%" aria-hidden="true">
      <g transform={`translate(0 ${lift})`}>
        {rotor(112, 132, 1)}
        {rotor(288, 132, -1)}
        {rotor(148, 268, -1)}
        {rotor(252, 268, 1)}
        <path d="M112 132 L148 268 M288 132 L252 268" stroke={shade(p.primary, 0.3)} strokeWidth={9} strokeLinecap="round" />
        <path d={panel(160, 178, 80, 56, 14)} fill={shell(p)} />
        <circle cx={200} cy={212} r={13} fill={dark(p)} />
        <circle cx={200} cy={212} r={7} fill={p.accent} opacity={0.9} />
      </g>
    </svg>
  );
};

/** A rocket on the pad, exhaust flaring, for launches and "first" stories. */
const Rocket: React.FC<ObjectProps> = ({palette: p, frame}) => {
  const flicker = 0.75 + 0.25 * Math.sin(frame / 2.2);
  return (
    <svg viewBox="0 0 400 400" width="100%" height="100%" aria-hidden="true">
      <path d="M200 30 Q248 130 248 250 L152 250 Q152 130 200 30 Z" fill={tint(p.primary, 0.3)} />
      <path d="M200 30 Q226 130 226 250 L200 250 Z" fill={tint(p.primary, 0.5)} />
      <circle cx={200} cy={132} r={20} fill={shade(p.accent, 0.2)} stroke={metal(p)} strokeWidth={3} />
      <path d="M152 250 Q120 286 124 306 L152 286 Z" fill={shade(p.primary, 0.2)} />
      <path d="M248 250 Q280 286 276 306 L248 286 Z" fill={shade(p.primary, 0.2)} />
      <rect x={152} y={246} width={96} height={22} rx={5} fill={metal(p)} />
      <g opacity={flicker}>
        <path d="M182 268 Q200 268 218 268 Q210 330 200 356 Q190 330 182 268 Z" fill={p.accent} />
        <path d="M192 268 Q200 268 208 268 Q204 306 200 320 Q196 306 192 268 Z" fill={tint(p.accent, 0.7)} />
      </g>
    </svg>
  );
};

/** An office tower with lit windows: the "tech company" object. */
const Building: React.FC<ObjectProps> = ({palette: p, frame}) => {
  return (
    <svg viewBox="0 0 400 400" width="100%" height="100%" aria-hidden="true">
      <ellipse cx={200} cy={372} rx={124} ry={13} fill={alpha(p.ink, 0.3)} />
      <path d={panel(122, 66, 156, 302, 6)} fill={shade(p.primary, 0.26)} />
      <path d={panel(122, 66, 46, 302, 6)} fill={shade(p.primary, 0.16)} />
      {Array.from({length: 12}, (_, r) =>
        Array.from({length: 5}, (_, c) => {
          const on = toggle(frame, 14 + ((r * 5 + c) % 7), r + c * 0.4);
          return (
            <rect
              key={`w-${r}-${c}`}
              x={136 + c * 27}
              y={84 + r * 23}
              width={18}
              height={13}
              rx={2}
              fill={on ? tint(p.accent, 0.3) : shade(p.primary, 0.45)}
              opacity={on ? 0.9 : 0.7}
            />
          );
        }),
      )}
      <rect x={190} y={348} width={20} height={20} fill={shade(p.accent, 0.2)} />
      <path d="M200 66 L200 40" stroke={metal(p)} strokeWidth={4} />
      <circle cx={200} cy={36} r={5} fill={p.accent} opacity={toggle(frame, 20, 0) ? 1 : 0.25} />
    </svg>
  );
};

// ---------------------------------------------------------------------------------------------
// 3D Modeling, Sculpting & Modern Architecture
// ---------------------------------------------------------------------------------------------

/**
 * 3D mesh topology: recognizable rotating 3D polyhedron showing vertices, wireframe edges, and
 * polygonal faces with dynamic surface shading and vertex pulsation.
 */
const MeshTopology: React.FC<ObjectProps> = ({palette: p, frame}) => {
  const cx = 200;
  const cy = 195;
  const scale = 110;
  const angleY = frame * 0.022;
  const angleX = 0.38 + 0.08 * Math.sin(frame * 0.016);
  const cosY = Math.cos(angleY);
  const sinY = Math.sin(angleY);
  const cosX = Math.cos(angleX);
  const sinX = Math.sin(angleX);

  // Golden ratio vertices for an icosahedron (normalized)
  const phi = (1 + Math.sqrt(5)) / 2;
  const norm = Math.sqrt(1 + phi * phi);
  const a = 1 / norm;
  const b = phi / norm;

  const baseVertices: [number, number, number][] = [
    [-a, b, 0], [a, b, 0], [-a, -b, 0], [a, -b, 0],
    [0, -a, b], [0, a, b], [0, -a, -b], [0, a, -b],
    [b, 0, -a], [b, 0, a], [-b, 0, -a], [-b, 0, a],
  ];

  // Project vertices
  const projected = baseVertices.map(([vx, vy, vz]) => {
    const x1 = vx * cosY + vz * sinY;
    const z1 = -vx * sinY + vz * cosY;
    const y2 = vy * cosX - z1 * sinX;
    const z2 = vy * sinX + z1 * cosX;
    return {x: cx + x1 * scale, y: cy + y2 * scale, z: z2};
  });

  // Triangular faces
  const faces: [number, number, number][] = [
    [0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11],
    [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8],
    [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9],
    [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1],
  ];

  // Filter and sort front-facing faces
  const faceData = faces.map(([i, j, k]) => {
    const p1 = projected[i];
    const p2 = projected[j];
    const p3 = projected[k];
    // 2D cross product for winding / facing direction
    const cross = (p2.x - p1.x) * (p3.y - p1.y) - (p2.y - p1.y) * (p3.x - p1.x);
    const avgZ = (p1.z + p2.z + p3.z) / 3;
    return {i, j, k, p1, p2, p3, cross, avgZ};
  });

  const shadowScale = 0.95 + 0.05 * Math.sin(frame * 0.03);
  return (
    <svg viewBox="0 0 400 400" width="100%" height="100%" aria-hidden="true">
      {/* Ground contact shadow */}
      <ellipse cx={cx} cy={352} rx={120 * shadowScale} ry={16 * shadowScale} fill={alpha(p.ink, 0.35)} />

      {/* Backfaces subtle wireframe */}
      {faceData
        .filter((f) => f.cross <= 0)
        .map(({i, j, k, p1, p2, p3}, idx) => (
          <polygon
            key={`back-${idx}`}
            points={`${p1.x},${p1.y} ${p2.x},${p2.y} ${p3.x},${p3.y}`}
            fill={alpha(p.primary, 0.04)}
            stroke={alpha(p.primary, 0.18)}
            strokeWidth={1}
            strokeDasharray="3 3"
          />
        ))}

      {/* Front-facing solid polygons */}
      {faceData
        .filter((f) => f.cross > 0)
        .sort((a, b) => a.avgZ - b.avgZ)
        .map(({p1, p2, p3, avgZ}, idx) => {
          const light = Math.max(0.12, Math.min(0.85, 0.5 + avgZ * 0.45));
          return (
            <polygon
              key={`front-${idx}`}
              points={`${p1.x},${p1.y} ${p2.x},${p2.y} ${p3.x},${p3.y}`}
              fill={alpha(p.primary, 0.16 + light * 0.28)}
              stroke={p.accent}
              strokeWidth={2}
              strokeLinejoin="round"
            />
          );
        })}

      {/* Vertices (nodes) */}
      {projected.map((pt, idx) => {
        const isFront = pt.z > -0.2;
        const pulse = 0.5 + 0.5 * Math.sin(frame * 0.06 + idx);
        return (
          <g key={`v-${idx}`}>
            <circle
              cx={pt.x}
              cy={pt.y}
              r={isFront ? 4.5 + pulse * 1.5 : 2.5}
              fill={isFront ? p.accent : alpha(p.primary, 0.4)}
            />
            {isFront ? (
              <circle
                cx={pt.x}
                cy={pt.y}
                r={8 + pulse * 3}
                fill={alpha(p.accent, 0.2 * pulse)}
              />
            ) : null}
          </g>
        );
      })}
    </svg>
  );
};

/**
 * Clay sculpting: sculpted organic volume on a turntable with dynamic sculpting tool carving a contour groove.
 */
const ClaySculpt: React.FC<ObjectProps> = ({palette: p, frame}) => {
  const cx = 200;
  const baseTop = 320;
  // Tool carving cycle: 0..1 over 70 frames
  const toolCycle = (frame % 70) / 70;
  // Tool position sweeping down-right across cheek/volume
  const toolX = 145 + toolCycle * 95;
  const toolY = 140 + toolCycle * 80 + Math.sin(toolCycle * Math.PI) * 15;

  return (
    <svg viewBox="0 0 400 400" width="100%" height="100%" aria-hidden="true">
      {/* Ground shadow */}
      <ellipse cx={cx} cy={362} rx={126} ry={16} fill={alpha(p.ink, 0.38)} />

      {/* Turntable stand */}
      <ellipse cx={cx} cy={baseTop + 24} rx={84} ry={12} fill={shade(p.primary, 0.45)} />
      <rect x={cx - 84} y={baseTop + 12} width={168} height={12} fill={shade(p.primary, 0.35)} />
      <ellipse cx={cx} cy={baseTop + 12} rx={84} ry={12} fill={metal(p)} />
      <ellipse cx={cx} cy={baseTop + 12} rx={74} ry={9} fill={shade(p.primary, 0.18)} />
      <rect x={cx - 18} y={baseTop - 24} width={36} height={36} fill={metal(p)} />

      {/* Main sculpted clay body (organic head/bust volume) */}
      <g>
        {/* Base clay mass shadow */}
        <path
          d="M130 290 C120 250 110 200 125 150 C140 100 180 75 225 80 C270 85 295 125 290 180 C285 235 265 270 250 294 Z"
          fill={shade(p.primary, 0.32)}
        />
        {/* Main clay volume */}
        <path
          d="M136 286 C126 248 118 202 132 154 C146 108 182 84 224 88 C266 92 288 130 284 182 C280 232 260 266 244 288 Z"
          fill={tint(p.primary, 0.08)}
        />
        {/* Sculpted planar highlight (planar facet analysis) */}
        <path
          d="M175 100 C205 102 235 115 245 145 C255 175 240 215 220 240 C200 230 180 215 170 185 C160 155 165 120 175 100 Z"
          fill={alpha(tint(p.primary, 0.35), 0.65)}
        />
        {/* Cross-contour loop rings demonstrating organic volume */}
        <path
          d="M132 170 C160 195 240 195 284 175"
          fill="none"
          stroke={alpha(p.ink, 0.28)}
          strokeWidth={2}
          strokeDasharray="4 3"
        />
        <path
          d="M140 215 C170 240 230 240 268 215"
          fill="none"
          stroke={alpha(p.ink, 0.25)}
          strokeWidth={2}
          strokeDasharray="4 3"
        />
        <path
          d="M152 255 C180 272 220 272 250 255"
          fill="none"
          stroke={alpha(p.ink, 0.22)}
          strokeWidth={2}
          strokeDasharray="4 3"
        />

        {/* Newly carved groove behind the tool */}
        <path
          d={`M145 140 Q${(145 + toolX) / 2} ${(140 + toolY) / 2 + 8} ${toolX} ${toolY}`}
          fill="none"
          stroke={p.accent}
          strokeWidth={3.5}
          strokeLinecap="round"
        />
      </g>

      {/* Sculpting loop tool (rake / ribbon stylus) */}
      <g transform={`translate(${toolX}, ${toolY}) rotate(-28)`}>
        {/* Wire loop head */}
        <path
          d="M0 0 C-6 -10 6 -10 0 0"
          fill="none"
          stroke={p.accent}
          strokeWidth={3}
        />
        {/* Ferrule connector */}
        <rect x={-3} y={0} width={6} height={9} rx={1.5} fill={metal(p)} />
        {/* Wooden handle */}
        <path d="M-4 9 L4 9 L3 68 L-3 68 Z" fill={shade(p.primary, 0.42)} />
        {/* Grip bands */}
        <line x1={-3.5} y1={22} x2={3.5} y2={22} stroke={metal(p)} strokeWidth={1.5} />
        <line x1={-3} y1={36} x2={3} y2={36} stroke={metal(p)} strokeWidth={1.5} />
        {/* Active clay shaving crumb */}
        <circle cx={-5} cy={-4} r={2.5} fill={p.accent} opacity={0.8} />
        <circle cx={4} cy={-6} r={1.8} fill={p.accent} opacity={0.6} />
      </g>
    </svg>
  );
};

/**
 * Cloud architecture: client devices, API gateway/load balancer, virtual microservices, and database
 * with animated packet flows showing real requests and infrastructure.
 */
const CloudArch: React.FC<ObjectProps> = ({palette: p, frame}) => {
  // Packet progress cycles (0..1)
  const p1 = (frame * 0.035) % 1;
  const p2 = ((frame + 20) * 0.035) % 1;
  const p3 = ((frame + 40) * 0.035) % 1;

  return (
    <svg viewBox="0 0 400 400" width="100%" height="100%" aria-hidden="true">
      {/* Ground contact shadow */}
      <ellipse cx={200} cy={356} rx={135} ry={16} fill={alpha(p.ink, 0.35)} />

      {/* Cloud perimeter contour backdrop */}
      <path
        d="M90 280 C60 280 45 250 55 220 C40 190 65 155 95 160 C110 115 165 95 205 110 C245 95 300 115 315 160 C345 155 370 190 355 220 C365 250 350 280 320 280 Z"
        fill={alpha(p.primary, 0.08)}
        stroke={alpha(p.primary, 0.22)}
        strokeWidth={2}
        strokeDasharray="6 4"
      />

      {/* Infrastructure Bus Lines */}
      {/* Client (80, 220) -> Gateway (200, 115) */}
      <path d="M85 220 L200 115" stroke={alpha(p.primary, 0.28)} strokeWidth={2.5} />
      {/* Gateway (200, 115) -> Pod 1 (150, 215) */}
      <path d="M200 115 L150 215" stroke={alpha(p.primary, 0.28)} strokeWidth={2.5} />
      {/* Gateway (200, 115) -> Pod 2 (250, 215) */}
      <path d="M200 115 L250 215" stroke={alpha(p.primary, 0.28)} strokeWidth={2.5} />
      {/* Pods -> Database (200, 305) */}
      <path d="M150 245 L200 305" stroke={alpha(p.primary, 0.28)} strokeWidth={2.5} />
      <path d="M250 245 L200 305" stroke={alpha(p.primary, 0.28)} strokeWidth={2.5} />

      {/* Animated Request Packets */}
      <circle
        cx={85 + (200 - 85) * p1}
        cy={220 + (115 - 220) * p1}
        r={4.5}
        fill={p.accent}
      />
      <circle
        cx={200 + (150 - 200) * p2}
        cy={115 + (215 - 115) * p2}
        r={4}
        fill={tint(p.accent, 0.3)}
      />
      <circle
        cx={250 + (200 - 250) * p3}
        cy={215 + (305 - 215) * p3}
        r={4}
        fill={tint(p.accent, 0.3)}
      />

      {/* Node 1: Client device (Phone / laptop endpoint at x=75, y=205) */}
      <g>
        <rect x={60} y={200} width={34} height={50} rx={4} fill={shade(p.primary, 0.32)} stroke={metal(p)} strokeWidth={1.5} />
        <rect x={64} y={205} width={26} height={36} rx={2} fill={p.primary} opacity={0.85} />
        <circle cx={77} cy={245} r={2} fill={metal(p)} />
      </g>

      {/* Node 2: Cloud Gateway / Load Balancer (x=200, y=115) */}
      <g>
        <circle cx={200} cy={115} r={24} fill={shade(p.primary, 0.25)} stroke={p.accent} strokeWidth={2.5} />
        <circle cx={200} cy={115} r={16} fill={p.accent} opacity={0.25 + 0.15 * Math.sin(frame * 0.1)} />
        <polygon
          points="200,103 209,122 191,122"
          fill={p.accent}
        />
      </g>

      {/* Node 3: Microservice Pod A (x=125, y=195) */}
      <g>
        <rect x={125} y={195} width={50} height={42} rx={4} fill={shade(p.primary, 0.3)} stroke={alpha(p.primary, 0.4)} strokeWidth={1.5} />
        <rect x={132} y={202} width={36} height={5} rx={1.5} fill={tint(p.accent, 0.2)} />
        <rect x={132} y={212} width={24} height={4} rx={1.5} fill={alpha(p.primary, 0.5)} />
        <circle cx={135} cy={226} r={2.5} fill={toggle(frame, 12, 0) ? p.accent : metal(p)} />
        <circle cx={145} cy={226} r={2.5} fill={metal(p)} />
      </g>

      {/* Node 4: Microservice Pod B (x=225, y=195) */}
      <g>
        <rect x={225} y={195} width={50} height={42} rx={4} fill={shade(p.primary, 0.3)} stroke={alpha(p.primary, 0.4)} strokeWidth={1.5} />
        <rect x={232} y={202} width={36} height={5} rx={1.5} fill={tint(p.accent, 0.2)} />
        <rect x={232} y={212} width={28} height={4} rx={1.5} fill={alpha(p.primary, 0.5)} />
        <circle cx={235} cy={226} r={2.5} fill={toggle(frame, 14, 1) ? p.accent : metal(p)} />
        <circle cx={245} cy={226} r={2.5} fill={metal(p)} />
      </g>

      {/* Node 5: Clustered Database (x=200, y=305) */}
      <g>
        {/* Cylinder bottom */}
        <path d="M168 295 V320 C168 332 232 332 232 320 V295 Z" fill={shade(p.primary, 0.38)} />
        <ellipse cx={200} cy={320} rx={32} ry={9} fill={shade(p.primary, 0.28)} />
        {/* Middle disk */}
        <path d="M168 285 V305 C168 317 232 317 232 305 V285 Z" fill={shade(p.primary, 0.32)} />
        <ellipse cx={200} cy={305} rx={32} ry={9} fill={metal(p)} />
        {/* Top disk */}
        <path d="M168 275 V295 C168 307 232 307 232 295 V275 Z" fill={shade(p.primary, 0.22)} />
        <ellipse cx={200} cy={275} rx={32} ry={9} fill={tint(p.primary, 0.2)} />
        <Led x={218} y={288} r={2.5} on={toggle(frame, 8, 0)} color={p.accent} off={metal(p)} />
      </g>
    </svg>
  );
};

/**
 * CPU processor: multi-core processor die, metallic heat spreader, L3 cache bus, and gold contacts.
 */
const CpuProcessor: React.FC<ObjectProps> = ({palette: p, frame}) => {
  const cx = 200;
  const cy = 200;
  return (
    <svg viewBox="0 0 400 400" width="100%" height="100%" aria-hidden="true">
      {/* Ground shadow */}
      <ellipse cx={cx} cy={356} rx={128} ry={16} fill={alpha(p.ink, 0.35)} />

      {/* Substrate green/blue PCB */}
      <rect x={80} y={80} width={240} height={240} rx={16} fill={shade(p.primary, 0.35)} stroke={metal(p)} strokeWidth={2} />

      {/* Gold perimeter contact pads */}
      {Array.from({length: 14}, (_, i) => (
        <g key={`pin-${i}`}>
          <rect x={96 + i * 15} y={83} width={8} height={5} fill={tint(p.accent, 0.3)} />
          <rect x={96 + i * 15} y={312} width={8} height={5} fill={tint(p.accent, 0.3)} />
          <rect x={83} y={96 + i * 15} width={5} height={8} fill={tint(p.accent, 0.3)} />
          <rect x={312} y={96 + i * 15} width={5} height={8} fill={tint(p.accent, 0.3)} />
        </g>
      ))}

      {/* Metallic Integrated Heat Spreader (IHS) */}
      <rect x={112} y={112} width={176} height={176} rx={10} fill={metal(p)} stroke={shade(p.primary, 0.18)} strokeWidth={3} />

      {/* Central silicon die window */}
      <rect x={140} y={140} width={120} height={120} rx={4} fill={shade(p.ink, 0.5)} stroke={p.accent} strokeWidth={2} />

      {/* 8 Compute Cores in 2x4 grid */}
      {Array.from({length: 8}, (_, idx) => {
        const row = Math.floor(idx / 4);
        const col = idx % 4;
        const active = toggle(frame, 10 + (idx % 4) * 3, idx);
        return (
          <rect
            key={`core-${idx}`}
            x={148 + col * 26}
            y={148 + row * 44}
            width={20}
            height={18}
            rx={2}
            fill={active ? tint(p.accent, 0.3) : shade(p.primary, 0.3)}
            stroke={p.accent}
            strokeWidth={1}
          />
        );
      })}

      {/* Shared L3 cache bar in the middle */}
      <rect x={148} y={192} width={104} height={16} rx={2} fill={tint(p.primary, 0.15)} />
      <line x1={148} y1={200} x2={252} y2={200} stroke={p.accent} strokeWidth={1.5} strokeDasharray="4 2" />
    </svg>
  );
};

/**
 * Quantum processor: cryogenic carrier, superconducting transmon qubits, and microwave resonators.
 */
const QuantumProcessor: React.FC<ObjectProps> = ({palette: p, frame}) => {
  const cx = 200;
  const cy = 200;
  return (
    <svg viewBox="0 0 400 400" width="100%" height="100%" aria-hidden="true">
      {/* Ground shadow */}
      <ellipse cx={cx} cy={356} rx={128} ry={16} fill={alpha(p.ink, 0.35)} />

      {/* Gold cryogenic cold-plate ring */}
      <circle cx={cx} cy={cy} r={130} fill={shade(p.accent, 0.4)} stroke={tint(p.accent, 0.25)} strokeWidth={4} />
      <circle cx={cx} cy={cy} r={115} fill={shade(p.primary, 0.45)} />

      {/* Silicon quantum chip substrate */}
      <rect x={130} y={130} width={140} height={140} rx={8} fill={shade(p.ink, 0.6)} stroke={p.accent} strokeWidth={2} />

      {/* Superconducting transmon qubits (crosses) */}
      {[
        [160, 160], [240, 160],
        [200, 200],
        [160, 240], [240, 240]
      ].map(([qx, qy], idx) => {
        const qPulse = 0.5 + 0.5 * Math.sin(frame * 0.08 + idx * 1.3);
        return (
          <g key={`qubit-${idx}`}>
            {/* Qubit cross shape */}
            <rect x={qx - 3} y={qy - 14} width={6} height={28} rx={2} fill={p.accent} />
            <rect x={qx - 14} y={qy - 3} width={28} height={6} rx={2} fill={p.accent} />
            {/* Quantum entanglement aura */}
            <circle cx={qx} cy={qy} r={18} fill={alpha(p.accent, 0.25 * qPulse)} />
          </g>
        );
      })}

      {/* Meandering coplanar microwave waveguide resonator lines */}
      <path
        d="M160 160 Q180 170 200 200 T240 240"
        fill="none"
        stroke={tint(p.primary, 0.4)}
        strokeWidth={2}
        strokeDasharray="4 2"
      />
      <path
        d="M240 160 Q220 170 200 200 T160 240"
        fill="none"
        stroke={tint(p.primary, 0.4)}
        strokeWidth={2}
        strokeDasharray="4 2"
      />
    </svg>
  );
};

/**
 * Optical fiber: glass fiber cores with guided laser pulses demonstrating high-speed optical transmission.
 */
const OpticalFiber: React.FC<ObjectProps> = ({palette: p, frame}) => {
  const p1 = (frame * 0.04) % 1;
  const p2 = ((frame + 18) * 0.04) % 1;
  const p3 = ((frame + 36) * 0.04) % 1;

  return (
    <svg viewBox="0 0 400 400" width="100%" height="100%" aria-hidden="true">
      {/* Ground shadow */}
      <ellipse cx={200} cy={356} rx={130} ry={16} fill={alpha(p.ink, 0.35)} />

      {/* Outer cable jacket (cutaway on left) */}
      <path
        d="M50 170 C90 170 120 180 140 190 L140 230 C120 220 90 210 50 210 Z"
        fill={shade(p.primary, 0.35)}
        stroke={metal(p)}
        strokeWidth={2}
      />

      {/* 3 Glowing glass fiber strands */}
      <path id="f1" d="M140 195 C200 170 260 160 340 170" fill="none" stroke={alpha(p.accent, 0.4)} strokeWidth={4} />
      <path id="f2" d="M140 205 C200 205 270 205 340 205" fill="none" stroke={alpha(p.accent, 0.55)} strokeWidth={4} />
      <path id="f3" d="M140 215 C200 235 260 245 340 235" fill="none" stroke={alpha(p.accent, 0.4)} strokeWidth={4} />

      {/* Laser Light Pulses propagating along strands */}
      <circle cx={140 + 200 * p1} cy={195 - Math.sin(p1 * Math.PI) * 20} r={6} fill={tint(p.accent, 0.4)} />
      <circle cx={140 + 200 * p2} cy={205} r={7} fill={p.accent} />
      <circle cx={140 + 200 * p3} cy={215 + Math.sin(p3 * Math.PI) * 20} r={6} fill={tint(p.accent, 0.4)} />

      {/* Transceiver connector block on the right */}
      <rect x={330} y={150} width={40} height={100} rx={6} fill={metal(p)} stroke={shade(p.primary, 0.2)} strokeWidth={2} />
      <Led x={350} y={170} r={3} on={toggle(frame, 6, 0)} color={p.accent} off={shade(p.primary, 0.5)} />
      <Led x={350} y={190} r={3} on={toggle(frame, 10, 1)} color={tint(p.accent, 0.3)} off={shade(p.primary, 0.5)} />
    </svg>
  );
};

/**
 * Subsea fiber-optic cable cross-section: concentric protective armor layers
 * (polyethylene outer jacket, steel armor wires, copper conductor, optical gel, and fiber core).
 */
const SubseaCableCutaway: React.FC<ObjectProps> = ({palette: p, frame}) => {
  const pulse = (frame * 0.05) % 1;
  const wires = Array.from({length: 16}, (_, i) => {
    const angle = (i * 2 * Math.PI) / 16;
    return {
      x: 200 + 104 * Math.cos(angle),
      y: 195 + 104 * Math.sin(angle),
    };
  });
  const fibers = Array.from({length: 6}, (_, i) => {
    const angle = (i * 2 * Math.PI) / 6;
    return {
      x: 200 + 26 * Math.cos(angle),
      y: 195 + 26 * Math.sin(angle),
    };
  });

  return (
    <svg viewBox="0 0 400 400" width="100%" height="100%" aria-hidden="true">
      {/* Ground contact shadow */}
      <ellipse cx={200} cy={356} rx={145} ry={18} fill={alpha(p.ink, 0.35)} />

      {/* Cable cylinder depth extension */}
      <path
        d="M60 195 L140 110 L340 110 L260 195 Z"
        fill={alpha(p.primary, 0.15)}
        stroke={alpha(p.primary, 0.3)}
        strokeWidth={1.5}
      />

      {/* Layer 1: Outer Polyethylene Jacket (Heavy dark protection) */}
      <circle cx={200} cy={195} r={140} fill={shade(p.primary, 0.4)} stroke={metal(p)} strokeWidth={3} />
      <circle cx={200} cy={195} r={130} fill={shade(p.primary, 0.28)} />

      {/* Layer 2: Mylar water-barrier tape */}
      <circle cx={200} cy={195} r={120} fill={alpha(p.accent, 0.2)} stroke={metal(p)} strokeWidth={1.5} />

      {/* Layer 3: High-tensile steel armor wire ring */}
      <circle cx={200} cy={195} r={112} fill={shade(p.primary, 0.45)} />
      {wires.map((w, i) => (
        <circle key={`sw-${i}`} cx={w.x} cy={w.y} r={7.5} fill={metal(p)} stroke={shade(p.primary, 0.3)} strokeWidth={1.2} />
      ))}

      {/* Layer 4: Copper power transmission tube */}
      <circle cx={200} cy={195} r={86} fill="#c27838" stroke="#e09452" strokeWidth={3} />
      <circle cx={200} cy={195} r={72} fill={shade(p.primary, 0.3)} />

      {/* Layer 5: Polycarbonate buffer sheath */}
      <circle cx={200} cy={195} r={58} fill={alpha(p.accent, 0.35)} stroke={metal(p)} strokeWidth={1.5} />

      {/* Layer 6: Water-blocking thixotropic gel bed */}
      <circle cx={200} cy={195} r={44} fill={alpha(p.primary, 0.18)} />

      {/* Central steel strength member */}
      <circle cx={200} cy={195} r={12} fill={metal(p)} stroke={shade(p.primary, 0.3)} strokeWidth={1} />

      {/* Glowing pure glass fiber cores */}
      {fibers.map((f, i) => {
        const lit = (i / 6 + pulse) % 1;
        return (
          <g key={`fc-${i}`}>
            <circle cx={f.x} cy={f.y} r={9} fill={p.accent} opacity={0.35 + lit * 0.5} />
            <circle cx={f.x} cy={f.y} r={5.5} fill="#ffffff" />
            <circle cx={f.x} cy={f.y} r={3} fill={p.accent} />
          </g>
        );
      })}

      {/* High-speed signal emission ring */}
      <circle
        cx={200}
        cy={195}
        r={28 + pulse * 14}
        fill="none"
        stroke={alpha(p.accent, 0.5 * (1 - pulse))}
        strokeWidth={2}
      />
    </svg>
  );
};

/**
 * Cooking pot: stainless steel/enamel stockpot on stove, bubbling boiling water, steam rising.
 */
const CookingPot: React.FC<ObjectProps> = ({palette: p, frame}) => {
  const steam1 = (frame * 0.04) % 1;
  const steam2 = ((frame + 18) * 0.04) % 1;
  const bubbleY = Math.sin(frame * 0.18) * 3;

  return (
    <svg viewBox="0 0 400 400" width="100%" height="100%" aria-hidden="true">
      {/* Ground contact shadow */}
      <ellipse cx={200} cy={356} rx={135} ry={16} fill={alpha(p.ink, 0.35)} />

      {/* Stove burner ring */}
      <ellipse cx={200} cy={334} rx={120} ry={14} fill={shade(p.primary, 0.45)} />
      <ellipse cx={200} cy={334} rx={95} ry={10} fill="none" stroke={p.accent} strokeWidth={3} strokeDasharray="16 8" />

      {/* Animated steam wisps */}
      <path
        d={`M165,${130 - steam1 * 60} Q145,${105 - steam1 * 60} 170,${80 - steam1 * 60} T160,${50 - steam1 * 60}`}
        fill="none"
        stroke={alpha(p.primary, 0.28 * (1 - steam1))}
        strokeWidth={3.5}
        strokeLinecap="round"
      />
      <path
        d={`M235,${125 - steam2 * 60} Q255,${100 - steam2 * 60} 230,${75 - steam2 * 60} T240,${45 - steam2 * 60}`}
        fill="none"
        stroke={alpha(p.primary, 0.25 * (1 - steam2))}
        strokeWidth={3.5}
        strokeLinecap="round"
      />

      {/* Pot side loop handles */}
      <rect x={44} y={190} width={26} height={46} rx={8} fill={shade(p.primary, 0.32)} stroke={metal(p)} strokeWidth={2} />
      <rect x={330} y={190} width={26} height={46} rx={8} fill={shade(p.primary, 0.32)} stroke={metal(p)} strokeWidth={2} />

      {/* Pot body cylinder */}
      <path
        d="M66 170 L66 305 C66 330 110 340 200 340 C290 340 334 330 334 305 L334 170 Z"
        fill={metal(p)}
        stroke={shade(p.primary, 0.25)}
        strokeWidth={2.5}
      />
      {/* Pot metallic highlight reflection */}
      <path
        d="M95 180 L95 320 C110 326 130 330 150 332 L150 180 Z"
        fill={alpha('#ffffff', 0.22)}
      />

      {/* Pot top rim ellipse */}
      <ellipse cx={200} cy={170} rx={134} ry={24} fill={shade(p.primary, 0.2)} stroke={metal(p)} strokeWidth={2} />
      {/* Boiling broth / water surface */}
      <ellipse cx={200} cy={172} rx={124} ry={20} fill={alpha(p.accent, 0.55)} />

      {/* Simmering bubbles */}
      <circle cx={160} cy={172 + bubbleY} r={5} fill={tint(p.accent, 0.5)} />
      <circle cx={220} cy={174 - bubbleY} r={6} fill={tint(p.accent, 0.5)} />
      <circle cx={190} cy={168 + bubbleY * 0.7} r={4} fill="#ffffff" />
      <circle cx={250} cy={170 + bubbleY} r={4.5} fill="#ffffff" />
    </svg>
  );
};

/**
 * Ramen bowl: ceramic noodle bowl with wavy noodles, boiled egg half, scallions, nori, steam.
 */
const RamenBowl: React.FC<ObjectProps> = ({palette: p, frame}) => {
  const steam = (frame * 0.035) % 1;

  return (
    <svg viewBox="0 0 400 400" width="100%" height="100%" aria-hidden="true">
      {/* Ground contact shadow */}
      <ellipse cx={200} cy={356} rx={130} ry={15} fill={alpha(p.ink, 0.35)} />

      {/* Steam rising */}
      <path
        d={`M190,${120 - steam * 50} Q175,${95 - steam * 50} 205,${70 - steam * 50} T195,${45 - steam * 50}`}
        fill="none"
        stroke={alpha(p.primary, 0.22 * (1 - steam))}
        strokeWidth={3}
        strokeLinecap="round"
      />

      {/* Ceramic bowl foot ring */}
      <rect x={140} y={328} width={120} height={18} rx={6} fill={shade(p.primary, 0.35)} stroke={metal(p)} strokeWidth={2} />

      {/* Ceramic bowl body */}
      <path
        d="M50 175 C55 270 120 330 200 330 C280 330 345 270 350 175 Z"
        fill={p.primary}
        stroke={metal(p)}
        strokeWidth={3}
      />
      {/* Decorative colored rim band */}
      <path
        d="M50 175 C55 205 75 225 95 230 C90 205 65 185 50 175 Z"
        fill={p.accent}
        opacity={0.8}
      />

      {/* Bowl rim outer ellipse */}
      <ellipse cx={200} cy={175} rx={150} ry={36} fill={metal(p)} stroke={shade(p.primary, 0.2)} strokeWidth={2} />
      {/* Rich ramen broth surface */}
      <ellipse cx={200} cy={178} rx={142} ry={32} fill="#d97706" />

      {/* Wavy noodles in broth */}
      <path
        d="M95 178 Q115 165 135 178 T175 178 T215 178 T255 178 T295 178"
        fill="none"
        stroke="#fde047"
        strokeWidth={5}
        strokeLinecap="round"
      />
      <path
        d="M110 188 Q130 175 150 188 T190 188 T230 188 T270 188 T300 185"
        fill="none"
        stroke="#facc15"
        strokeWidth={5}
        strokeLinecap="round"
      />
      <path
        d="M120 198 Q140 186 160 198 T200 198 T240 198 T280 196"
        fill="none"
        stroke="#fde047"
        strokeWidth={4.5}
        strokeLinecap="round"
      />

      {/* Dark nori seaweed sheet */}
      <polygon points="75,140 115,130 125,185 85,195" fill="#1e293b" />

      {/* Boiled ramen egg half */}
      <ellipse cx={245} cy={180} rx={22} ry={16} fill="#ffffff" transform="rotate(-15 245 180)" />
      <ellipse cx={245} cy={180} rx={13} ry={10} fill="#f97316" transform="rotate(-15 245 180)" />
      <circle cx={247} cy={178} r={3} fill="#fef08a" />

      {/* Scallion / chive slices */}
      <ellipse cx={170} cy={185} rx={6} ry={3.5} fill="#22c55e" stroke="#15803d" strokeWidth={1} />
      <ellipse cx={182} cy={175} rx={5} ry={3} fill="#22c55e" stroke="#15803d" strokeWidth={1} />
      <ellipse cx={195} cy={188} rx={6.5} ry={4} fill="#22c55e" stroke="#15803d" strokeWidth={1} />
      <ellipse cx={210} cy={180} rx={5} ry={3} fill="#22c55e" stroke="#15803d" strokeWidth={1} />

      {/* Pair of bamboo chopsticks resting on bowl */}
      <polygon points="90,140 330,165 330,171 90,144" fill="#a16207" />
      <polygon points="95,148 335,173 335,178 95,152" fill="#78350f" />
    </svg>
  );
};

/**
 * Planet Earth: recognizable blue marble sphere with continents, Indonesia archipelago, and cloud drift.
 */
const PlanetEarth: React.FC<ObjectProps> = ({palette: p, frame}) => {
  const cloudDrift = (frame * 0.12) % 180;

  return (
    <svg viewBox="0 0 400 400" width="100%" height="100%" aria-hidden="true">
      {/* Outer atmosphere halo glow */}
      <circle cx={200} cy={195} r={148} fill={alpha(p.accent, 0.18)} />
      <circle cx={200} cy={195} r={142} fill={alpha('#38bdf8', 0.14)} />

      {/* Earth deep ocean base sphere */}
      <defs>
        <radialGradient id="earthGrad" cx="35%" cy="30%" r="70%">
          <stop offset="0%" stopColor="#38bdf8" />
          <stop offset="45%" stopColor="#0284c7" />
          <stop offset="100%" stopColor="#082f49" />
        </radialGradient>
        <clipPath id="earthClip">
          <circle cx={200} cy={195} r={136} />
        </clipPath>
      </defs>

      <circle cx={200} cy={195} r={136} fill="url(#earthGrad)" />

      {/* Clipped continents and clouds */}
      <g clipPath="url(#earthClip)">
        {/* Asian landmass / China / India */}
        <path
          d="M120 110 Q160 90 220 100 Q260 115 270 145 Q240 170 200 160 Q170 170 150 145 Z"
          fill="#15803d"
          stroke="#166534"
          strokeWidth={1.5}
        />
        {/* Southeast Asia & Indonesian Archipelago */}
        <path
          d="M185 180 Q210 185 240 180 Q245 190 230 195 Q205 195 185 185 Z"
          fill="#22c55e"
        />
        {/* Sumatra, Java, Kalimantan, Sulawesi islands */}
        <ellipse cx={175} cy={195} rx={14} ry={6} fill="#22c55e" transform="rotate(-25 175 195)" />
        <ellipse cx={195} cy={206} rx={16} ry={5} fill="#22c55e" transform="rotate(-5 195 206)" />
        <ellipse cx={212} cy={192} rx={12} ry={10} fill="#22c55e" />
        <ellipse cx={232} cy={198} rx={8} ry={10} fill="#22c55e" />
        <ellipse cx={260} cy={205} rx={18} ry={8} fill="#22c55e" />

        {/* Australia */}
        <path
          d="M240 230 C270 225 305 240 300 270 C280 285 245 285 235 260 Z"
          fill="#d97706"
          stroke="#b45309"
          strokeWidth={1.5}
        />

        {/* Animated atmospheric cloud swirls */}
        <g transform={`translate(${cloudDrift - 90}, 0)`} opacity={0.65}>
          <path
            d="M60 130 Q120 110 190 125 T290 120"
            fill="none"
            stroke="#ffffff"
            strokeWidth={14}
            strokeLinecap="round"
          />
          <path
            d="M130 170 Q180 160 250 165 T350 160"
            fill="none"
            stroke="#ffffff"
            strokeWidth={12}
            strokeLinecap="round"
          />
          <path
            d="M90 220 Q160 210 220 225 T320 215"
            fill="none"
            stroke="#ffffff"
            strokeWidth={10}
            strokeLinecap="round"
          />
        </g>

        {/* Sphere 3D terminator shadow */}
        <path
          d="M200 59 C275 59 336 120 336 195 C336 270 275 331 200 331 C240 290 260 240 260 195 C260 150 240 100 200 59 Z"
          fill={alpha('#000000', 0.38)}
        />
      </g>

      {/* Delicate satellite orbital trajectory ring */}
      <ellipse
        cx={200}
        cy={195}
        rx={165}
        ry={55}
        fill="none"
        stroke={alpha(p.accent, 0.4)}
        strokeWidth={1.5}
        strokeDasharray="8 6"
        transform="rotate(-22 200 195)"
      />
      {/* Orbiting micro-satellite marker */}
      <circle
        cx={200 + 165 * Math.cos((frame * 0.04) % (2 * Math.PI))}
        cy={195 + 55 * Math.sin((frame * 0.04) % (2 * Math.PI))}
        r={4}
        fill={p.accent}
      />
    </svg>
  );
};

/** A precision scientific microscope for biology, medicine, and research explainers. */
const Microscope: React.FC<ObjectProps> = ({palette: p, frame}) => {
  const pulse = Math.sin(frame * 0.08) * 0.15;
  return (
    <svg viewBox="0 0 400 400" width="100%" height="100%" aria-hidden="true">
      {/* Ground contact shadow */}
      <ellipse cx={200} cy={372} rx={95} ry={14} fill={alpha(p.ink, 0.28)} />

      {/* Heavy Horseshoe Base */}
      <path
        d="M125 365 C125 335 155 330 200 330 C245 330 275 335 275 365 C275 372 260 376 200 376 C140 376 125 372 125 365 Z"
        fill={shade(p.primary, 0.35)}
      />
      <ellipse cx={200} cy={356} rx={55} ry={8} fill={shade(p.primary, 0.15)} />

      {/* Curved Arm */}
      <path
        d="M230 335 C270 300 270 210 240 160 C230 145 220 140 205 140"
        fill="none"
        stroke={shade(p.primary, 0.25)}
        strokeWidth={26}
        strokeLinecap="round"
      />
      <circle cx={242} cy={240} r={16} fill={metal(p)} stroke={shade(p.ink, 0.2)} strokeWidth={2} />
      <circle cx={242} cy={240} r={8} fill={shade(p.primary, 0.4)} />

      {/* Stage and Specimen Glass Slide */}
      <rect x={130} y={235} width={90} height={10} rx={2} fill={shade(p.ink, 0.4)} />
      <rect x={145} y={231} width={60} height={4} rx={1} fill={alpha('#ffffff', 0.85)} />
      {/* Glowing specimen on slide */}
      <circle cx={175} cy={233} r={4 + pulse * 2} fill={p.accent} opacity={0.9} />

      {/* Condenser / Mirror below stage */}
      <ellipse cx={175} cy={275} rx={16} ry={6} fill={metal(p)} />
      <path d="M175 275 L175 330" stroke={metal(p)} strokeWidth={6} />

      {/* Optical Tube and Eyepiece */}
      <g transform="rotate(-15 175 160)">
        {/* Main Body Tube */}
        <rect x={164} y={90} width={22} height={85} rx={3} fill={metal(p)} stroke={shade(p.primary, 0.3)} strokeWidth={2} />
        {/* Eyepiece / Ocular */}
        <rect x={160} y={60} width={30} height={30} rx={4} fill={shade(p.primary, 0.45)} />
        <ellipse cx={175} cy={60} rx={15} ry={4} fill={p.accent} />
        {/* Revolving Nosepiece */}
        <path d="M160 175 L190 175 L182 190 L168 190 Z" fill={shade(p.primary, 0.3)} />
        {/* Objective Lenses */}
        <rect x={171} y={190} width={8} height={25} rx={2} fill={metal(p)} />
        <rect x={170} y={212} width={10} height={4} rx={1} fill={p.accent} />
        <rect x={180} y={185} width={7} height={18} rx={1} fill={shade(metal(p), 0.2)} transform="rotate(30 180 185)" />
      </g>

      {/* Illuminated light cone from objective onto slide */}
      <polygon
        points="171,215 179,215 185,231 165,231"
        fill={alpha(p.accent, 0.25 + pulse)}
      />
    </svg>
  );
};

/** An incandescent light bulb symbolizing inventions, discoveries, and innovation. */
const LightBulb: React.FC<ObjectProps> = ({palette: p, frame}) => {
  const glow = 0.7 + Math.sin(frame * 0.1) * 0.25;
  return (
    <svg viewBox="0 0 400 400" width="100%" height="100%" aria-hidden="true">
      {/* Ground contact shadow */}
      <ellipse cx={200} cy={372} rx={70} ry={12} fill={alpha(p.ink, 0.22)} />

      {/* Soft Radiating Glow Aura */}
      <circle cx={200} cy={165} r={115} fill={alpha(p.accent, 0.12 * glow)} />
      <circle cx={200} cy={165} r={85} fill={alpha('#fff5cc', 0.22 * glow)} />

      {/* Screw Base / Threading */}
      <rect x={178} y={290} width={44} height={8} rx={4} fill={shade(metal(p), 0.15)} />
      <rect x={180} y={300} width={40} height={8} rx={4} fill={metal(p)} />
      <rect x={182} y={310} width={36} height={8} rx={4} fill={shade(metal(p), 0.15)} />
      {/* Electrical Foot Contact */}
      <path d="M185 318 C185 328 215 328 215 318 Z" fill={shade(p.ink, 0.4)} />

      {/* Glass Bulb Outline */}
      <path
        d="M178 290 C162 270 140 230 140 175 C140 108 167 80 200 80 C233 80 260 108 260 175 C260 230 238 270 222 290 Z"
        fill={alpha('#ffffff', 0.45)}
        stroke={shade(p.primary, 0.2)}
        strokeWidth={4}
      />

      {/* Interior Mount / Lead Wires */}
      <path d="M192 288 L192 215 M208 288 L208 215" stroke={metal(p)} strokeWidth={2.5} />

      {/* Tungsten Filament (Glowing Heart) */}
      <path
        d="M192 215 Q196 175 186 160 Q192 145 200 145 Q208 145 214 160 Q204 175 208 215"
        fill="none"
        stroke={p.accent}
        strokeWidth={3.5}
        strokeLinecap="round"
        opacity={glow}
      />
      {/* Center highlight point */}
      <circle cx={200} cy={148} r={5} fill="#ffffff" opacity={glow} />

      {/* Curved Glass Specular Reflection Highlight */}
      <path
        d="M155 135 C150 155 152 180 158 205"
        fill="none"
        stroke="#ffffff"
        strokeWidth={6}
        strokeLinecap="round"
        opacity={0.65}
      />
    </svg>
  );
};

/** An industrial factory with saw-tooth roof and puffing chimney smoke for history/business. */
const Factory: React.FC<ObjectProps> = ({palette: p, frame}) => {
  const smokeT = (frame * 0.05) % 1;
  return (
    <svg viewBox="0 0 400 400" width="100%" height="100%" aria-hidden="true">
      {/* Ground contact shadow */}
      <ellipse cx={200} cy={372} rx={135} ry={14} fill={alpha(p.ink, 0.28)} />

      {/* Chimney 1 (Left Tall) */}
      <polygon points="120,360 128,150 146,150 154,360" fill={shade(p.primary, 0.25)} />
      <rect x={126} y={145} width={22} height={7} rx={2} fill={shade(p.ink, 0.35)} />
      {/* Chimney Band */}
      <polygon points="124,185 126,170 148,170 150,185" fill={p.accent} />

      {/* Animated Smoke Puffs */}
      {[0, 1, 2].map((i) => {
        const t = (smokeT + i / 3) % 1;
        const scale = 0.5 + t * 1.4;
        const y = 140 - t * 85;
        const x = 137 + Math.sin(t * 4 + i) * 16 + t * 24;
        return (
          <circle
            key={`smoke-${i}`}
            cx={x}
            cy={y}
            r={12 * scale}
            fill={alpha('#ffffff', (1 - t) * 0.55)}
          />
        );
      })}

      {/* Main Factory Building with Saw-Tooth Roof */}
      <path
        d="M90 360 L90 270 L140 215 L140 270 L195 215 L195 270 L250 215 L250 270 L305 215 L305 360 Z"
        fill={tint(p.primary, 0.15)}
        stroke={shade(p.primary, 0.35)}
        strokeWidth={3}
      />

      {/* Front Saw-Tooth Accent Shadowing */}
      <polygon points="140,215 140,270 148,270 148,225" fill={shade(p.primary, 0.2)} />
      <polygon points="195,215 195,270 203,270 203,225" fill={shade(p.primary, 0.2)} />
      <polygon points="250,215 250,270 258,270 258,225" fill={shade(p.primary, 0.2)} />

      {/* Factory Grid Windows with Warm Glow */}
      {[110, 165, 220, 275].map((x) => (
        <g key={`win-${x}`}>
          <rect x={x} y={290} width={24} height={42} rx={2} fill="#fffae6" stroke={shade(p.ink, 0.3)} strokeWidth={1.5} />
          <line x1={x + 12} y1={290} x2={x + 12} y2={332} stroke={shade(p.ink, 0.3)} strokeWidth={1.5} />
          <line x1={x} y1={311} x2={x + 24} y2={311} stroke={shade(p.ink, 0.3)} strokeWidth={1.5} />
        </g>
      ))}

      {/* Heavy Roll-Up Warehouse Door */}
      <rect x={180} y={325} width={40} height={35} fill={shade(p.ink, 0.35)} />
      {[332, 339, 346, 353].map((y) => (
        <line key={`door-${y}`} x1={180} y1={y} x2={220} y2={y} stroke={metal(p)} strokeWidth={1.5} />
      ))}
    </svg>
  );
};

/** A financial/economic chart showing growth, data metrics, and business trends. */
const StockChart: React.FC<ObjectProps> = ({palette: p, frame}) => {
  const pulse = Math.sin(frame * 0.1) * 3;
  return (
    <svg viewBox="0 0 400 400" width="100%" height="100%" aria-hidden="true">
      {/* Ground contact shadow */}
      <ellipse cx={200} cy={372} rx={110} ry={12} fill={alpha(p.ink, 0.25)} />

      {/* Chart Backboard Tablet / Monitor */}
      <rect
        x={75}
        y={80}
        width={250}
        height={280}
        rx={12}
        fill={tint(p.primary, 0.35)}
        stroke={shade(p.primary, 0.25)}
        strokeWidth={3}
      />

      {/* Grid Lines */}
      {[130, 180, 230, 280].map((y) => (
        <line
          key={`grid-${y}`}
          x1={95}
          y1={y}
          x2={305}
          y2={y}
          stroke={alpha(p.ink, 0.12)}
          strokeDasharray="4 4"
          strokeWidth={1.5}
        />
      ))}

      {/* Volume Histogram Bars at Bottom */}
      {[
        {x: 105, h: 28},
        {x: 135, h: 42},
        {x: 165, h: 32},
        {x: 195, h: 56},
        {x: 225, h: 48},
        {x: 255, h: 72},
        {x: 285, h: 64},
      ].map((bar, i) => (
        <rect
          key={`bar-${i}`}
          x={bar.x}
          y={330 - bar.h}
          width={18}
          height={bar.h}
          rx={2}
          fill={alpha(p.accent, 0.38)}
        />
      ))}

      {/* Upward Growth Trend Curve */}
      <path
        d="M100 300 Q140 280 170 230 T240 180 T300 120"
        fill="none"
        stroke={p.accent}
        strokeWidth={6}
        strokeLinecap="round"
      />

      {/* Shaded Area Under Curve */}
      <path
        d="M100 300 Q140 280 170 230 T240 180 T300 120 L300 330 L100 330 Z"
        fill={alpha(p.accent, 0.12)}
      />

      {/* Live Pulsing Data Peak Point */}
      <circle cx={300} cy={120} r={9 + pulse * 0.5} fill={alpha(p.accent, 0.3)} />
      <circle cx={300} cy={120} r={5} fill="#ffffff" stroke={p.accent} strokeWidth={2} />

      {/* Currency / Growth Indicator Badge */}
      <rect x={245} y={92} width={65} height={22} rx={11} fill={p.accent} />
      <text
        x={277}
        y={107}
        textAnchor="middle"
        fill="#ffffff"
        fontSize={12}
        fontFamily="sans-serif"
        fontWeight="bold"
      >
        +84.6%
      </text>
    </svg>
  );
};


// ---------------------------------------------------------------------------------------------
// Registry
// ---------------------------------------------------------------------------------------------

export const OBJECT_COMPONENTS: Record<ObjectKind, React.FC<ObjectProps>> = {
  gpu: Gpu,
  wafer: Wafer,
  serverRack: ServerRack,
  dataCenter: DataCenter,
  neuralNet: NeuralNet,
  database: Database,
  satellite: Satellite,
  antenna: Antenna,
  turbine: Turbine,
  solarPanel: SolarPanel,
  coolingFan: CoolingFan,
  phone: Phone,
  drone: Drone,
  rocket: Rocket,
  building: Building,
  meshTopology: MeshTopology,
  claySculpt: ClaySculpt,
  cloudArch: CloudArch,
  cpuProcessor: CpuProcessor,
  quantumProcessor: QuantumProcessor,
  opticalFiber: OpticalFiber,
  subseaCableCutaway: SubseaCableCutaway,
  ramenBowl: RamenBowl,
  cookingPot: CookingPot,
  planetEarth: PlanetEarth,
  microscope: Microscope,
  lightBulb: LightBulb,
  factory: Factory,
  stockChart: StockChart,
};

/** Every kind has a drawing; this is the assertion the QC gate mirrors on the Python side. */
if (Object.keys(OBJECT_COMPONENTS).length !== OBJECT_KINDS.length) {
  throw new Error('object library and OBJECT_KINDS disagree');
}
