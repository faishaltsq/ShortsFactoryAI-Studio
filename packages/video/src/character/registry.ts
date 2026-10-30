import {MAYA} from './assets/maya/manifest';
import {EXPRESSIONS, GESTURES, POSES, type ExpressionId, type GestureId, type PoseId} from './ids';
import type {CharacterManifest} from './types';
import {validateCharacter} from './validate';

/**
 * Manifest-level validation. A declared capability without real art behind it is a lie the studio
 * would display, so a declared variant or mouth shape must resolve to something renderable.
 */
export const validateManifest = (manifest: CharacterManifest): string[] => {
  const issues: string[] = [];
  if (manifest.clothingVariants.length === 0) {
    issues.push(`${manifest.id} declares no clothing variants`);
  }
  for (const variant of manifest.clothingVariants) {
    if (variant === 'default') continue;
    const layers = manifest.variantLayers?.[variant];
    if (!layers || layers.length === 0) {
      issues.push(`${manifest.id} declares clothing variant ${variant} with no art`);
    }
  }
  if (manifest.mouthShapes.length === 0) {
    issues.push(`${manifest.id} declares no mouth shapes`);
  }
  // A rig cycle or an unresolved parent would animate silently wrong.
  const known = new Set(manifest.rig.bones.map((bone) => bone.id));
  for (const bone of manifest.rig.bones) {
    if (bone.parent !== null && !known.has(bone.parent)) {
      issues.push(`${manifest.id}: bone ${bone.id} has unresolved parent ${bone.parent}`);
    }
  }
  return issues;
};

const ALL: readonly CharacterManifest[] = [MAYA];

const byId = new Map<string, CharacterManifest>();

/**
 * Eager validation. A malformed asset is a build defect, so it fails at module
 * load (and therefore at `tsc`, test time and the first render) rather than
 * producing a subtly broken frame halfway through a job.
 */
for (const character of ALL) {
  validateCharacter(character);
  for (const problem of validateManifest(character)) {
    throw new Error(`${character.id} manifest: ${problem}`);
  }
  if (byId.has(character.id)) throw new Error(`duplicate character id ${character.id}`);
  byId.set(character.id, character);
}

/** Every registered character, in a stable order. The index exporter enumerates this. */
export const CHARACTERS: readonly CharacterManifest[] = [...byId.values()].sort((a, b) =>
  a.id.localeCompare(b.id),
);
export const CHARACTER_IDS = [...byId.keys()].sort();

export const getCharacter = (id: string): CharacterManifest | undefined => byId.get(id);

export interface CharacterResolution {
  character: CharacterManifest | null;
  /** Present when a requested id could not be served; the renderer falls back. */
  fallbackReason?: string;
}

/**
 * Resolve an actor's requested character. Unknown ids fall back to the procedural
 * figure: a job must not die because a language model invented a name, but the
 * fallback is reported so QC and logs can see it happened.
 */
export const resolveCharacter = (id: string | undefined): CharacterResolution => {
  if (!id) return {character: null};
  const character = byId.get(id);
  if (!character) return {character: null, fallbackReason: `unknown character id ${id}`};
  return {character};
};

/** Cue-level validation: capability checks against a resolved manifest. */
export interface CharacterCue {
  pose?: PoseId;
  expression?: ExpressionId;
  gesture?: GestureId;
}

export const validateCue = (manifest: CharacterManifest, cue: CharacterCue): string[] => {
  const issues: string[] = [];
  if (cue.pose && !manifest.poses.includes(cue.pose)) {
    issues.push(`${manifest.id} does not support pose ${cue.pose}`);
  }
  if (cue.expression && !manifest.expressions.includes(cue.expression)) {
    issues.push(`${manifest.id} does not support expression ${cue.expression}`);
  }
  if (cue.gesture && !manifest.gestures.includes(cue.gesture)) {
    issues.push(`${manifest.id} does not support gesture ${cue.gesture}`);
  }
  return issues;
};

export const CAPABILITIES = {
  poses: POSES,
  expressions: EXPRESSIONS,
  gestures: GESTURES,
} as const;
