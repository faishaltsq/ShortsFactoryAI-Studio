import React from 'react';
import type {Effect} from '../scene-data';
import {alpha, type ArtPalette} from './palette';
import {rand} from './rng';

const W = 1080;
const H = 1920;

export const Effects: React.FC<{list: Effect[]; palette: ArtPalette; frame: number; progress: number}> = ({
  list,
  palette,
  frame,
  progress,
}) => (
  <>
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid slice" style={{position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none'}} aria-hidden="true">
      <defs>
        <linearGradient id="ray-fade" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#ffffff" stopOpacity={0.95} />
          <stop offset="55%" stopColor="#ffffff" stopOpacity={0.45} />
          <stop offset="100%" stopColor="#ffffff" stopOpacity={0} />
        </linearGradient>
        <mask id="ray-fade-mask">
          <rect x={0} y={0} width={W} height={H} fill="url(#ray-fade)" />
        </mask>
      </defs>
      {list.includes('lightRays') ? (
        // Feathered with a gradient mask: hard polygons read as cardboard cut-outs
        // rather than light falling through atmosphere.
        <g opacity={0.2} mask="url(#ray-fade-mask)">
          {Array.from({length: 5}, (_, i) => (
            <polygon
              key={i}
              points={`${420 + i * 46},0 ${560 + i * 46},0 ${900 + i * 120},${H} ${620 + i * 120},${H}`}
              fill={palette.figureAccent}
              opacity={0.3 + rand(i) * 0.3}
              transform={`translate(${Math.sin(frame / 60 + i) * 14} 0)`}
            />
          ))}
        </g>
      ) : null}

      {list.includes('dust') ? (
        <g fill={palette.figure}>
          {Array.from({length: 44}, (_, i) => {
            const drift = frame * (0.5 + rand(i + 7) * 1.6);
            const x = rand(i + 21) * W + Math.sin(frame / 40 + i) * 26;
            const y = H - ((drift + rand(i + 55) * H) % H);
            return <circle key={i} cx={x} cy={y} r={1.6 + rand(i + 91) * 3.2} opacity={0.14 + rand(i + 3) * 0.4} />;
          })}
        </g>
      ) : null}

      {list.includes('stars') ? (
        <g fill={palette.figure}>
          {Array.from({length: 80}, (_, i) => {
            const twinkle = 0.25 + Math.abs(Math.sin(frame / (18 + rand(i) * 30) + i)) * 0.65;
            return (
              <circle key={i} cx={rand(i + 400) * W} cy={rand(i + 500) * H * 0.62} r={1 + rand(i + 600) * 2.4} opacity={twinkle} />
            );
          })}
        </g>
      ) : null}

      {list.includes('speedLines') ? (
        <g stroke={palette.figure} strokeLinecap="round">
          {Array.from({length: 16}, (_, i) => {
            const y = rand(i + 700) * H;
            const length = 90 + rand(i + 800) * 220;
            const x = ((frame * (26 + rand(i + 900) * 40)) % (W + length)) - length;
            return <line key={i} x1={x} y1={y} x2={x + length} y2={y} strokeWidth={2 + rand(i + 950) * 4} opacity={0.16 + rand(i + 990) * 0.3} />;
          })}
        </g>
      ) : null}

      {list.includes('impact') ? (
        <g
          stroke={palette.figureAccent}
          strokeWidth={6}
          strokeLinecap="round"
          opacity={Math.max(0, 1 - progress * 1.4)}
          transform={`translate(${W / 2} ${H * 0.46})`}
        >
          {Array.from({length: 14}, (_, i) => {
            const angle = (i / 14) * Math.PI * 2;
            const inner = 120 + progress * 70;
            const outer = inner + 90 + rand(i + 77) * 120;
            return (
              <line
                key={i}
                x1={Math.cos(angle) * inner}
                y1={Math.sin(angle) * inner}
                x2={Math.cos(angle) * outer}
                y2={Math.sin(angle) * outer}
              />
            );
          })}
        </g>
      ) : null}
    </svg>

    {list.includes('vignette') ? (
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background: `radial-gradient(ellipse at 50% 46%, rgba(0,0,0,0) 46%, ${alpha(palette.ink, 0.62)} 100%)`,
        }}
      />
    ) : null}
  </>
);
