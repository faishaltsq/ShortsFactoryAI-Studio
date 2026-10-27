/**
 * Exact-integer hash mapped to 0..1. Never Math.random(): a Remotion render must
 * produce identical frames on every run, and the pipeline hashes the artifacts.
 */
export const rand = (seed: number): number => {
  let t = (seed + 0x6d2b79f5) | 0;
  t = Math.imul(t ^ (t >>> 15), t | 1);
  t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};

export const randRange = (seed: number, min: number, max: number): number => min + rand(seed) * (max - min);
