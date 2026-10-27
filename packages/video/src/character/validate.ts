import {ARTICULATED_BONES, BONE_IDS, EXPRESSIONS, GESTURES, PAINT_ROLES, POSES, type BoneId} from './ids';
import type {CharacterManifest, ShapeSpec} from './types';

const ID_PATTERN = /^[a-z][a-z0-9_-]{1,31}$/;
const SEMVER = /^\d+\.\d+\.\d+$/;
const HEX = /^#[0-9a-fA-F]{6}$/;

const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

/**
 * Validate a character manifest before any frame renders.
 *
 * This is deliberately strict and separate from cue validation: a broken asset is
 * an engineering defect that must fail loudly, while an invented character id from
 * a language model must degrade gracefully. `validateCharacter` throws; the
 * registry decides what that means for a scene.
 */
export const validateCharacter = (manifest: CharacterManifest): void => {
  const fail = (reason: string): never => {
    throw new Error(`character ${String(manifest?.id ?? '<unknown>')}: ${reason}`);
  };

  if (!ID_PATTERN.test(manifest.id)) fail('id must match ^[a-z][a-z0-9_-]{1,31}$');
  if (!SEMVER.test(manifest.version)) fail('version must be semver (major.minor.patch)');
  if (manifest.artStyle !== 'editorial-vector') fail(`unsupported artStyle ${String(manifest.artStyle)}`);
  if (!manifest.displayName?.trim()) fail('displayName is required');

  // --- geometry ---------------------------------------------------------------
  const {width, height} = manifest.viewBox ?? {width: 0, height: 0};
  const minX = manifest.viewBox?.minX ?? 0;
  const minY = manifest.viewBox?.minY ?? 0;
  if (!finite(minX) || !finite(minY)) fail('viewBox minX/minY must be finite');
  if (!finite(width) || !finite(height) || width <= 0 || height <= 0) fail('viewBox must be positive and finite');
  if (!finite(manifest.groundY) || manifest.groundY <= 0 || manifest.groundY > height) {
    fail('groundY must sit inside the viewBox');
  }

  // --- declared capability ----------------------------------------------------
  for (const [label, declared, allowed] of [
    ['poses', manifest.poses, POSES],
    ['expressions', manifest.expressions, EXPRESSIONS],
    ['gestures', manifest.gestures, GESTURES],
  ] as const) {
    if (!Array.isArray(declared) || declared.length === 0) fail(`${label} must be a non-empty array`);
    const unknown = declared.filter((value) => !(allowed as readonly string[]).includes(value));
    if (unknown.length > 0) fail(`declares unsupported ${label}: ${unknown.join(', ')}`);
    if (new Set(declared).size !== declared.length) fail(`${label} contains duplicates`);
  }
  // A character that cannot stand cannot be placed in a scene.
  if (!manifest.poses.includes('stand')) fail('poses must include stand');

  // --- rig --------------------------------------------------------------------
  if (!manifest.rig || !Array.isArray(manifest.rig.bones) || manifest.rig.bones.length === 0) fail('rig.bones is required');
  const bones = new Map<BoneId, {parent: BoneId | null}>();
  for (const bone of manifest.rig.bones) {
    if (!BONE_IDS.includes(bone.id)) fail(`unknown bone ${String(bone.id)}`);
    if (bones.has(bone.id)) fail(`bone ${bone.id} declared twice`);
    if (!finite(bone.pivot?.x) || !finite(bone.pivot?.y)) fail(`bone ${bone.id} has a non-finite pivot`);
    if (bone.pivot.x < minX || bone.pivot.x > minX + width || bone.pivot.y < minY || bone.pivot.y > minY + height) {
      fail(`bone ${bone.id} pivot lies outside the viewBox`);
    }
    if (bone.limits && !(bone.limits.min < bone.limits.max)) fail(`bone ${bone.id} has an empty joint limit`);
    bones.set(bone.id, {parent: bone.parent});
  }
  for (const [id, spec] of bones) {
    if (spec.parent !== null && !bones.has(spec.parent)) fail(`bone ${id} points at missing parent ${spec.parent}`);
  }
  // Root must exist exactly once and hang off nothing.
  const roots = [...bones].filter(([, spec]) => spec.parent === null);
  if (roots.length !== 1 || roots[0][0] !== 'root') fail('exactly one bone must be the parentless root');
  for (const bone of ARTICULATED_BONES) {
    if (!bones.has(bone)) fail(`rig is missing articulated bone ${bone}`);
  }

  // --- layers -----------------------------------------------------------------
  if (!Array.isArray(manifest.layers) || manifest.layers.length === 0) fail('layers must be a non-empty array');
  const layerIds = new Set<string>();
  const bonesWithArt = new Set<BoneId>();
  for (const layer of manifest.layers) {
    if (!layer.id?.trim()) fail('every layer needs an id');
    if (layerIds.has(layer.id)) fail(`layer id ${layer.id} declared twice`);
    layerIds.add(layer.id);
    if (!bones.has(layer.bone)) fail(`layer ${layer.id} is bound to missing bone ${String(layer.bone)}`);
    if (!finite(layer.z)) fail(`layer ${layer.id} has a non-finite z`);
    if (!Array.isArray(layer.shapes) || layer.shapes.length === 0) fail(`layer ${layer.id} has no shapes`);
    if (layer.opacity !== undefined && !(finite(layer.opacity) && layer.opacity >= 0 && layer.opacity <= 1)) {
      fail(`layer ${layer.id} opacity must be 0..1`);
    }
    for (const shape of layer.shapes) validateShape(shape, layer.id, fail);
    bonesWithArt.add(layer.bone);
  }

  // This is the rule that rejects a flattened image dressed up as a character:
  // every articulated bone must actually carry art, or the limb cannot move.
  const unbound = ARTICULATED_BONES.filter((bone) => !bonesWithArt.has(bone));
  if (unbound.length > 0) fail(`articulated bones without art: ${unbound.join(', ')}`);

  // --- face and hands ---------------------------------------------------------
  if (manifest.face) {
    const face = manifest.face;
    if (!finite(face.anchor?.x) || !finite(face.anchor?.y)) fail('face.anchor must be finite');
    if (!finite(face.width) || !finite(face.height) || face.width <= 0 || face.height <= 0) fail('face size must be positive');
    if (face.turn !== undefined && !(finite(face.turn) && Math.abs(face.turn) <= 35)) fail('face.turn must be within ±35 degrees');
    if (!bones.has('head')) fail('a face requires a head bone');
  }
  if (manifest.hands) {
    if (!finite(manifest.hands.length) || !finite(manifest.hands.width)) fail('hands dimensions must be finite');
    if (manifest.hands.length <= 0 || manifest.hands.width <= 0) fail('hands dimensions must be positive');
    for (const bone of ['handNear', 'handFar'] as const) {
      if (!bones.has(bone)) fail(`hands require bone ${bone}`);
    }
  }

  // --- palette ----------------------------------------------------------------
  if (!manifest.palette) fail('palette is required');
  for (const role of PAINT_ROLES) {
    const value = manifest.palette[role];
    if (typeof value !== 'string' || !HEX.test(value)) fail(`palette.${role} must be a #rrggbb colour`);
  }

  // --- provenance and licence -------------------------------------------------
  if (!manifest.provenance?.author?.trim() || !manifest.provenance?.source?.trim()) {
    fail('provenance.author and provenance.source are required');
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(manifest.provenance.createdAt ?? '')) fail('provenance.createdAt must be YYYY-MM-DD');
  if (!manifest.license?.id?.trim()) fail('license.id is required');
};

const validateShape = (shape: ShapeSpec, layerId: string, fail: (reason: string) => never): void => {
  if (!shape || typeof shape !== 'object') fail(`layer ${layerId} has a non-object shape`);
  if (shape.fill !== undefined && shape.fill !== 'none' && !PAINT_ROLES.includes(shape.fill)) fail(`layer ${layerId} uses unknown paint role ${String(shape.fill)}`);
  if (shape.stroke !== undefined && !PAINT_ROLES.includes(shape.stroke)) fail(`layer ${layerId} uses unknown paint role ${String(shape.stroke)}`);
  if (shape.opacity !== undefined && !(finite(shape.opacity) && shape.opacity >= 0 && shape.opacity <= 1)) {
    fail(`layer ${layerId} has an out-of-range shape opacity`);
  }
  switch (shape.kind) {
    case 'path':
      if (typeof shape.d !== 'string' || !/^[Mm]/.test(shape.d.trim()) || shape.d.length > 6000) {
        fail(`layer ${layerId} has an invalid path (must start with M/m and stay under 6000 chars)`);
      }
      // Only commands and numbers are allowed: a path can never smuggle markup.
      if (!/^[MmZzLlHhVvCcSsQqTtAa0-9eE.,\s+-]+$/.test(shape.d)) fail(`layer ${layerId} path contains unsupported characters`);
      if (shape.stroke !== undefined && !(finite(shape.strokeWidth) && shape.strokeWidth > 0)) {
        fail(`layer ${layerId} stroke needs a positive strokeWidth`);
      }
      break;
    case 'ellipse':
      if (![shape.cx, shape.cy, shape.rx, shape.ry].every(finite) || shape.rx <= 0 || shape.ry <= 0) {
        fail(`layer ${layerId} has an invalid ellipse`);
      }
      break;
    case 'rect':
      if (![shape.x, shape.y, shape.width, shape.height].every(finite) || shape.width <= 0 || shape.height <= 0) {
        fail(`layer ${layerId} has an invalid rect`);
      }
      break;
    default:
      fail(`layer ${layerId} has an unsupported shape kind`);
  }
};
