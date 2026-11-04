/**
 * Backdrops for informative scenes.
 *
 * An environment is not decoration: it establishes *where* the object lives, which is half of what
 * makes an illustration informative. A GPU on a cosmic gradient says nothing; the same GPU in a
 * data hall with a grid floor and a cable tray says "inference cluster".
 *
 * Every environment is drawn from the palette, so a theme change recolours the whole film
 * consistently and no environment introduces a colour the theme does not own.
 */

import React from 'react';
import { useCurrentFrame } from 'remotion';
import {alpha, isLight, mix, shade, tint, type ArtPalette, type EnvironmentKind, DEFAULT_PALETTE} from './palette';

const W = 1080;
const H = 1920;

/** Perspective floor: lines converging on a horizon, the cheapest honest depth cue. */
const Floor: React.FC<{palette: ArtPalette; horizon: number; rows?: number; opacity?: number}> = ({
  palette: p,
  horizon,
  rows = 9,
  opacity = 0.5,
}) => {
  const light = isLight(p.skyTop);
  const gridLine = light ? alpha(p.prop, 0.22) : tint(p.ground, 0.35);
  return (
    <g opacity={opacity}>
      {Array.from({length: rows}, (_, i) => {
        const t = i / (rows - 1);
        // Rows compress toward the horizon, which is what makes a flat grid read as a plane.
        const y = horizon + (H - horizon) * t * t;
        return <line key={`r-${i}`} x1={0} y1={y} x2={W} y2={y} stroke={gridLine} strokeWidth={2} />;
      })}
      {Array.from({length: 13}, (_, i) => {
        const x = (i / 12) * W;
        return (
          <line
            key={`c-${i}`}
            x1={W / 2 + (x - W / 2) * 0.08}
            y1={horizon}
            x2={x}
            y2={H}
            stroke={gridLine}
            strokeWidth={2}
          />
        );
      })}
    </g>
  );
};

/** A wall of racks receding into the dark: the data-centre establishing shot. */
const DataCenterEnv: React.FC<{palette: ArtPalette; frame: number}> = ({palette: p, frame}) => {
  const horizon = 980;
  const light = isLight(p.skyTop);
  return (
    <g>
      <rect width={W} height={H} fill={p.skyTop} />
      <rect width={W} height={horizon} fill={p.skyBottom} />
      {/* far wall of racks */}
      {Array.from({length: 9}, (_, i) => {
        const x = 40 + i * 118;
        const height = 300 + ((i * 37) % 90);
        return (
          <g key={`wall-${i}`}>
            <rect
              x={x}
              y={horizon - height}
              width={96}
              height={height}
              fill={light ? mix(p.skyBottom, p.prop, 0.28) : shade(p.primary, 0.78)}
            />
            {Array.from({length: Math.floor(height / 26)}, (_, r) => (
              <rect
                key={r}
                x={x + 8}
                y={horizon - height + 12 + r * 26}
                width={80}
                height={5}
                fill={alpha(p.accent, (frame / 20 + r + i) % 3 < 1 ? 0.42 : 0.12)}
              />
            ))}
          </g>
        );
      })}
      <Floor palette={p} horizon={horizon} opacity={0.45} />
      <rect y={horizon} width={W} height={H - horizon} fill={p.ground} opacity={light ? 0.45 : 0.35} />
      {/* overhead cable tray */}
      <path
        d={`M0 240 Q${W / 2} 150 ${W} 240`}
        fill="none"
        stroke={light ? alpha(p.prop, 0.35) : shade(p.prop, 0.2)}
        strokeWidth={18}
        opacity={0.75}
      />
    </g>
  );
};

/** A PCB: traces at right angles, pads, and a slow pulse running along them. */
const CircuitEnv: React.FC<{palette: ArtPalette; frame: number}> = ({palette: p, frame}) => {
  const pulse = (frame / 60) % 1;
  const light = isLight(p.skyTop);
  return (
    <g>
      <rect width={W} height={H} fill={p.skyTop} />
      <g opacity={light ? 0.6 : 0.5}>
        {Array.from({length: 22}, (_, i) => {
          const y = 80 + i * 82;
          const turn = 200 + ((i * 137) % 620);
          const lit = Math.abs((i / 22) - pulse) < 0.06;
          return (
            <g key={`trace-${i}`}>
              <path
                d={`M-40 ${y} H${turn} V${y + 60} H${turn + 220}`}
                fill="none"
                stroke={light ? alpha(p.prop, 0.22) : shade(p.prop, 0.1)}
                strokeWidth={5}
                strokeLinecap="square"
              />
              <path
                d={`M-40 ${y} H${turn} V${y + 60} H${turn + 220}`}
                fill="none"
                stroke={p.accent}
                strokeWidth={7}
                strokeLinecap="square"
                opacity={lit ? 0.85 : 0}
              />
            </g>
          );
        })}
      </g>
      {Array.from({length: 14}, (_, i) => (
        <circle
          key={`pad-${i}`}
          cx={120 + ((i * 211) % 840)}
          cy={140 + ((i * 333) % 1600)}
          r={9}
          fill={alpha(p.accent, light ? 0.25 : 0.35)}
        />
      ))}
    </g>
  );
};

/** Space: a star field with a faint nebula wash. */
const SpaceEnv: React.FC<{palette: ArtPalette; frame: number}> = ({palette: p, frame}) => {
  const light = isLight(p.skyTop);
  return (
    <g>
      <rect width={W} height={H} fill={light ? mix(p.prop, '#1A140E', 0.8) : shade(p.skyTop, 0.55)} />
      <ellipse cx={W * 0.7} cy={H * 0.3} rx={620} ry={480} fill={alpha(p.accent, 0.12)} />
      <ellipse cx={W * 0.25} cy={H * 0.7} rx={520} ry={400} fill={alpha(p.prop, 0.10)} />
      {Array.from({length: 140}, (_, i) => {
        const x = (i * 613) % W;
        const y = (i * 947) % H;
        const twinkle = 0.35 + 0.65 * Math.abs(Math.sin(frame / 40 + i));
        return <circle key={`s-${i}`} cx={x} cy={y} r={i % 7 === 0 ? 3 : 1.6} fill={tint(p.accent, 0.8)} opacity={twinkle * 0.8} />;
      })}
    </g>
  );
};

/** A clean lab: bright, tiled floor, soft panel light from above. */
const LabEnv: React.FC<{palette: ArtPalette}> = ({palette: p}) => {
  const light = isLight(p.skyTop);
  return (
    <g>
      <rect width={W} height={H} fill={p.skyTop} />
      <rect y={1100} width={W} height={H - 1100} fill={p.ground} />
      {Array.from({length: 8}, (_, i) => (
        <line
          key={`f-${i}`}
          x1={0}
          y1={1100 + i * 110}
          x2={W}
          y2={1100 + i * 110}
          stroke={light ? alpha(p.prop, 0.2) : tint(p.ground, 0.15)}
          strokeWidth={2}
        />
      ))}
      {Array.from({length: 7}, (_, i) => (
        <rect
          key={`lamp-${i}`}
          x={80 + i * 140}
          y={90}
          width={86}
          height={14}
          rx={7}
          fill={tint(p.accent, 0.65)}
          opacity={0.8}
        />
      ))}
      <rect width={W} height={H} fill={alpha(p.accent, 0.04)} />
    </g>
  );
};

/** A skyline: the corporate-story backdrop. */
const CityEnv: React.FC<{palette: ArtPalette; frame: number}> = ({palette: p, frame}) => {
  const light = isLight(p.skyTop);
  return (
    <g>
      <rect width={W} height={H} fill={p.skyTop} />
      {Array.from({length: 26}, (_, i) => {
        const w = 60 + ((i * 71) % 90);
        const x = i * 44 - 30;
        const height = 320 + ((i * 193) % 700);
        return (
          <g key={`b-${i}`}>
            <rect
              x={x}
              y={H - height}
              width={w}
              height={height}
              fill={light ? mix(p.skyBottom, p.prop, 0.22 + (i % 4) * 0.08) : shade(p.skyTop, 0.45)}
            />
            {Array.from({length: Math.floor(height / 46)}, (_, r) =>
              Array.from({length: Math.max(1, Math.floor(w / 26))}, (_, c) => {
                const on = (frame / 22 + r + c + i) % 5 < 2;
                return (
                  <rect
                    key={`${r}-${c}`}
                    x={x + 10 + c * 26}
                    y={H - height + 20 + r * 46}
                    width={12}
                    height={16}
                    fill={on ? tint(p.accent, 0.4) : (light ? alpha(p.prop, 0.2) : shade(p.primary, 0.5))}
                    opacity={on ? 0.85 : 0.5}
                  />
                );
              }),
            )}
          </g>
        );
      })}
      <rect y={H - 160} width={W} height={160} fill={light ? p.ground : shade(p.ink, 0.4)} />
    </g>
  );
};

/** An abstract grid: nothing but structure, for a diagram with no place. */
const GridEnv: React.FC<{palette: ArtPalette; frame: number}> = ({palette: p, frame}) => {
  const drift = (frame / 3) % 80;
  const light = isLight(p.skyTop);
  return (
    <g>
      <rect width={W} height={H} fill={p.skyTop} />
      {Array.from({length: 26}, (_, i) => (
        <line
          key={`gv-${i}`}
          x1={i * 44}
          y1={0}
          x2={i * 44}
          y2={H}
          stroke={alpha(p.accent, light ? 0.14 : 0.09)}
          strokeWidth={1.6}
        />
      ))}
      {Array.from({length: 46}, (_, i) => (
        <line
          key={`gh-${i}`}
          x1={0}
          y1={(i * 44 + drift) % H}
          x2={W}
          y2={(i * 44 + drift) % H}
          stroke={alpha(p.accent, light ? 0.14 : 0.09)}
          strokeWidth={1.6}
        />
      ))}
      <ellipse cx={W / 2} cy={H * 0.45} rx={520} ry={620} fill={alpha(p.accent, light ? 0.06 : 0.1)} />
    </g>
  );
};

/** Ocean floor: seabed contour, subtle light rays from surface, cable resting zone. */
const OceanFloorEnv: React.FC<{palette: ArtPalette; frame: number}> = ({palette: p, frame}) => {
  const wave = Math.sin(frame / 36) * 12;
  return (
    <g>
      <defs>
        <linearGradient id="oceanGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={p.skyTop} />
          <stop offset="55%" stopColor={p.skyBottom} />
          <stop offset="100%" stopColor={p.groundFar} />
        </linearGradient>
      </defs>
      <rect width={W} height={H} fill="url(#oceanGrad)" />
      {/* Gentle water light rays */}
      <polygon points={`120,0 ${280 + wave},0 ${440 + wave},${H * 0.72} 80,${H * 0.72}`} fill={alpha(p.accent, 0.05)} />
      <polygon points={`520,0 ${680 + wave},0 ${820 + wave},${H * 0.72} 460,${H * 0.72}`} fill={alpha(p.accent, 0.04)} />
      {/* Seabed layers */}
      <path
        d={`M0,${H * 0.74} Q${W * 0.3},${H * 0.71} ${W * 0.6},${H * 0.75} T${W},${H * 0.73} L${W},${H} L0,${H} Z`}
        fill={alpha(p.groundFar, 0.6)}
      />
      <path
        d={`M0,${H * 0.78} Q${W * 0.4},${H * 0.76} ${W * 0.75},${H * 0.8} T${W},${H * 0.77} L${W},${H} L0,${H} Z`}
        fill={p.ground}
      />
    </g>
  );
};

/** Kitchen / warm domestic: clean countertop, soft backsplash, warm atmosphere. */
const KitchenEnv: React.FC<{palette: ArtPalette}> = ({palette: p}) => (
  <g>
    <rect width={W} height={H} fill={p.skyTop} />
    {/* Subtle wall tile lines */}
    {Array.from({length: 8}, (_, i) => (
      <line
        key={`kt-${i}`}
        x1={0}
        y1={H * 0.2 + i * 80}
        x2={W}
        y2={H * 0.2 + i * 80}
        stroke={alpha(p.prop, 0.16)}
        strokeWidth={1.5}
        strokeDasharray="40 2"
      />
    ))}
    {/* Countertop surface */}
    <rect y={H * 0.68} width={W} height={36} fill={p.groundFar} />
    <rect y={H * 0.7} width={W} height={H * 0.3} fill={p.ground} />
    <line x1={0} y1={H * 0.68} x2={W} y2={H * 0.68} stroke={alpha(p.ink, 0.12)} strokeWidth={2} />
  </g>
);

const AbstractEnv: React.FC<{palette: ArtPalette; frame?: number}> = ({palette: p, frame = 0}) => {
  const pulse = Math.sin(frame / 45) * 20;
  return (
    <g>
      <rect width={W} height={H} fill={p.skyTop} />
      <ellipse cx={W * 0.2 + pulse * 0.5} cy={H * 0.25} rx={560} ry={520} fill={alpha(p.skyBottom, 0.55)} />
      <ellipse cx={W * 0.85 - pulse} cy={H * 0.75} rx={620} ry={560} fill={alpha(p.accent, 0.08)} />
      <rect y={H * 0.72} width={W} height={H * 0.28} fill={alpha(p.ground, 0.4)} />
    </g>
  );
};

export const Environment: React.FC<{
  kind?: EnvironmentKind;
  environment?: EnvironmentKind;
  palette?: ArtPalette;
  frame?: number;
}> = ({kind, environment, palette, frame}) => {
  let remotionFrame = 0;
  try {
    remotionFrame = useCurrentFrame();
  } catch {
    // not in a Remotion context
  }
  const effectiveFrame = frame ?? remotionFrame;
  const effectiveKind = kind || environment || 'abstract';
  const p = palette || DEFAULT_PALETTE;
  switch (effectiveKind) {
    case 'dataCenter':
      return <DataCenterEnv palette={p} frame={effectiveFrame} />;
    case 'circuit':
      return <CircuitEnv palette={p} frame={effectiveFrame} />;
    case 'space':
      return <SpaceEnv palette={p} frame={effectiveFrame} />;
    case 'lab':
      return <LabEnv palette={p} />;
    case 'city':
      return <CityEnv palette={p} frame={effectiveFrame} />;
    case 'grid':
      return <GridEnv palette={p} frame={effectiveFrame} />;
    case 'oceanFloor':
      return <OceanFloorEnv palette={p} frame={effectiveFrame} />;
    case 'kitchen':
      return <KitchenEnv palette={p} />;
    case 'abstract':
    default:
      return <AbstractEnv palette={p} frame={effectiveFrame} />;
  }
};

export const ENVIRONMENT_SIZE = {width: W, height: H};

const withEnvDefault = (Comp: React.FC<any>): React.FC<{palette?: ArtPalette; frame?: number}> => {
  const Wrapped: React.FC<{palette?: ArtPalette; frame?: number}> = ({palette, frame}) => {
    let remotionFrame = 0;
    try {
      remotionFrame = useCurrentFrame();
    } catch {
      // not in a Remotion context
    }
    const effectiveFrame = frame ?? remotionFrame;
    return <Comp palette={palette || DEFAULT_PALETTE} frame={effectiveFrame} />;
  };
  return Wrapped;
};

export const DataCenterEnvWrapped = withEnvDefault(DataCenterEnv);
export const CircuitEnvWrapped = withEnvDefault(CircuitEnv);
export const SpaceEnvWrapped = withEnvDefault(SpaceEnv);
export const LabEnvWrapped = withEnvDefault(LabEnv);
export const CityEnvWrapped = withEnvDefault(CityEnv);
export const GridEnvWrapped = withEnvDefault(GridEnv);
export const OceanFloorEnvWrapped = withEnvDefault(OceanFloorEnv);
export const KitchenEnvWrapped = withEnvDefault(KitchenEnv);
export const AbstractEnvWrapped = withEnvDefault(AbstractEnv);

export {
  DataCenterEnvWrapped as DataCenterEnv,
  DataCenterEnvWrapped as envDataCenter,
  DataCenterEnvWrapped as dataCenterEnv,
  CircuitEnvWrapped as CircuitEnv,
  CircuitEnvWrapped as envCircuit,
  CircuitEnvWrapped as circuitEnv,
  SpaceEnvWrapped as SpaceEnv,
  SpaceEnvWrapped as envSpace,
  SpaceEnvWrapped as spaceEnv,
  LabEnvWrapped as LabEnv,
  LabEnvWrapped as envLab,
  LabEnvWrapped as labEnv,
  CityEnvWrapped as CityEnv,
  CityEnvWrapped as envCity,
  CityEnvWrapped as cityEnv,
  GridEnvWrapped as GridEnv,
  GridEnvWrapped as envGrid,
  GridEnvWrapped as gridEnv,
  OceanFloorEnvWrapped as OceanFloorEnv,
  OceanFloorEnvWrapped as envOceanFloor,
  OceanFloorEnvWrapped as oceanFloorEnv,
  KitchenEnvWrapped as KitchenEnv,
  KitchenEnvWrapped as envKitchen,
  KitchenEnvWrapped as kitchenEnv,
  AbstractEnvWrapped as AbstractEnv,
  AbstractEnvWrapped as envAbstract,
  AbstractEnvWrapped as abstractEnv,
};
