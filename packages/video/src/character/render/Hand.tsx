import React from 'react';
import type {HandPose} from '../ids';

/**
 * Parametric hand, authored pointing down +y from the wrist.
 *
 * At 1080×1920 a hand is roughly 55 px tall in a medium shot and 130 px in a close
 * up. Three evenly spaced finger strokes at that size read as a claw, so the shapes
 * are built the way a hand actually reads in silhouette:
 *
 * - a rounded finger mass with two crease lines (relaxed)
 * - four separated fingers only when the hand is genuinely open
 * - one extended index with the rest curled (point)
 * - a closed mass with a knuckle crease (fist)
 */
export const Hand: React.FC<{
  pose: HandPose;
  length: number;
  width: number;
  skin: string;
  shade: string;
  ink: string;
}> = ({pose, length, width, skin, shade, ink}) => {
  const palmLength = length * 0.46;
  const palmWidth = width * (pose === 'fist' ? 0.96 : 0.94);
  const fingerBase = palmLength * 0.96;

  const palm = `M${-palmWidth * 0.46} 0
    C${-palmWidth * 0.54} ${palmLength * 0.34} ${-palmWidth * 0.5} ${palmLength * 0.76} ${-palmWidth * 0.34} ${palmLength * 0.94}
    C${-palmWidth * 0.1} ${palmLength * 1.06} ${palmWidth * 0.18} ${palmLength * 1.02} ${palmWidth * 0.36} ${palmLength * 0.9}
    C${palmWidth * 0.5} ${palmLength * 0.72} ${palmWidth * 0.52} ${palmLength * 0.32} ${palmWidth * 0.44} 0 Z`;

  // Thumb: a separate mass on the near side, crossing the palm from high up.
  const thumb = `M${-palmWidth * 0.36} ${palmLength * 0.2}
    C${-palmWidth * 0.66} ${palmLength * 0.22} ${-palmWidth * 0.74} ${palmLength * 0.44} ${-palmWidth * 0.6} ${palmLength * 0.6}
    C${-palmWidth * 0.46} ${palmLength * 0.72} ${-palmWidth * 0.32} ${palmLength * 0.64} ${-palmWidth * 0.3} ${palmLength * 0.5} Z`;

  /** Finger mass for relaxed / fist / point: one rounded block, not four strokes. */
  const fingerMass = (() => {
    if (pose === 'fist') {
      return `M${-palmWidth * 0.34} ${fingerBase}
        C${-palmWidth * 0.36} ${fingerBase + length * 0.1} ${palmWidth * 0.3} ${fingerBase + length * 0.12} ${palmWidth * 0.34} ${fingerBase}
        C${palmWidth * 0.3} ${fingerBase - length * 0.02} ${-palmWidth * 0.3} ${fingerBase - length * 0.02} ${-palmWidth * 0.34} ${fingerBase} Z`;
    }
    // Relaxed and point share the mass; `point` adds an extended index on top.
    // Relaxed hand: a narrow finger mass, clearly shorter than the palm, so the hand
    // reads as palm + fingers rather than one paddle.
    return `M${-palmWidth * 0.34} ${fingerBase - length * 0.02}
      C${-palmWidth * 0.36} ${fingerBase + length * 0.16} ${-palmWidth * 0.14} ${fingerBase + length * 0.23} ${palmWidth * 0.01} ${fingerBase + length * 0.22}
      C${palmWidth * 0.18} ${fingerBase + length * 0.2} ${palmWidth * 0.36} ${fingerBase + length * 0.12} ${palmWidth * 0.36} ${fingerBase - length * 0.02}
      C${palmWidth * 0.16} ${fingerBase + length * 0.03} ${-palmWidth * 0.14} ${fingerBase + length * 0.03} ${-palmWidth * 0.34} ${fingerBase - length * 0.02} Z`;
  })();

  const openFingers = [
    {x: palmWidth * 0.3, len: length * 0.26, angle: -20},
    {x: palmWidth * 0.1, len: length * 0.32, angle: -7},
    {x: -palmWidth * 0.11, len: length * 0.3, angle: 7},
    {x: -palmWidth * 0.31, len: length * 0.23, angle: 22},
  ];

  return (
    <g>
      {pose === 'open'
        ? openFingers.map((finger, index) => {
            const rad = (finger.angle * Math.PI) / 180;
            return (
              <line
                key={index}
                x1={finger.x}
                y1={fingerBase}
                x2={finger.x + Math.sin(rad) * finger.len}
                y2={fingerBase + Math.cos(rad) * finger.len}
                stroke={skin}
                strokeWidth={width * 0.19}
                strokeLinecap="round"
              />
            );
          })
        : null}
      <path d={palm} fill={skin} />
      {pose === 'point' ? (
        <path
          // Extended index: one tapered digit above the curled mass.
          d={`M${-width * 0.06} ${fingerBase} L${-width * 0.045} ${fingerBase + length * 0.42}
              C${-width * 0.02} ${fingerBase + length * 0.46} ${width * 0.045} ${fingerBase + length * 0.45} ${width * 0.055} ${fingerBase + length * 0.4}
              L${width * 0.075} ${fingerBase} Z`}
          fill={skin}
        />
      ) : null}
      <path d={fingerMass} fill={skin} />
      <path d={thumb} fill={skin} />
      {/* Creases: two short strokes give the finger mass structure without clawing. */}
      {pose !== 'fist' && pose !== 'open' ? (
        <g stroke={shade} strokeWidth={width * 0.045} strokeLinecap="round" fill="none" opacity={0.5}>
          <path d={`M${-palmWidth * 0.11} ${fingerBase + length * 0.03} L${-palmWidth * 0.095} ${fingerBase + length * 0.15}`} />
          <path d={`M${palmWidth * 0.1} ${fingerBase + length * 0.03} L${palmWidth * 0.09} ${fingerBase + length * 0.14}`} />
        </g>
      ) : null}
      {/* Knuckle crease on the fist. */}
      {pose === 'fist' ? (
        <path
          d={`M${-palmWidth * 0.26} ${fingerBase + length * 0.04} Q0 ${fingerBase + length * 0.1} ${palmWidth * 0.26} ${fingerBase + length * 0.03}`}
          stroke={shade}
          strokeWidth={width * 0.08}
          strokeLinecap="round"
          fill="none"
          opacity={0.7}
        />
      ) : null}
      {/* Thumb shadow, so the digit separates from the palm. */}
      <path
        d={`M${-palmWidth * 0.32} ${palmLength * 0.24} C${-palmWidth * 0.5} ${palmLength * 0.3} ${-palmWidth * 0.56} ${palmLength * 0.44} ${-palmWidth * 0.48} ${palmLength * 0.54}`}
        stroke={shade}
        strokeWidth={width * 0.06}
        strokeLinecap="round"
        fill="none"
        opacity={0.6}
      />
      {/* Back-of-hand core shadow on the far edge. Flat fill, no gradient. */}
      <path
        d={`M${palmWidth * 0.24} 0 C${palmWidth * 0.4} ${palmLength * 0.3} ${palmWidth * 0.44} ${palmLength * 0.64} ${palmWidth * 0.34} ${palmLength * 0.86}
            L${palmWidth * 0.44} ${palmLength * 0.82} C${palmWidth * 0.5} ${palmLength * 0.56} ${palmWidth * 0.46} ${palmLength * 0.22} ${palmWidth * 0.38} 0 Z`}
        fill={shade}
        opacity={0.4}
      />
      {/* Wrist crease: a short arc inside the wrist, not a line across it. A straight
          line reads as a cut when the hand is rotated by a gesture. */}
      <path
        d={`M${-palmWidth * 0.3} ${palmLength * 0.08} Q0 ${palmLength * 0.13} ${palmWidth * 0.28} ${palmLength * 0.07}`}
        stroke={ink}
        strokeWidth={width * 0.05}
        strokeLinecap="round"
        fill="none"
        opacity={0.2}
      />
    </g>
  );
};
