import {BONE_IDS, type BoneId} from './ids';
import {clamp, mixAngle} from './math';
import type {BoneAngles, Point, RigSpec} from './types';

/**
 * 2D affine matrix in SVG order: [a, b, c, d, e, f].
 * x' = a·x + c·y + e ; y' = b·x + d·y + f
 */
export type Matrix = readonly [number, number, number, number, number, number];

export const IDENTITY: Matrix = [1, 0, 0, 1, 0, 0];

export const multiply = (m: Matrix, n: Matrix): Matrix => [
  m[0] * n[0] + m[2] * n[1],
  m[1] * n[0] + m[3] * n[1],
  m[0] * n[2] + m[2] * n[3],
  m[1] * n[2] + m[3] * n[3],
  m[0] * n[4] + m[2] * n[5] + m[4],
  m[1] * n[4] + m[3] * n[5] + m[5],
];

const translate = (x: number, y: number): Matrix => [1, 0, 0, 1, x, y];

const rotate = (degrees: number): Matrix => {
  const rad = (degrees * Math.PI) / 180;
  const cos = Math.cos(rad);
  const sin = Math.sin(rad);
  return [cos, sin, -sin, cos, 0, 0];
};

export const applyMatrix = (m: Matrix, point: Point): Point => ({
  x: m[0] * point.x + m[2] * point.y + m[4],
  y: m[1] * point.x + m[3] * point.y + m[5],
});

export const matrixToSvg = (m: Matrix): string =>
  `matrix(${m.map((v) => (Number.isFinite(v) ? Number(v.toFixed(5)) : 0)).join(' ')})`;

export interface RigIndex {
  order: BoneId[];
  parents: Map<BoneId, BoneId | null>;
  pivots: Map<BoneId, Point>;
  limits: Map<BoneId, {min: number; max: number}>;
}

/** Validate + flatten a rig once, so per-frame solving does no lookups by string. */
export const indexRig = (rig: RigSpec): RigIndex => {
  const seen = new Map<BoneId, {parent: BoneId | null; pivot: Point; limits?: {min: number; max: number}}>();
  for (const bone of rig.bones) {
    if (seen.has(bone.id)) throw new Error(`character rig declares bone ${bone.id} twice`);
    if (!BONE_IDS.includes(bone.id)) throw new Error(`character rig uses unknown bone ${String(bone.id)}`);
    if (!Number.isFinite(bone.pivot.x) || !Number.isFinite(bone.pivot.y)) {
      throw new Error(`character rig bone ${bone.id} has a non-finite pivot`);
    }
    if (bone.limits && !(bone.limits.min <= bone.limits.max)) {
      throw new Error(`character rig bone ${bone.id} has an inverted limit`);
    }
    if (bone.parent !== null && !rig.bones.some((b) => b.id === bone.parent)) {
      throw new Error(`character rig bone ${bone.id} points at missing parent ${bone.parent}`);
    }
    seen.set(bone.id, {parent: bone.parent, pivot: bone.pivot, limits: bone.limits});
  }
  for (const [id, spec] of seen) {
    // Walk up to the root: a cycle would hang the solver instead of failing loudly.
    let cursor: BoneId | null = id;
    let hops = 0;
    while (cursor !== null) {
      const parent: BoneId | null = seen.get(cursor)!.parent;
      if (parent === null) break;
      cursor = parent;
      if (++hops > seen.size) throw new Error(`character rig has a parent cycle at bone ${id}`);
    }
  }

  // Parents before children, so one pass computes every world matrix.
  const order: BoneId[] = [];
  const pending = [...seen.keys()];
  while (pending.length > 0) {
    const next = pending.find((id) => {
      const parent = seen.get(id)!.parent;
      return parent === null || order.includes(parent);
    });
    if (next === undefined) throw new Error('character rig could not be topologically ordered');
    order.push(next);
    pending.splice(pending.indexOf(next), 1);
  }

  return {
    order,
    parents: new Map([...seen].map(([id, spec]) => [id, spec.parent])),
    pivots: new Map([...seen].map(([id, spec]) => [id, spec.pivot])),
    limits: new Map([...seen].filter(([, s]) => s.limits).map(([id, s]) => [id, s.limits!])),
  };
};

const clampAngle = (index: RigIndex, bone: BoneId, angle: number): number => {
  const limit = index.limits.get(bone);
  const finite = Number.isFinite(angle) ? angle : 0;
  return limit ? clamp(finite, limit.min, limit.max) : finite;
};

/**
 * Forward kinematics. Angles are rest-relative degrees; the result maps rest-space
 * art straight into world space, which keeps z-order independent of hierarchy.
 */
export const solveRig = (
  index: RigIndex,
  angles: BoneAngles,
  offset: Point = {x: 0, y: 0},
  lean = 0,
): Map<BoneId, Matrix> => {
  const world = new Map<BoneId, Matrix>();
  const rootAngle = Number.isFinite(lean) ? lean : 0;
  for (const bone of index.order) {
    const parent = index.parents.get(bone) ?? null;
    const parentMatrix = parent === null ? IDENTITY : world.get(parent) ?? IDENTITY;
    const pivot = index.pivots.get(bone)!;
    const own = clampAngle(index, bone, angles[bone] ?? 0);
    // Root carries the whole-body offset and lean; children only rotate.
    const rotateAboutPivot = multiply(
      multiply(translate(pivot.x, pivot.y), rotate(own)),
      translate(-pivot.x, -pivot.y),
    );
    const local =
      parent === null
        ? multiply(multiply(translate(offset.x, offset.y), translate(pivot.x, pivot.y)), multiply(rotate(rootAngle + own), translate(-pivot.x, -pivot.y)))
        : rotateAboutPivot;
    world.set(bone, multiply(parentMatrix, local));
  }
  return world;
};

/** Blend two angle sets with shortest-arc interpolation per bone. */
export const blendAngles = (from: BoneAngles, to: BoneAngles, t: number): BoneAngles => {
  const out: BoneAngles = {};
  for (const bone of BONE_IDS) {
    const a = from[bone];
    const b = to[bone];
    if (a === undefined && b === undefined) continue;
    if (a === undefined) out[bone] = (b as number) * t;
    else if (b === undefined) out[bone] = (a as number) * (1 - t);
    else out[bone] = mixAngle(a, b, t);
  }
  return out;
};

/** Additive composition, used by gestures and secondary motion. */
export const addAngles = (base: BoneAngles, delta: BoneAngles): BoneAngles => {
  const out: BoneAngles = {...base};
  for (const bone of BONE_IDS) {
    const value = delta[bone];
    if (value === undefined) continue;
    out[bone] = (out[bone] ?? 0) + value;
  }
  return out;
};

/**
 * Analytic two-bone leg IK.
 *
 * Rest pose points straight down (+y). `target` is the ankle position in character
 * space. Returns rest-relative degrees for thigh, shin and foot such that the sole
 * sits flat unless `pitch` asks otherwise. Returns null when the target is out of
 * reach, so a caller keeps its authored angles instead of stretching the leg.
 */
export const solveLeg = (
  hip: Point,
  knee: Point,
  ankle: Point,
  target: Point,
  pitch = 0,
): {thigh: number; shin: number; foot: number} | null => {
  const a = Math.hypot(knee.x - hip.x, knee.y - hip.y);
  const b = Math.hypot(ankle.x - knee.x, ankle.y - knee.y);
  const dx = target.x - hip.x;
  const dy = target.y - hip.y;
  const d = Math.hypot(dx, dy);
  if (!(d > 0) || d > a + b - 0.5 || d < Math.abs(a - b) + 0.5) return null;

  // Direction of hip→ankle in the same "straight down is 0" convention as bones.
  const bearing = -Math.atan2(dx, dy);
  const cosAlpha = clamp((d * d + a * a - b * b) / (2 * d * a), -1, 1);
  const alpha = Math.acos(cosAlpha);
  const cosBeta = clamp((a * a + b * b - d * d) / (2 * a * b), -1, 1);
  const beta = Math.acos(cosBeta);

  const deg = (rad: number) => (rad * 180) / Math.PI;
  // Knee leads forward (negative thigh). The shin folds back by the interior
  // supplement, so the knee can never bend the wrong way.
  const thigh = deg(bearing - alpha);
  const shin = 180 - deg(beta);
  const foot = -(thigh + shin) + pitch;
  return {thigh, shin, foot};
};
