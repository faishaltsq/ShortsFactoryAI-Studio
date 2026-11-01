import React from 'react';
import {interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import type {SceneProps} from '../components/NarrativeFrame';
import {InformativeFrame} from '../components/InformativeFrame';
import {Environment} from '../art/Environment';
import {alpha, paletteFor, shade, tint} from '../art/palette';
import {ProcessFlowData, validateSceneData} from '../scene-data';
import {resolveTheme} from '../themes/brand';

const W = 1080;
const H = 1920;
/** Frames one link takes to travel. Every other timing in the template is derived from it. */
const LINK_FRAMES = 26;

/**
 * `ProcessFlow` — how a thing works, one stage at a time.
 *
 * The motion is the explanation: a packet leaves stage *n* and arrives at stage *n+1*, and the stage
 * it lands on lights up. A viewer who reads nothing still learns the order. This is the template for
 * "how a training run works", "how a request reaches a data centre", "how a chip is fabricated".
 */
export const ProcessFlowScene: React.FC<SceneProps> = ({scene, theme: inputTheme, watermark}) => {
  const theme = resolveTheme(inputTheme);
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  validateSceneData(scene);
  const data = scene.data as unknown as ProcessFlowData;
  const palette = paletteFor(theme, data.environment);
  const steps = data.steps;
  const count = steps.length;

  // Nodes sit in a right-hand column; the rail runs down the left so the chain reads top-to-bottom
  // even on a 9:16 frame where a horizontal chain would be illegibly narrow.
  const top = 560;
  const gap = Math.min(300, (H - top - 520) / Math.max(1, count - 1));
  const nodeX = 530;
  const nodeW = 560;
  const nodeH = 168;
  const railX = 176;

  const stepAt = (i: number): number => i * LINK_FRAMES;

  return (
    <InformativeFrame scene={scene} theme={theme} watermark={watermark} title={data.title} caption={data.caption}>
      <svg width={W} height={H} style={{position: 'absolute', inset: 0}} aria-hidden="true">
        <Environment kind={data.environment} palette={palette} frame={frame} />
      </svg>
      <svg width={W} height={H} style={{position: 'absolute', inset: 0}} aria-hidden="true">
        {/* the rail */}
        <line
          x1={railX}
          y1={top}
          x2={railX}
          y2={top + gap * (count - 1)}
          stroke={alpha(palette.accent, 0.25)}
          strokeWidth={6}
          strokeLinecap="round"
        />
        {steps.slice(0, -1).map((_, i) => {
          const linkStart = stepAt(i);
          const local = Math.max(0, frame - linkStart);
          const travelled = Math.min(1, local / LINK_FRAMES);
          const y1 = top + gap * i;
          const y2 = top + gap * (i + 1);
          // The lit segment grows with the packet, so the rail records how far the process has got.
          return (
            <g key={`link-${i}`}>
              <line
                x1={railX}
                y1={y1}
                x2={railX}
                y2={y1 + (y2 - y1) * travelled}
                stroke={palette.accent}
                strokeWidth={6}
                strokeLinecap="round"
                opacity={0.9}
              />
              {local > 0 && travelled < 1 ? (
                <circle cx={railX} cy={y1 + (y2 - y1) * travelled} r={13} fill={tint(palette.accent, 0.45)} />
              ) : null}
            </g>
          );
        })}
      </svg>
      {steps.map((step, i) => {
        const start = stepAt(i);
        const enter = spring({frame: Math.max(0, frame - start), fps, config: {damping: 16, stiffness: 130, mass: 0.8}});
        const weight = Number.isFinite(enter) ? Math.min(1, Math.max(0, enter)) : 1;
        const y = top + gap * i;
        // A stage is "now" for one link's worth of frames after it lands; afterwards it is history
        // and drops back so the current stage is always the brightest thing in the column.
        const current = frame >= start && frame < start + LINK_FRAMES;
        const done = frame >= start + LINK_FRAMES;
        const border = current ? palette.accent : done ? alpha(palette.accent, 0.4) : alpha(palette.ink, 0.3);
        return (
          <React.Fragment key={`step-${i}`}>
          <div
            style={{
              position: 'absolute',
              left: railX,
              top: y - 1.5,
              width: nodeX - nodeW / 2 - railX,
              height: 3,
              background: alpha(palette.accent, current ? 0.9 : 0.3),
            }}
          />
          <div
            style={{
              position: 'absolute',
              left: nodeX - nodeW / 2,
              top: y - nodeH / 2,
              width: nodeW,
              height: nodeH,
              opacity: weight,
              transform: `translateX(${(1 - weight) * 40}px)`,
              borderRadius: 20,
              background: alpha(shade(palette.ink, 0.1), 0.94),
              border: `3px solid ${border}`,
              padding: '22px 26px',
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'center',
              gap: 8,
              boxShadow: current ? `0 0 44px ${alpha(palette.accent, 0.35)}` : 'none',
            }}
          >
            <div style={{display: 'flex', alignItems: 'center', gap: 14}}>
              <div
                style={{
                  width: 40,
                  height: 40,
                  borderRadius: 20,
                  background: current ? palette.accent : alpha(palette.accent, 0.35),
                  color: shade(palette.ink, 0.4),
                  fontFamily: theme.fontHeading,
                  fontSize: 22,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                {i + 1}
              </div>
              <div style={{fontFamily: theme.fontHeading, fontSize: 38, color: theme.primary, lineHeight: 1.1}}>
                {step.label}
              </div>
            </div>
            {step.detail ? (
              <div style={{fontFamily: theme.fontBody, fontSize: 26, color: theme.secondary, lineHeight: 1.25}}>
                {step.detail}
              </div>
            ) : null}
          </div>
          </React.Fragment>
        );
      })}
      {/* Progress readout: the chain's own clock, so the last frame is visibly "finished". */}
      <div
        style={{
          position: 'absolute',
          left: 72,
          right: 72,
          bottom: 190,
          height: 8,
          borderRadius: 4,
          background: alpha(palette.accent, 0.2),
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            height: '100%',
            width: `${interpolate(frame, [0, stepAt(count - 1) + LINK_FRAMES], [0, 100], {
              extrapolateLeft: 'clamp',
              extrapolateRight: 'clamp',
            })}%`,
            background: palette.accent,
          }}
        />
      </div>
    </InformativeFrame>
  );
};
