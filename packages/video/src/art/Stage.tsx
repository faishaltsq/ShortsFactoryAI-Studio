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
import type {LayoutMode, CausalStateSpec} from '../types';

export const STAGE_WIDTH = 1080;
export const STAGE_HEIGHT = 1920;
export const TOP_SAFE_PX = 210;
export const BOTTOM_SAFE_PX = 1460; // 1920 - 460px bottom safe zone for captions

/** Clamp object Y coordinate and bounds inside the required vertical safe zones. */
export const clampSafeY = (yPx: number, sizePx: number = 0): number => {
  const half = sizePx / 2;
  const minY = TOP_SAFE_PX + half;
  const maxY = BOTTOM_SAFE_PX - half;
  if (minY <= maxY) {
    return Math.max(minY, Math.min(maxY, yPx));
  }
  return (TOP_SAFE_PX + BOTTOM_SAFE_PX) / 2;
};

/**
 * Computes adaptive coordinates and sizes for stage objects according to the active layout mode.
 * Always clamps within safe zones (top >= 210px, bottom <= 1460px).
 */
export function computeAdaptiveLayout(
  objects: readonly StageObject[],
  layoutMode: LayoutMode = 'DefaultHero',
): StageObject[] {
  if (objects.length === 0) return [];

  let adapted: StageObject[];

  switch (layoutMode) {
    case 'SplitComparison': {
      // Two main objects positioned side-by-side (left: x=0.28, right: x=0.72, y=0.48, size=0.42)
      adapted = objects.map((obj, i) => {
        if (i === 0) {
          return {...obj, x: 0.28, y: 0.48, size: 0.42};
        }
        if (i === 1) {
          return {...obj, x: 0.72, y: 0.48, size: 0.42};
        }
        const tertiaryCount = objects.length - 2;
        const subT = tertiaryCount <= 1 ? 0.5 : (i - 2) / (tertiaryCount - 1);
        const x = tertiaryCount <= 1 ? 0.5 : 0.22 + subT * 0.56;
        const y = 0.70;
        const size = Math.min(obj.size, 0.28);
        return {...obj, x, y, size};
      });
      break;
    }

    case 'RadialNetwork': {
      // Hero in center (x=0.5, y=0.48, size=0.45), secondary objects in orbital/radial positions
      const secondaryCount = objects.length - 1;
      adapted = objects.map((obj, i) => {
        if (i === 0) {
          return {...obj, x: 0.5, y: 0.48, size: 0.45};
        }
        const idx = i - 1;
        const angle = secondaryCount <= 1
          ? 0
          : -Math.PI / 2 + (idx * 2 * Math.PI) / secondaryCount;
        const radX = 0.32;
        const radY = 0.16;
        const x = 0.5 + Math.cos(angle) * radX;
        const y = 0.48 + Math.sin(angle) * radY;
        return {...obj, x, y, size: Math.min(obj.size, 0.3)};
      });
      break;
    }

    case 'LeftRailProcess': {
      // Vertical rail or horizontal step sequence (top-left down to bottom-right)
      adapted = objects.map((obj, i) => {
        if (objects.length > 1) {
          const t = i / (objects.length - 1);
          const x = 0.26 + t * 0.48;
          const y = 0.34 + t * 0.32;
          const size = Math.min(obj.size, 0.38);
          return {...obj, x, y, size};
        }
        return {...obj, x: 0.5, y: 0.48, size: Math.min(obj.size, 0.38)};
      });
      break;
    }

    case 'FullBleedFocus': {
      // Dominant hero (size=0.78, y=0.48), subtle secondary accents
      adapted = objects.map((obj, i) => {
        if (i === 0) {
          return {...obj, x: 0.5, y: 0.48, size: 0.78};
        }
        if (i === 1) {
          return {...obj, x: 0.22, y: 0.72, size: 0.22};
        }
        const tertiaryCount = objects.length - 2;
        const subT = tertiaryCount <= 1 ? 1 : (i - 2) / (tertiaryCount - 1);
        const x = 0.50 + subT * 0.28;
        const y = 0.72;
        const size = Math.min(obj.size, 0.22);
        return {...obj, x, y, size};
      });
      break;
    }

    case 'DefaultHero':
    default: {
      // Existing behavior: primary hero ~0.62 size, supporting objects around it
      adapted = objects.map((obj, i) => {
        if (i === 0) {
          return {...obj, size: obj.size ?? 0.62};
        }
        return {...obj};
      });
      break;
    }
  }

  // Always clamp safe zones: top >= 210px, bottom <= 1460px (leaving 460px bottom safe zone for captions)
  return adapted.map((obj) => {
    const sizePx = obj.size * STAGE_WIDTH;
    const yPx = obj.y * STAGE_HEIGHT;
    const clampedYPx = clampSafeY(yPx, sizePx);
    const halfX = sizePx / 2;
    const minX = halfX + 24;
    const maxX = STAGE_WIDTH - halfX - 24;
    const clampedXPx = minX <= maxX ? Math.max(minX, Math.min(maxX, obj.x * STAGE_WIDTH)) : STAGE_WIDTH / 2;
    return {
      ...obj,
      x: clampedXPx / STAGE_WIDTH,
      y: clampedYPx / STAGE_HEIGHT,
    };
  });
}

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
  subtle?: boolean;
}> = ({object: spec, palette, frame, fps, index, labelColor, subtle = false}) => {
  const Component = OBJECT_COMPONENTS[spec.kind as ObjectKind];
  if (!Component) return null;
  const {x, y, size} = objectCentre(spec);
  const rawAt = spec.at ?? 0;
  // Hero object arrives immediately at frame 0 so the scene is never a blank void.
  // Supporting objects clamp to a reasonable entrance window within the scene.
  const effectiveAt = index === 0 ? 0 : Math.max(0, Math.min(rawAt, 20));
  const enter = arrival(frame, effectiveAt, fps);
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
        opacity: enter * (subtle ? 0.55 : 1),
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
      <Component
        palette={palette}
        frame={Math.max(0, frame - effectiveAt)}
        progress={Math.max(0, Math.min(1, (frame - effectiveAt) / (fps * 2)))}
      />
      {spec.label ? (
        <div
          style={{
            position: 'absolute',
            left: 0,
            right: 0,
            top: size * (OBJECT_CAPTION_Y[spec.kind] ?? 0.94) + 18,
            textAlign: 'center',
            fontFamily: 'Inter, system-ui, sans-serif',
            fontWeight: 600,
            fontSize: 24,
            letterSpacing: '0.01em',
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
  layoutMode?: LayoutMode;
  causalState?: CausalStateSpec;
}> = ({data, environment, palette, frame, labelColor, scale = 1, layoutMode, causalState}) => {
  const {fps} = useVideoConfig();
  const effectiveLayout = layoutMode ?? (data.layoutMode as LayoutMode | undefined) ?? 'DefaultHero';
  const adaptedObjects = React.useMemo(
    () => computeAdaptiveLayout(data.objects, effectiveLayout),
    [data.objects, effectiveLayout],
  );
  const anchors = adaptedObjects.map(objectCentre);

  // Flows: synthesized if RadialNetwork or LeftRailProcess when none declared
  const flowsToRender = React.useMemo(() => {
    if (data.flows.length > 0) return data.flows;
    if (effectiveLayout === 'RadialNetwork' && adaptedObjects.length > 1) {
      return adaptedObjects.slice(1).map((_, i) => ({
        from: 0,
        to: i + 1,
      }));
    }
    if (effectiveLayout === 'LeftRailProcess' && adaptedObjects.length > 1) {
      return adaptedObjects.slice(0, -1).map((_, i) => ({
        from: i,
        to: i + 1,
      }));
    }
    return data.flows;
  }, [data.flows, effectiveLayout, adaptedObjects]);

  // FullBleedFocus: immersive scale animation
  const focusScale = effectiveLayout === 'FullBleedFocus'
    ? interpolate(frame, [0, 150], [0.97, 1.04], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})
    : 1;
  const combinedScale = scale * focusScale;

  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        transform: `scale(${combinedScale})`,
        transformOrigin: '50% 55%',
        overflow: 'hidden',
      }}
    >
      <svg width={STAGE_WIDTH} height={STAGE_HEIGHT} style={{position: 'absolute', inset: 0}} aria-hidden="true">
        <Environment kind={environment} palette={palette} frame={frame} />
      </svg>

      {/* SplitComparison: comparative divider and dual leader anchors */}
      {effectiveLayout === 'SplitComparison' && adaptedObjects.length > 1 && (
        <svg width={STAGE_WIDTH} height={STAGE_HEIGHT} style={{position: 'absolute', inset: 0, pointerEvents: 'none'}} aria-hidden="true">
          <line
            x1={STAGE_WIDTH * 0.5}
            y1={TOP_SAFE_PX + 60}
            x2={STAGE_WIDTH * 0.5}
            y2={BOTTOM_SAFE_PX - 60}
            stroke={alpha(palette.accent, 0.25)}
            strokeWidth={2}
            strokeDasharray="10 8"
          />
          <circle cx={STAGE_WIDTH * 0.5} cy={STAGE_HEIGHT * 0.48} r={28} fill={palette.ink} stroke={alpha(palette.accent, 0.6)} strokeWidth={2} />
          <text
            x={STAGE_WIDTH * 0.5}
            y={STAGE_HEIGHT * 0.48 + 7}
            textAnchor="middle"
            fill={palette.accent}
            fontFamily="Inter, system-ui, sans-serif"
            fontSize={18}
            fontWeight={800}
            letterSpacing="0.05em"
          >
            VS
          </text>
          {anchors[0] && anchors[1] && (
            <>
              <line
                x1={STAGE_WIDTH * 0.5 - 28}
                y1={STAGE_HEIGHT * 0.48}
                x2={anchors[0].x + anchors[0].size * 0.35}
                y2={anchors[0].y}
                stroke={alpha(palette.accent, 0.3)}
                strokeWidth={2}
                strokeDasharray="6 6"
              />
              <line
                x1={STAGE_WIDTH * 0.5 + 28}
                y1={STAGE_HEIGHT * 0.48}
                x2={anchors[1].x - anchors[1].size * 0.35}
                y2={anchors[1].y}
                stroke={alpha(palette.accent, 0.3)}
                strokeWidth={2}
                strokeDasharray="6 6"
              />
            </>
          )}
        </svg>
      )}

      {/* RadialNetwork: orbital guide path */}
      {effectiveLayout === 'RadialNetwork' && adaptedObjects.length > 1 && (
        <svg width={STAGE_WIDTH} height={STAGE_HEIGHT} style={{position: 'absolute', inset: 0, pointerEvents: 'none'}} aria-hidden="true">
          <ellipse
            cx={STAGE_WIDTH * 0.5}
            cy={STAGE_HEIGHT * 0.48}
            rx={STAGE_WIDTH * 0.32}
            ry={STAGE_HEIGHT * 0.16}
            fill="none"
            stroke={alpha(palette.accent, 0.18)}
            strokeWidth={2}
            strokeDasharray="8 6"
          />
        </svg>
      )}

      {/* LeftRailProcess: step sequence rail and numbered badges */}
      {effectiveLayout === 'LeftRailProcess' && adaptedObjects.length > 1 && (
        <svg width={STAGE_WIDTH} height={STAGE_HEIGHT} style={{position: 'absolute', inset: 0, pointerEvents: 'none'}} aria-hidden="true">
          <path
            d={`M ${anchors.map((a) => `${a.x} ${a.y}`).join(' L ')}`}
            fill="none"
            stroke={alpha(palette.accent, 0.35)}
            strokeWidth={3}
            strokeDasharray="12 8"
          />
          {anchors.map((a, idx) => (
            <g key={idx}>
              <circle cx={a.x - a.size * 0.45} cy={a.y - a.size * 0.45} r={18} fill={palette.accent} />
              <text
                x={a.x - a.size * 0.45}
                y={a.y - a.size * 0.45 + 6}
                textAnchor="middle"
                fill={palette.ink}
                fontFamily="Inter, system-ui, sans-serif"
                fontSize={16}
                fontWeight={800}
              >
                {idx + 1}
              </text>
            </g>
          ))}
        </svg>
      )}

      {flowsToRender.map((flow, i) =>
        anchors[flow.from] && anchors[flow.to] ? (
          <Flow key={`flow-${i}`} flow={flow} from={anchors[flow.from]} to={anchors[flow.to]} palette={palette} frame={frame} />
        ) : null,
      )}
      {adaptedObjects.map((spec, i) => (
        <PlacedObject
          key={`obj-${i}`}
          object={spec}
          palette={palette}
          frame={frame}
          fps={fps}
          index={i}
          labelColor={labelColor}
          subtle={effectiveLayout === 'FullBleedFocus' && i > 0}
        />
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
