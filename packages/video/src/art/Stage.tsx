/**
 * The stage: an environment, the objects standing in it, and the links between them.
 *
 * There are no actors here and no rig. The composition of a frame is decided by the storyboard's
 * object list, and every animated thing on screen is one of: an object arriving, an object being
 * highlighted, a packet travelling a flow, or a callout appearing. That closed set is what keeps
 * the engine honest — any motion a viewer sees has a declared cause in `scene.data`.
 */

import React from 'react';
import {interpolate, spring, useVideoConfig} from 'remotion';
import {Environment} from './Environment';
import {OBJECT_COMPONENTS} from './objects';
import {OBJECT_CAPTION_Y, type ObjectKind} from './object-kinds';
import {alpha, shade, type ArtPalette, type EnvironmentKind} from './palette';
import type {CalloutSpec, ExplainerData, FlowSpec, StageObject} from '../scene-data';

export const STAGE_WIDTH = 1080;
export const STAGE_HEIGHT = 1920;

/** Where an object's centre sits, in stage pixels. */
export const objectCentre = (object: StageObject): {x: number; y: number; size: number} => ({
  x: object.x * STAGE_WIDTH,
  y: object.y * STAGE_HEIGHT,
  size: object.size * STAGE_WIDTH,
});

/** 0..1 arrival weight for one object at `frame`. Objects never pop: they rise and settle. */
const arrival = (frame: number, at: number, fps: number): number => {
  const raw = spring({frame: Math.max(0, frame - at), fps, config: {damping: 18, stiffness: 120, mass: 0.9}});
  return Number.isFinite(raw) ? Math.min(1, Math.max(0, raw)) : 1;
};

/** 0..1 how lit an object is inside its declared highlight window. */
const highlightAt = (frame: number, window: readonly [number, number] | undefined): number => {
  if (!window) return 0;
  const [start, end] = window;
  if (frame < start || frame > end) return 0;
  // Ramp in and out over a tenth of the window so the highlight reads as a breath, not a switch.
  const span = Math.max(1, end - start);
  const ramp = Math.min(span * 0.25, 8);
  return Math.min(1, Math.min((frame - start) / Math.max(1, ramp), (end - frame) / Math.max(1, ramp)));
};

const PlacedObject: React.FC<{
  object: StageObject;
  palette: ArtPalette;
  frame: number;
  fps: number;
  index: number;
  labelColor: string;
}> = ({object: spec, palette, frame, fps, index, labelColor}) => {
  const Component = OBJECT_COMPONENTS[spec.kind as ObjectKind];
  if (!Component) return null;
  const {x, y, size} = objectCentre(spec);
  const enter = arrival(frame, spec.at ?? 0, fps);
  const lit = highlightAt(frame, spec.highlight);
  const lift = (1 - enter) * 60;
  // A highlight grows the object by 3% and drops a soft ring behind it. Both read at 1080px wide;
  // a colour change alone did not.
  const scale = 1 + lit * 0.03;
  const ringR = size * (0.52 + lit * 0.06);

  return (
    <div
      style={{
        position: 'absolute',
        left: x - size / 2,
        top: y - size / 2,
        width: size,
        height: size,
        opacity: enter,
        transform: `translateY(${lift}px) scale(${scale})`,
      }}
    >
      {lit > 0.01 ? (
        <svg viewBox={`0 0 ${size} ${size}`} style={{position: 'absolute', inset: 0, width: '100%', height: '100%'}} aria-hidden="true">
          <ellipse cx={size / 2} cy={size / 2} rx={ringR} ry={ringR * 0.92} fill={alpha(palette.accent, 0.1 * lit)} />
          <ellipse
            cx={size / 2}
            cy={size / 2}
            rx={ringR}
            ry={ringR * 0.92}
            fill="none"
            stroke={alpha(palette.accent, 0.45 * lit)}
            strokeWidth={3}
          />
        </svg>
      ) : null}
      <Component palette={palette} frame={frame - (spec.at ?? 0)} progress={0} />
      {spec.label ? (
        <div
          style={{
            position: 'absolute',
            left: 0,
            right: 0,
            top: size * (OBJECT_CAPTION_Y[spec.kind] ?? 0.94) + 24,
            textAlign: 'center',
            fontFamily: 'Inter, system-ui, sans-serif',
            fontWeight: 700,
            fontSize: 26,
            letterSpacing: '0.04em',
            textTransform: 'uppercase',
            color: lit > 0.3 ? palette.accent : labelColor,
            whiteSpace: 'nowrap',
          }}
        >
          {spec.label}
        </div>
      ) : null}
    </div>
  );
};

const Callout: React.FC<{
  callout: CalloutSpec;
  anchor: {x: number; y: number; size: number};
  palette: ArtPalette;
  frame: number;
  fps: number;
}> = ({callout, anchor, palette, frame, fps}) => {
  const enter = arrival(frame, callout.at ?? 0, fps);
  if (enter <= 0) return null;
  const x = anchor.x + callout.dx * STAGE_WIDTH;
  const y = anchor.y + callout.dy * STAGE_HEIGHT;
  // The leader is drawn from the label box back toward the object it names, so a callout is
  // always visibly attached to something rather than floating free.
  const fromX = anchor.x + Math.sign(callout.dx || 1) * anchor.size * 0.42;
  const fromY = anchor.y + Math.sign(callout.dy || 1) * anchor.size * 0.42;
  return (
    <div style={{position: 'absolute', inset: 0, opacity: enter, pointerEvents: 'none'}}>
      <svg width={STAGE_WIDTH} height={STAGE_HEIGHT} style={{position: 'absolute', inset: 0}} aria-hidden="true">
        <line
          x1={fromX}
          y1={fromY}
          x2={x}
          y2={y}
          stroke={alpha(palette.accent, 0.55)}
          strokeWidth={2.5}
          strokeDasharray="10 8"
        />
        <circle cx={fromX} cy={fromY} r={7} fill={palette.accent} />
      </svg>
      <div
        style={{
          position: 'absolute',
          left: x + (callout.dx < 0 ? -16 : 16) + (callout.dx < 0 ? -320 : 0),
          top: y - 30,
          width: 320,
          padding: '14px 18px',
          borderRadius: 14,
          background: alpha(shade(palette.ink, 0.2), 0.82),
          border: `2px solid ${alpha(palette.accent, 0.45)}`,
          fontFamily: 'Inter, system-ui, sans-serif',
          fontSize: 26,
          fontWeight: 600,
          lineHeight: 1.25,
          color: '#ffffff',
        }}
      >
        {callout.text}
      </div>
    </div>
  );
};

const Flow: React.FC<{
  flow: FlowSpec;
  from: {x: number; y: number; size: number};
  to: {x: number; y: number; size: number};
  palette: ArtPalette;
  frame: number;
}> = ({flow, from, to, palette, frame}) => {
  const start = flow.at ?? 0;
  if (frame < start) return null;
  const mx = (from.x + to.x) / 2;
  const my = (from.y + to.y) / 2 - 120;
  const path = `M${from.x} ${from.y} Q${mx} ${my} ${to.x} ${to.y}`;
  // The label sits three quarters of the way along the link, not at its midpoint: an object's own
  // caption lives just under its base, which is exactly where a midpoint label would land.
  const lt = 0.74;
  const lx = (1 - lt) * (1 - lt) * from.x + 2 * (1 - lt) * lt * mx + lt * lt * to.x;
  const ly = (1 - lt) * (1 - lt) * from.y + 2 * (1 - lt) * lt * my + lt * lt * to.y;
  // Three packets per link, evenly phased, so the link reads as a direction rather than a wire.
  return (
    <svg width={STAGE_WIDTH} height={STAGE_HEIGHT} style={{position: 'absolute', inset: 0}} aria-hidden="true">
      <path d={path} fill="none" stroke={alpha(palette.accent, 0.35)} strokeWidth={4} strokeDasharray="14 12" />
      {[0, 1, 2].map((i) => {
        const t = ((frame - start) / 34 + i / 3) % 1;
        // Quadratic Bezier evaluation, matching the `Q` above exactly.
        const px = (1 - t) * (1 - t) * from.x + 2 * (1 - t) * t * mx + t * t * to.x;
        const py = (1 - t) * (1 - t) * from.y + 2 * (1 - t) * t * my + t * t * to.y;
        return <circle key={i} cx={px} cy={py} r={8} fill={palette.accent} opacity={0.9} />;
      })}
      {flow.label ? (
        <g>
          <rect x={lx + 18} y={ly - 19} width={16 + flow.label.length * 14.4} height={38} rx={19} fill={palette.accent} />
          <text
            x={lx + 26}
            y={ly + 7}
            textAnchor="start"
            fill={palette.ink}
            fontFamily="Inter, system-ui, sans-serif"
            fontSize={24}
            fontWeight={700}
          >
            {flow.label}
          </text>
        </g>
      ) : null}
    </svg>
  );
};

export const ObjectStage: React.FC<{
  data: ExplainerData;
  environment: EnvironmentKind;
  palette: ArtPalette;
  frame: number;
  /** Colour for object captions, supplied by the theme so it reads on every environment. */
  labelColor: string;
  scale?: number;
  /** Frames elapsed at scene start, so objects keyed on `at` stay seekable. */
  sceneFrame?: number;
}> = ({data, environment, palette, frame, labelColor, scale = 1}) => {
  const {fps} = useVideoConfig();
  const anchors = data.objects.map(objectCentre);
  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        transform: `scale(${scale})`,
        transformOrigin: '50% 55%',
        overflow: 'hidden',
      }}
    >
      <svg width={STAGE_WIDTH} height={STAGE_HEIGHT} style={{position: 'absolute', inset: 0}} aria-hidden="true">
        <Environment kind={environment} palette={palette} frame={frame} />
      </svg>
      {data.flows.map((flow, i) =>
        anchors[flow.from] && anchors[flow.to] ? (
          <Flow key={`flow-${i}`} flow={flow} from={anchors[flow.from]} to={anchors[flow.to]} palette={palette} frame={frame} />
        ) : null,
      )}
      {data.objects.map((spec, i) => (
        <PlacedObject key={`obj-${i}`} object={spec} palette={palette} frame={frame} fps={fps} index={i} labelColor={labelColor} />
      ))}
      {data.callouts.map((callout, i) =>
        anchors[callout.object] ? (
          <Callout key={`callout-${i}`} callout={callout} anchor={anchors[callout.object]} palette={palette} frame={frame} fps={fps} />
        ) : null,
      )}
    </div>
  );
};

/** Small helper the metric template shares: a value that climbs to its target. */
export const countTo = (frame: number, target: number, start: number, span: number): number =>
  interpolate(frame, [start, start + span], [0, target], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
