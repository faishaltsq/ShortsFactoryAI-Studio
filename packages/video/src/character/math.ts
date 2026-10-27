/**
 * Deterministic numeric helpers. Every animation value in the character engine
 * derives from the frame number through these functions: no clocks, no state,
 * no Math.random. Two renders of the same frame are byte-identical.
 */

export const clamp = (value: number, low = 0, high = 1): number =>
  Number.isFinite(value) ? Math.min(high, Math.max(low, value)) : low;

export const lerp = (a: number, b: number, t: number): number => a + (b - a) * t;

export const smoothstep = (t: number): number => {
  const p = clamp(t);
  return p * p * (3 - 2 * p);
};

export const easeInOutCubic = (t: number): number => {
  const p = clamp(t);
  return p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2;
};

export const easeOutCubic = (t: number): number => 1 - Math.pow(1 - clamp(t), 3);

export const easeInCubic = (t: number): number => Math.pow(clamp(t), 3);

/** Overshoots past 1 then settles. Used for anticipation-free punchy accents. */
export const easeOutBack = (t: number, overshoot = 1.70158): number => {
  const p = clamp(t) - 1;
  return 1 + (overshoot + 1) * p * p * p + overshoot * p * p;
};

/** Winds back below 0 before moving forward. Reads as anticipation. */
export const easeInBack = (t: number, overshoot = 1.70158): number => {
  const p = clamp(t);
  return (overshoot + 1) * p * p * p - overshoot * p * p;
};

/**
 * Damped settle: rises to 1, overshoots once, then rings down.
 * `damping` controls how quickly the ring dies, `frequency` how many wobbles.
 */
export const dampedSettle = (t: number, damping = 5.5, frequency = 1.35): number => {
  const p = clamp(t);
  if (p <= 0) return 0;
  return 1 - Math.exp(-damping * p) * Math.cos(frequency * Math.PI * 2 * p);
};

/** Shortest signed angular distance in degrees, for interpolation across ±180. */
export const angleDelta = (from: number, to: number): number => {
  let delta = (to - from) % 360;
  if (delta > 180) delta -= 360;
  if (delta < -180) delta += 360;
  return delta;
};

export const mixAngle = (from: number, to: number, t: number): number => from + angleDelta(from, to) * t;

/** Frame-normalised phase in 0..1, safe for a zero or negative duration. */
export const phase = (frame: number, duration: number): number =>
  duration > 0 ? clamp(frame / duration) : 1;

export const hash01 = (seed: number): number => {
  let t = (Math.floor(seed) + 0x6d2b79f5) | 0;
  t = Math.imul(t ^ (t >>> 15), t | 1);
  t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};

/**
 * Deterministic blink schedule. Returns 0 (open) .. 1 (closed).
 * A blink lasts ~5 frames and recurs every 3.2-5.2s, offset per actor so a
 * two-character scene never blinks in lockstep.
 */
export const blinkAt = (frame: number, fps: number, seed: number): number => {
  const period = Math.round((3.2 + hash01(seed) * 2) * fps);
  const offset = Math.round(hash01(seed + 91) * period);
  const local = (((frame + offset) % period) + period) % period;
  const close = Math.max(2, Math.round(fps * 0.09));
  if (local > close * 2) return 0;
  // Down over `close` frames, up over `close` frames.
  const t = local <= close ? local / close : 1 - (local - close) / close;
  return clamp(t);
};
