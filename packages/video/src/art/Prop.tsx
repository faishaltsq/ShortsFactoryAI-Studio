import React from 'react';
import type {IllustrationProp} from '../scene-data';
import {alpha, shade, type ArtPalette} from './palette';

const BOX = 100;

const Shape: React.FC<{kind: IllustrationProp['kind']; palette: ArtPalette}> = ({kind, palette}) => {
  switch (kind) {
    case 'sun':
      return (
        <g>
          <circle cx={50} cy={50} r={46} fill={palette.glow} />
          <circle cx={50} cy={50} r={32} fill={palette.figureAccent} />
        </g>
      );
    case 'moon':
      return (
        <g>
          <circle cx={50} cy={50} r={44} fill={palette.glow} />
          <circle cx={50} cy={50} r={30} fill={palette.prop} />
          <circle cx={62} cy={43} r={26} fill={palette.skyTop} />
        </g>
      );
    case 'planet':
      return (
        <g>
          <circle cx={50} cy={50} r={28} fill={palette.prop} />
          <ellipse cx={50} cy={50} rx={44} ry={13} fill="none" stroke={palette.figureAccent} strokeWidth={5} opacity={0.85} transform="rotate(-18 50 50)" />
        </g>
      );
    case 'star':
      return <path d="M50 6 L58 42 L94 50 L58 58 L50 94 L42 58 L6 50 L42 42 Z" fill={palette.figureAccent} />;
    case 'cloud':
      return (
        <g fill={alpha(palette.figure, 0.72)}>
          <ellipse cx={38} cy={58} rx={26} ry={18} />
          <ellipse cx={62} cy={50} rx={30} ry={22} />
          <ellipse cx={78} cy={60} rx={20} ry={15} />
        </g>
      );
    case 'mountain':
      return <path d="M4 92 L38 26 L58 62 L72 40 L96 92 Z" fill={shade(palette.groundFar, 0.1)} />;
    case 'tree':
      return (
        <g>
          <rect x={44} y={58} width={12} height={38} fill={shade(palette.ground, 0.45)} />
          <circle cx={50} cy={42} r={26} fill={shade(palette.groundFar, 0.15)} />
          <circle cx={34} cy={54} r={17} fill={shade(palette.groundFar, 0.05)} />
          <circle cx={66} cy={54} r={17} fill={shade(palette.groundFar, 0.05)} />
        </g>
      );
    case 'tower':
      return (
        <g>
          <rect x={30} y={14} width={40} height={82} fill={shade(palette.ground, 0.35)} />
          {[0, 1, 2, 3].map((row) => [0, 1].map((col) => (
            <rect key={`${row}-${col}`} x={38 + col * 16} y={24 + row * 18} width={10} height={12} fill={palette.figureAccent} opacity={0.7} />
          )))}
        </g>
      );
    case 'gear':
      return (
        <g fill={palette.prop}>
          <circle cx={50} cy={50} r={26} />
          {Array.from({length: 8}, (_, i) => (
            <rect key={i} x={46} y={8} width={8} height={16} transform={`rotate(${i * 45} 50 50)`} />
          ))}
          <circle cx={50} cy={50} r={10} fill={palette.skyTop} />
        </g>
      );
    case 'book':
      return (
        <g>
          <rect x={16} y={26} width={68} height={52} rx={6} fill={palette.prop} />
          <rect x={16} y={26} width={10} height={52} fill={shade(palette.prop, 0.3)} />
          <line x1={36} y1={44} x2={74} y2={44} stroke={palette.skyTop} strokeWidth={4} />
          <line x1={36} y1={58} x2={66} y2={58} stroke={palette.skyTop} strokeWidth={4} />
        </g>
      );
    case 'wave':
      return (
        <g stroke={palette.figureAccent} strokeWidth={7} fill="none" strokeLinecap="round">
          <path d="M4 44 q22,-18 44,0 t44,0" />
          <path d="M4 64 q22,-18 44,0 t44,0" opacity={0.7} />
        </g>
      );
    case 'clock':
      return (
        <g>
          <circle cx={50} cy={50} r={34} fill={palette.prop} />
          <circle cx={50} cy={50} r={26} fill={palette.skyTop} />
          <line x1={50} y1={50} x2={50} y2={32} stroke={palette.figureAccent} strokeWidth={5} strokeLinecap="round" />
          <line x1={50} y1={50} x2={66} y2={56} stroke={palette.figureAccent} strokeWidth={5} strokeLinecap="round" />
        </g>
      );
    case 'bulb':
      return (
        <g>
          <circle cx={50} cy={40} r={24} fill={palette.figureAccent} />
          <rect x={42} y={62} width={16} height={18} rx={4} fill={palette.prop} />
          <g stroke={palette.figureAccent} strokeWidth={4} strokeLinecap="round">
            <line x1={50} y1={4} x2={50} y2={14} />
            <line x1={20} y1={20} x2={27} y2={27} />
            <line x1={80} y1={20} x2={73} y2={27} />
          </g>
        </g>
      );
    default:
      return (
        <g>
          <line x1={10} y1={50} x2={76} y2={50} stroke={palette.figureAccent} strokeWidth={8} strokeLinecap="round" />
          <path d="M68 32 L92 50 L68 68 Z" fill={palette.figureAccent} />
        </g>
      );
  }
};

export const Prop: React.FC<{
  prop: IllustrationProp;
  palette: ArtPalette;
  frame: number;
  index: number;
  /** 'frame' uses 1080x1920 stage coordinates (Stage); 'box' uses its parent (panels, layers). */
  fit?: 'frame' | 'box';
}> = ({
  prop,
  palette,
  frame,
  index,
  fit = 'frame',
}) => {
  const size = 150 * prop.scale;
  const float = Math.sin(frame / 34 + index * 1.7) * 6 * prop.scale;
  const placement =
    fit === 'box'
      ? {left: `${prop.x * 100}%`, top: `${prop.y * 100}%`, transform: 'translate(-50%, -50%)'}
      : {left: prop.x * 1080 - size / 2, top: prop.y * 1920 - size / 2 + float};
  return (
    <div
      style={{
        position: 'absolute',
        ...placement,
        width: size,
        height: size,
      }}
    >
      <svg viewBox={`0 0 ${BOX} ${BOX}`} style={{width: '100%', height: '100%'}} aria-hidden="true">
        <Shape kind={prop.kind} palette={palette} />
      </svg>
    </div>
  );
};
