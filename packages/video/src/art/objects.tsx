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
};

/** Every kind has a drawing; this is the assertion the QC gate mirrors on the Python side. */
if (Object.keys(OBJECT_COMPONENTS).length !== OBJECT_KINDS.length) {
  throw new Error('object library and OBJECT_KINDS disagree');
}
