import React from 'react';
import type {MouthShape} from '../ids';
import type {ExpressionTarget, Point} from '../types';

/**
 * Parametric face.
 *
 * Layout is measured in character space, anchored on the eye line:
 *
 *   brow   anchor.y - 0.145·height
 *   eyes   anchor.y
 *   nose   anchor.y + 0.18·height
 *   mouth  anchor.y + 0.30·height
 *
 * The eye is built as sclera + iris + pupil + catchlight. A single dark almond
 * reads as a dot at close framing, which is the shot this engine is built for.
 * The far eye is narrower and closer to the nose: that asymmetry is what makes a
 * three-quarter head read as turned rather than as a flat mask.
 */
export const Face: React.FC<{
  expression: ExpressionTarget;
  anchor: Point;
  width: number;
  height: number;
  turn: number;
  palette: {ink: string; skinShade: string; blush: string; sclera: string};
  /**
   * Declared mouth shape. When given, the aperture is drawn to match it; the measured envelope
   * still decides *when* a shape applies, so the shape is a rendering of the measurement rather
   * than a replacement for it.
   */
  mouthShape?: MouthShape;
}> = ({expression, anchor, width, height, turn, palette, mouthShape}) => {
  const {browAngle, browLift, eyeOpen, gaze, mouthWidth, mouthOpen, mouthCurve, cheek, blush} = expression;

  const eyeY = anchor.y;
  const eyeDX = width * 0.2;
  const turnShift = (turn / 35) * width * 0.045;
  const nearEye = {x: anchor.x - eyeDX + turnShift * 0.5, y: eyeY, rx: width * 0.125, ry: width * 0.112};
  const farEye = {x: anchor.x + eyeDX + turnShift, y: eyeY, rx: width * 0.1, ry: width * 0.1};

  const mouthY = anchor.y + height * 0.3;
  const mouthWidthScale = mouthShape === 'wide' ? 1.22 : mouthShape === 'round' ? 0.78 : 1;
  const halfMouth = width * 0.15 * mouthWidth * mouthWidthScale;
  const lidLift = cheek * width * 0.02;
  const open = Math.max(0.08, eyeOpen);

  const eye = (cx: number, cy: number, rx: number, ry: number, isNear: boolean) => {
    const ryOpen = ry * open;
    const pupilX = cx + gaze.x * (isNear ? 1 : 0.8);
    const pupilY = cy + gaze.y * 0.8;

    // Closed or nearly closed: one lash curve. Never a zero-height ellipse.
    if (open < 0.22) {
      return (
        <path
          d={`M${cx - rx} ${cy + ryOpen * 0.15} Q${cx} ${cy + ry * 0.5} ${cx + rx} ${cy + ryOpen * 0.15}`}
          stroke={palette.ink}
          strokeWidth={width * 0.026}
          strokeLinecap="round"
          fill="none"
        />
      );
    }

    // Open eye: sclera, then an iris that fills most of the height but only ~60 % of
    // the width, so there is visible white on both sides. A full-width dark almond
    // reads as a closed eye at any scale, which is the single most common face bug.
    return (
      <g>
        <ellipse cx={cx} cy={cy} rx={rx} ry={ryOpen} fill={palette.sclera} />
        <ellipse cx={pupilX} cy={pupilY} rx={rx * 0.58} ry={ryOpen * 0.9} fill={palette.ink} />
        <circle cx={pupilX - rx * 0.22} cy={pupilY - ryOpen * 0.36} r={Math.max(1.1, rx * 0.2)} fill="#ffffff" opacity={0.95} />
        {/* Lash line sits on the top edge of the sclera and lifts at the outer corner. */}
        <path
          d={`M${cx - rx * 1.02} ${cy - ryOpen * 0.32} Q${cx} ${cy - ryOpen * 1.12} ${cx + rx * 1.04} ${cy - ryOpen * 0.42}`}
          stroke={palette.ink}
          strokeWidth={width * 0.024}
          strokeLinecap="round"
          fill="none"
        />
        {/* Lower lid, raised by a genuine smile. */}
        {lidLift > 0.4 ? (
          <path
            d={`M${cx - rx * 0.85} ${cy + ryOpen * 0.98} Q${cx} ${cy + ryOpen * 0.98 - lidLift} ${cx + rx * 0.85} ${cy + ryOpen * 0.98}`}
            stroke={palette.skinShade}
            strokeWidth={width * 0.014}
            fill="none"
            opacity={0.6}
          />
        ) : null}
      </g>
    );
  };

  const brow = (cx: number, rx: number, mirrored: boolean) => {
    const y = eyeY - height * 0.145 - browLift;
    const tilt = (browAngle / 20) * rx * 0.6;
    // Positive browAngle raises the inner end (concern). Mirrored for the far brow.
    const inner = {x: cx + (mirrored ? -rx * 0.92 : rx * 0.92), y: y + (mirrored ? -tilt : tilt)};
    const outer = {x: cx + (mirrored ? rx * 0.92 : -rx * 0.92), y: y - (mirrored ? -tilt : tilt) * 0.3};
    const peak = {x: (inner.x + outer.x) / 2, y: Math.min(inner.y, outer.y) - width * 0.02};
    return (
      <path
        d={`M${outer.x} ${outer.y} Q${peak.x} ${peak.y} ${inner.x} ${inner.y}`}
        stroke={palette.ink}
        strokeWidth={width * 0.036}
        strokeLinecap="round"
        fill="none"
      />
    );
  };

  // Mouth: one stroked curve when closed, a filled shape when open. The opening is
  // asymmetric so it reads as a mouth on a turned head, not as a centred icon.
  const mouth = (() => {
    const left = {x: anchor.x - halfMouth + turnShift * 0.35, y: mouthY};
    const right = {x: anchor.x + halfMouth + turnShift * 0.35, y: mouthY - mouthCurve * width * 0.006};
    const dip = mouthY + mouthCurve * height * 0.085;
    if (mouthOpen < 0.06) {
      return (
        <path
          d={`M${left.x} ${left.y} Q${(left.x + right.x) / 2} ${dip} ${right.x} ${right.y}`}
          stroke={palette.ink}
          strokeWidth={width * 0.04}
          strokeLinecap="round"
          fill="none"
        />
      );
    }
    // The declared shape scales the aperture within the measured opening. `wide` spreads it
    // horizontally, `round` pulls it in and deepens it; `open` is the neutral band. Without a
    // declared shape the measured amplitude alone drives the geometry, which is the legacy path.
    const shapeScale = mouthShape === 'wide'
      ? {w: 1.22, d: 0.92}
      : mouthShape === 'round'
        ? {w: 0.78, d: 1.3}
        : {w: 1, d: 1};
    const drop = mouthOpen * height * 0.07 * shapeScale.d;
    const top = mouthY - drop * 0.16;
    return (
      <g>
        <path
          d={`M${left.x} ${top} Q${(left.x + right.x) / 2} ${dip - drop * 0.12} ${right.x} ${top} Q${(left.x + right.x) / 2 + halfMouth * 0.15} ${top + drop} ${left.x} ${top} Z`}
          fill={palette.ink}
        />
        {mouthOpen > 0.6 ? (
          <path
            d={`M${left.x + halfMouth * 0.18} ${top + drop * 0.07} Q${(left.x + right.x) / 2} ${top + drop * 0.22} ${right.x - halfMouth * 0.18} ${top + drop * 0.05}`}
            stroke="#f7f2ea"
            strokeWidth={drop * 0.18}
            fill="none"
            opacity={0.9}
          />
        ) : null}
      </g>
    );
  })();

  return (
    <g>
      {/* Nose: one short hook. The shortest readable nose at this scale. */}
      <path
        d={`M${anchor.x + width * 0.015 + turnShift * 0.7} ${eyeY + height * 0.13} q${-width * 0.03} ${height * 0.045} ${width * 0.02} ${height * 0.05}`}
        stroke={palette.skinShade}
        strokeWidth={width * 0.022}
        strokeLinecap="round"
        fill="none"
      />
      {blush > 0.02 ? (
        <g fill={palette.blush} opacity={0.4 * blush}>
          <ellipse cx={nearEye.x - width * 0.055} cy={eyeY + height * 0.12} rx={width * 0.08} ry={width * 0.04} />
          <ellipse cx={farEye.x + width * 0.05} cy={eyeY + height * 0.115} rx={width * 0.055} ry={width * 0.03} />
        </g>
      ) : null}
      {eye(nearEye.x, nearEye.y, nearEye.rx, nearEye.ry, true)}
      {eye(farEye.x, farEye.y, farEye.rx, farEye.ry, false)}
      {brow(nearEye.x, nearEye.rx * 1.15, true)}
      {brow(farEye.x, farEye.rx * 1.2, false)}
      {mouth}
    </g>
  );
};
