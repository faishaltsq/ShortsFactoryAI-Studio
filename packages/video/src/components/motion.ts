import {Easing, interpolate, spring} from 'remotion';

/**
 * Editorial text-motion system for ShortsFactoryAI video engine.
 * Direction: Warm, dignified, editorial motion ("Claude-like").
 *
 * Rules:
 * - Zero cartoon bounce, zero overshoot, zero glitch, zero aggressive pop.
 * - Restrained physical damping (damping >= 22) for smooth, premium deceleration.
 * - Masked reveals and quiet staggered typography for mobile viewing distance.
 *
 * ponytail: deterministic frame-based transforms; add spring velocity caching if composition nesting exceeds 5 levels.
 */

export interface AnimateArgs {
  readonly frame: number;
  readonly fps: number;
  readonly durationInFrames: number;
  readonly intensity?: number;
}

/**
 * Shared editorial easing curves for Remotion interpolate().
 * Smooth, elegant deceleration curves inspired by editorial publishing.
 */
export const EDITORIAL_EASING = {
  /** Smooth exponential ease-out for natural, dignified settles */
  smoothOut: Easing.bezier(0.16, 1, 0.3, 1),
  /** Symmetrical ease-in-out for paced transitions */
  smoothInOut: Easing.bezier(0.65, 0, 0.35, 1),
  /** Restrained cubic out for short text elements */
  cubicOut: Easing.out(Easing.cubic),
  /** Quartic out for subtle drift and breath */
  quartOut: Easing.out(Easing.poly(4)),
} as const;

/**
 * Standard editorial spring profiles.
 * High damping guarantees NO oscillation or bouncy elastic ringing.
 */
export const EDITORIAL_SPRING = {
  /** Standard editorial landing: smooth, zero bounce, crisp landing */
  standard: {damping: 24, stiffness: 110, mass: 0.9},
  /** Gentle settle for larger text blocks and captions */
  gentle: {damping: 28, stiffness: 85, mass: 1.0},
  /** Crisp settle for kicks, badges, and technical labels */
  crisp: {damping: 22, stiffness: 140, mass: 0.8},
} as const;

export interface MaskedRevealArgs extends AnimateArgs {
  readonly direction?: 'up' | 'down' | 'left' | 'right';
}

/**
 * Masked reveal preset (editorial curtain / clip-path inset).
 * Smoothly reveals text from behind an invisible boundary.
 */
export const maskedReveal = ({
  frame,
  durationInFrames,
  direction = 'up',
}: MaskedRevealArgs) => {
  const progress = interpolate(frame, [0, Math.max(1, durationInFrames)], [0, 100], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: EDITORIAL_EASING.smoothOut,
  });

  const opacity = interpolate(frame, [0, Math.max(1, durationInFrames * 0.3)], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  let clipPath: string;
  switch (direction) {
    case 'up':
      // Clip from bottom upwards
      clipPath = `inset(0 0 ${100 - progress}% 0)`;
      break;
    case 'down':
      // Clip from top downwards
      clipPath = `inset(${100 - progress}% 0 0 0)`;
      break;
    case 'left':
      // Clip from right towards left
      clipPath = `inset(0 ${100 - progress}% 0 0)`;
      break;
    case 'right':
      clipPath = `inset(0 0 0 ${100 - progress}%)`;
      break;
  }

  return {
    clipPath,
    opacity,
  };
};

export interface StaggeredWordArgs {
  readonly frame: number;
  readonly fps: number;
  readonly wordIndex: number;
  readonly staggerFrames?: number;
  readonly durationInFrames?: number;
}

/**
 * Staggered per-word editorial reveal.
 * Words glide up with gentle displacement (14px) and zero bounce.
 */
export const staggeredWordReveal = ({
  frame,
  fps,
  wordIndex,
  staggerFrames = 3,
}: StaggeredWordArgs) => {
  const wordStart = wordIndex * staggerFrames;
  const localFrame = Math.max(0, frame - wordStart);

  const spr = spring({
    frame: localFrame,
    fps,
    config: EDITORIAL_SPRING.standard,
  });

  const opacity = interpolate(localFrame, [0, 8], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const translateY = interpolate(spr, [0, 1], [14, 0]);

  return {
    opacity: frame < wordStart ? 0 : opacity,
    transform: `translateY(${translateY.toFixed(2)}px)`,
    display: 'inline-block' as const,
  };
};

export interface SoftSlideFadeArgs extends AnimateArgs {
  readonly distance?: number;
  readonly direction?: 'up' | 'down' | 'left' | 'right';
}

/**
 * Gentle editorial slide + fade.
 * Restrained displacement (default 24px) for dignified arrival.
 */
export const softSlideFade = ({
  frame,
  fps,
  durationInFrames,
  distance = 24,
  direction = 'up',
  intensity = 1,
}: SoftSlideFadeArgs) => {
  const spr = spring({
    frame,
    fps,
    config: EDITORIAL_SPRING.gentle,
  });

  const effectiveDistance = distance * intensity;
  const opacity = interpolate(
    frame,
    [0, Math.max(1, durationInFrames * 0.4)],
    [0, 1],
    {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    }
  );

  let transform: string;
  switch (direction) {
    case 'up':
      transform = `translateY(${interpolate(spr, [0, 1], [effectiveDistance, 0]).toFixed(2)}px)`;
      break;
    case 'down':
      transform = `translateY(${interpolate(spr, [0, 1], [-effectiveDistance, 0]).toFixed(2)}px)`;
      break;
    case 'left':
      transform = `translateX(${interpolate(spr, [0, 1], [effectiveDistance, 0]).toFixed(2)}px)`;
      break;
    case 'right':
      transform = `translateX(${interpolate(spr, [0, 1], [-effectiveDistance, 0]).toFixed(2)}px)`;
      break;
  }

  return {
    opacity,
    transform,
  };
};

export interface ScaleEmphasisArgs extends AnimateArgs {
  readonly fromScale?: number;
  readonly toScale?: number;
}

/**
 * Restrained scale emphasis.
 * Subtle breath (0.97 -> 1.00 or 1.00 -> 1.03) without pop or cartoon zoom.
 */
export const scaleEmphasis = ({
  frame,
  fps,
  fromScale = 0.97,
  toScale = 1.0,
}: ScaleEmphasisArgs) => {
  const spr = spring({
    frame,
    fps,
    config: EDITORIAL_SPRING.standard,
  });

  const scale = interpolate(spr, [0, 1], [fromScale, toScale]);
  const opacity = interpolate(spr, [0, 1], [0.4, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return {
    transform: `scale(${scale.toFixed(4)})`,
    opacity,
  };
};

export interface LineDrawArgs extends AnimateArgs {
  readonly orientation?: 'horizontal' | 'vertical';
}

/**
 * Editorial line draw / underline reveal.
 * Expands a rule or accent line cleanly from left to right.
 */
export const lineDraw = ({
  frame,
  durationInFrames,
  orientation = 'horizontal',
}: LineDrawArgs) => {
  const progress = interpolate(frame, [0, Math.max(1, durationInFrames)], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: EDITORIAL_EASING.smoothOut,
  });

  if (orientation === 'vertical') {
    return {
      transform: `scaleY(${progress.toFixed(4)})`,
      transformOrigin: 'top center',
      opacity: progress > 0 ? 1 : 0,
    };
  }

  return {
    transform: `scaleX(${progress.toFixed(4)})`,
    transformOrigin: 'left center',
    opacity: progress > 0 ? 1 : 0,
  };
};

export interface GentleCountArgs {
  readonly from: number;
  readonly to: number;
  readonly frame: number;
  readonly durationInFrames: number;
  readonly decimals?: number;
  readonly formatter?: (val: number) => string;
}

/**
 * Gentle numeric counting transition for metrics.
 * Uses smooth editorial easing so the number settles gracefully without snapping.
 */
export const gentleCount = ({
  from,
  to,
  frame,
  durationInFrames,
  decimals = 0,
  formatter,
}: GentleCountArgs) => {
  const progress = interpolate(frame, [0, Math.max(1, durationInFrames)], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: EDITORIAL_EASING.smoothOut,
  });

  const rawValue = from + (to - from) * progress;
  const rounded = Number(rawValue.toFixed(decimals));
  const formatted = formatter
    ? formatter(rounded)
    : rounded.toLocaleString('en-US', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      });

  return {
    value: rounded,
    formatted,
    progress,
  };
};

/**
 * Cohesive group reveal.
 * Fades in an entire headline block (kicker + title + subheading) as a single
 * dignified unit with a subtle 12px upward settle.
 */
export const cohesiveGroupReveal = ({
  frame,
  fps,
  durationInFrames,
}: AnimateArgs) => {
  const spr = spring({
    frame,
    fps,
    config: EDITORIAL_SPRING.gentle,
  });

  const opacity = interpolate(
    frame,
    [0, Math.max(1, durationInFrames * 0.4)],
    [0, 1],
    {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    }
  );

  const translateY = interpolate(spr, [0, 1], [12, 0]);

  return {
    opacity,
    transform: `translateY(${translateY.toFixed(2)}px)`,
  };
};

export const EDITORIAL_MOTION_PRESETS = {
  maskedReveal,
  staggeredWordReveal,
  softSlideFade,
  scaleEmphasis,
  lineDraw,
  gentleCount,
  cohesiveGroupReveal,
} as const;
