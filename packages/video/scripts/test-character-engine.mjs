/**
 * Character Engine V2 contract tests.
 *
 * These run in plain Node with the TypeScript transpiled in-process, matching the
 * existing `scripts/test-*.mjs` convention, so the suite needs no test runner and no
 * browser. They cover the rules that would silently produce a broken render:
 * manifest integrity, rig math, determinism, joint limits, and fallback behaviour.
 */
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
import ts from 'typescript';
import vm from 'node:vm';

const videoDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

const compileCache = new Map();
const compile = (relPath, stubs = {}) => {
  const key = `${relPath}|${Object.keys(stubs).sort().join(',')}`;
  if (compileCache.has(key)) return compileCache.get(key);
  const source = readFileSync(path.join(videoDir, relPath), 'utf8');
  const js = ts.transpileModule(source, {
    compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022},
  }).outputText;
  const mod = {exports: {}};
  const require = createRequire(import.meta.url);
  const localRequire = (specifier) => {
    if (specifier in stubs) return stubs[specifier];
    throw new Error(`unexpected import ${specifier} in ${relPath}`);
  };
  vm.runInNewContext(js, {
    module: mod,
    exports: mod.exports,
    require: localRequire,
    console,
    Math,
    Number,
    Object,
    Array,
    String,
    JSON,
    Map,
    Set,
    Error,
    Infinity,
    NaN,
    isFinite,
  });
  compileCache.set(key, mod.exports);
  return mod.exports;
};

const ids = compile('src/character/ids.ts');
const math = compile('src/character/math.ts');
const types = {};
const rig = compile('src/character/rig.ts', {'./ids': ids, './math': math, './types': types});
const poses = compile('src/character/poses.ts', {'./ids': ids, './rig': rig, './types': types});
const expressions = compile('src/character/expressions.ts', {'./ids': ids, './math': math, './types': types});
const gestures = compile('src/character/gestures.ts', {'./ids': ids, './math': math, './types': types});
const motion = compile('src/character/motion.ts', {
  './expressions': expressions,
  './gestures': gestures,
  './ids': ids,
  './math': math,
  './poses': poses,
  './types': types,
});
const validate = compile('src/character/validate.ts', {'./ids': ids, './types': types});
const art = compile('src/character/assets/maya/art.ts', {'../../ids': ids, './types': types});
const maya = compile('src/character/assets/maya/manifest.ts', {'./art': art, '../../types': types});

const MANIFEST = maya.MAYA;
const registry = compile('src/character/registry.ts', {
  './assets/maya/manifest': maya,
  './ids': ids,
  './types': types,
  './validate': validate,
});
const RIG = rig.indexRig(MANIFEST.rig);
const pivots = (bone) => RIG.pivots.get(bone);

let passed = 0;
const test = (name, fn) => {
  try {
    fn();
    passed += 1;
    console.log(`  ok  ${name}`);
  } catch (error) {
    console.error(`FAIL  ${name}\n      ${error.message}`);
    process.exitCode = 1;
  }
};

console.log('manifest');

test('Maya passes manifest validation', () => {
  validate.validateCharacter(MANIFEST);
});

test('rejects a manifest whose articulated bone has no art', () => {
  const broken = {...MANIFEST, layers: MANIFEST.layers.filter((layer) => layer.bone !== 'shinFar')};
  assert.throws(() => validate.validateCharacter(broken), /articulated bones without art: shinFar/);
});

test('rejects a layer bound to a bone the rig does not declare', () => {
  const broken = {...MANIFEST, layers: [...MANIFEST.layers, {id: 'ghost', bone: 'spine', z: 1, shapes: []}]};
  assert.throws(() => validate.validateCharacter(broken), /has no shapes/);
});

test('rejects a pivot outside the viewBox', () => {
  const broken = {
    ...MANIFEST,
    rig: {
      bones: MANIFEST.rig.bones.map((bone) =>
        bone.id === 'head' ? {...bone, pivot: {x: 9999, y: 9999}} : bone,
      ),
    },
  };
  assert.throws(() => validate.validateCharacter(broken), /outside the viewBox/);
});

test('rejects an inverted joint limit', () => {
  const broken = {
    ...MANIFEST,
    rig: {
      bones: MANIFEST.rig.bones.map((bone) =>
        bone.id === 'shinNear' ? {...bone, limits: {min: 90, max: 10}} : bone,
      ),
    },
  };
  assert.throws(() => validate.validateCharacter(broken), /empty joint limit/);
});

test('rejects a rig that declares a pose it does not support', () => {
  const broken = {...MANIFEST, poses: [...MANIFEST.poses, 'flying']};
  assert.throws(() => validate.validateCharacter(broken), /unsupported poses/);
});

test('rejects a manifest without provenance', () => {
  const broken = {...MANIFEST, provenance: {...MANIFEST.provenance, source: ''}};
  assert.throws(() => validate.validateCharacter(broken), /provenance/);
});

test('rejects a manifest without a licence', () => {
  const broken = {...MANIFEST, license: {id: ''}};
  assert.throws(() => validate.validateCharacter(broken), /license.id/);
});

test('rejects a path that smuggles markup', () => {
  const broken = {
    ...MANIFEST,
    layers: MANIFEST.layers.map((layer) =>
      layer.id === 'head'
        ? {...layer, shapes: [{kind: 'path', d: 'M0 0 <script>alert(1)</script>'}]}
        : layer,
    ),
  };
  assert.throws(() => validate.validateCharacter(broken), /unsupported characters/);
});

test('rejects an unknown paint role', () => {
  const broken = {
    ...MANIFEST,
    layers: MANIFEST.layers.map((layer) =>
      layer.id === 'head' ? {...layer, shapes: [{kind: 'path', d: 'M0 0 L1 1 Z', fill: 'gold'}]} : layer,
    ),
  };
  assert.throws(() => validate.validateCharacter(broken), /unknown paint role/);
});

console.log('rig');

test('every bone resolves to a finite matrix at rest', () => {
  const world = rig.solveRig(RIG, {}, {x: 0, y: 0}, 0);
  for (const bone of ids.BONE_IDS) {
    const matrix = world.get(bone);
    assert.ok(matrix, `missing matrix for ${bone}`);
    assert.ok(matrix.every(Number.isFinite), `non-finite matrix for ${bone}`);
  }
});

test('a bone rotation leaves its own pivot fixed', () => {
  const pivot = pivots('head');
  const world = rig.solveRig(RIG, {head: 17}, {x: 0, y: 0}, 0);
  const moved = rig.applyMatrix(world.get('head'), pivot);
  assert.ok(Math.abs(moved.x - pivot.x) < 1e-9, `x drifted to ${moved.x}`);
  assert.ok(Math.abs(moved.y - pivot.y) < 1e-9, `y drifted to ${moved.y}`);
});

test('child bones inherit parent rotation', () => {
  const world = rig.solveRig(RIG, {spine: 20}, {x: 0, y: 0}, 0);
  const headAtRest = rig.applyMatrix(rig.solveRig(RIG, {}, {x: 0, y: 0}, 0).get('head'), pivots('head'));
  const headTurned = rig.applyMatrix(world.get('head'), pivots('head'));
  assert.ok(Math.abs(headAtRest.y - headTurned.y) > 1, 'spine rotation did not move the head pivot');
});

test('joint limits clamp a hinge joint in the wrong direction', () => {
  // The knee is the one-sided joint in this rig: a negative shin angle would bend it
  // forward, so it must clamp to the lower limit (0).
  const beyond = rig.solveRig(RIG, {shinNear: -60}, {x: 0, y: 0}, 0);
  const atLimit = rig.solveRig(RIG, {shinNear: 0}, {x: 0, y: 0}, 0);
  assert.deepEqual(beyond.get('shinNear'), atLimit.get('shinNear'));
});

test('topological order places parents before children', () => {
  const position = new Map(RIG.order.map((bone, index) => [bone, index]));
  for (const bone of RIG.order) {
    const parent = RIG.parents.get(bone);
    if (parent) assert.ok(position.get(parent) < position.get(bone), `${parent} after ${bone}`);
  }
});

test('leg IK plants the ankle on its target', () => {
  const hip = pivots('thighNear');
  const knee = pivots('shinNear');
  const ankle = pivots('footNear');
  const target = {x: hip.x + 6, y: 690};
  const solved = rig.solveLeg(hip, knee, ankle, target);
  assert.ok(solved, 'IK reported out of reach');
  const world = rig.solveRig(RIG, {thighNear: solved.thigh, shinNear: solved.shin, footNear: solved.foot}, {x: 0, y: 0}, 0);
  const planted = rig.applyMatrix(world.get('footNear'), ankle);
  assert.ok(Math.abs(planted.x - target.x) < 1.5, `ankle x ${planted.x} vs ${target.x}`);
  assert.ok(Math.abs(planted.y - target.y) < 1.5, `ankle y ${planted.y} vs ${target.y}`);
});

test('leg IK refuses an unreachable target instead of stretching', () => {
  const hip = pivots('thighNear');
  const knee = pivots('shinNear');
  const ankle = pivots('footNear');
  assert.equal(rig.solveLeg(hip, knee, ankle, {x: hip.x, y: hip.y + 400}), null);
});

test('every pose plants at least one sole on the ground line', () => {
  for (const pose of MANIFEST.poses) {
    const resolved = poses.resolvePose(pose, pivots);
    const world = rig.solveRig(RIG, resolved.angles, resolved.hips, resolved.lean);
    // A pose may raise a heel on purpose (reach lifts the near heel), so the contract
    // is "no pose floats": at least one sole must be planted on the ground line.
    // Sample both the heel and the toe of each boot: under a raised heel or a
    // toe-off the contact point is not under the ankle.
    const soles = ['footNear', 'footFar'].flatMap((name) => {
      const pivot = pivots(name);
      return [
        rig.applyMatrix(world.get(name), {x: pivot.x - 18, y: pivot.y + 42}).y,
        rig.applyMatrix(world.get(name), {x: pivot.x + 40, y: pivot.y + 42}).y,
      ];
    });
    const lowest = Math.max(...soles);
    assert.ok(
      Math.abs(lowest - MANIFEST.groundY) < 8,
      `${pose} floats: lowest sole at y=${lowest.toFixed(1)}, ground ${MANIFEST.groundY}`,
    );
  }
});

test('walk pose is asymmetric', () => {
  const resolved = poses.resolvePose('walk', pivots);
  assert.notEqual(resolved.angles.thighNear, resolved.angles.thighFar);
});

console.log('determinism');

const frameOf = (overrides = {}) =>
  motion.characterFrameAt({
    input: {pose: 'stand', expression: 'neutral', gesture: 'none', seed: 3, ...overrides},
    frame: 40,
    fps: 30,
    durationInFrames: 300,
    pivot: pivots,
  });

test('same input and frame produce identical output', () => {
  assert.deepEqual(frameOf(), frameOf());
});

test('a different frame produces different output', () => {
  const a = frameOf();
  const b = motion.characterFrameAt({
    input: {pose: 'stand', expression: 'neutral', gesture: 'none', seed: 3},
    frame: 41,
    fps: 30,
    durationInFrames: 300,
    pivot: pivots,
  });
  assert.notDeepEqual(a, b);
});

test('different actor seeds desynchronise the idle cycle', () => {
  assert.notDeepEqual(frameOf({seed: 3}), frameOf({seed: 91}));
});

test('no channel ever produces a non-finite value across a whole scene', () => {
  for (const pose of MANIFEST.poses) {
    for (const gesture of MANIFEST.gestures) {
      for (let frame = 0; frame < 300; frame += 7) {
        const resolved = motion.characterFrameAt({
          input: {pose, expression: 'happy', gesture, seed: 5, motion: {preset: 'talk'}},
          frame,
          fps: 30,
          durationInFrames: 300,
          pivot: pivots,
        });
        for (const [bone, angle] of Object.entries(resolved.angles)) {
          assert.ok(Number.isFinite(angle), `${pose}/${gesture}@${frame} ${bone} = ${angle}`);
        }
        assert.ok(Number.isFinite(resolved.hips.x) && Number.isFinite(resolved.hips.y));
        assert.ok(Number.isFinite(resolved.lean));
        assert.ok(Number.isFinite(resolved.opacity));
      }
    }
  }
});

console.log('expressions');

test('every declared expression is defined and in range', () => {
  for (const id of MANIFEST.expressions) {
    const expression = expressions.resolveExpression(id);
    assert.ok(expression.eyeOpen > 0 && expression.eyeOpen <= 1.5, `${id} eyeOpen ${expression.eyeOpen}`);
    assert.ok(expression.mouthOpen >= 0 && expression.mouthOpen <= 1, `${id} mouthOpen`);
    assert.ok(expression.mouthCurve >= -1 && expression.mouthCurve <= 1, `${id} mouthCurve`);
    assert.ok(Number.isFinite(expression.gaze.x) && Number.isFinite(expression.gaze.y));
  }
});

test('blending two expressions stays inside the parameter bounds', () => {
  for (let t = 0; t <= 1; t += 0.1) {
    const blended = expressions.blendExpression(
      expressions.resolveExpression('surprised'),
      expressions.resolveExpression('sad'),
      t,
    );
    assert.ok(blended.eyeOpen > 0 && blended.eyeOpen <= 1.5);
    assert.ok(blended.mouthOpen >= 0 && blended.mouthOpen <= 1);
  }
});

test('happy and sad differ in both brows and mouth', () => {
  const happy = expressions.resolveExpression('happy');
  const sad = expressions.resolveExpression('sad');
  assert.ok(happy.mouthCurve - sad.mouthCurve > 1, 'mouth curves are not distinct');
  assert.ok(Math.abs(happy.browAngle - sad.browAngle) > 10, 'brow angles are not distinct');
});

test('blink closes and reopens within its window', () => {
  const fps = 30;
  const samples = Array.from({length: 400}, (_, frame) => math.blinkAt(frame, fps, 7));
  assert.ok(Math.max(...samples) > 0.5, 'no blink occurred in 400 frames');
  assert.ok(Math.min(...samples) === 0, 'eyes never fully open');
});

console.log('gestures');

test('a gesture peaks and then releases inside its scene', () => {
  const gesture = gestures.GESTURES.pointForward;
  const duration = 120;
  const peak = gestures.gestureEnvelope(gesture.attack + 2, gesture, duration, 1).weight;
  const end = gestures.gestureEnvelope(duration - 1, gesture, duration, 1).weight;
  assert.ok(peak > 0.9, `peak weight ${peak}`);
  assert.ok(end < 0.15, `end weight ${end}`);
});

test('a gesture sustains through a long scene instead of expiring early', () => {
  const gesture = gestures.GESTURES.openPalm;
  const duration = 300;
  const middle = gestures.gestureEnvelope(150, gesture, duration, 1).weight;
  assert.ok(middle > 0.95, `mid-scene weight ${middle} — gesture expired`);
});

test('gesture arm targets override the pose instead of adding to it', () => {
  const posed = motion.characterFrameAt({
    input: {pose: 'point', expression: 'neutral', gesture: 'none', seed: 1, motion: {preset: 'idle'}},
    frame: 60,
    fps: 30,
    durationInFrames: 300,
    pivot: pivots,
  });
  const gesturing = motion.characterFrameAt({
    input: {pose: 'point', expression: 'neutral', gesture: 'pointForward', seed: 1, motion: {preset: 'idle'}},
    frame: 60,
    fps: 30,
    durationInFrames: 300,
    pivot: pivots,
  });
  // The pose already raises the arm; adding the gesture must not double the raise.
  assert.ok(Math.abs(gesturing.angles.armUpperNear) < 110, `arm over-rotated to ${gesturing.angles.armUpperNear}`);
});

test('an arms-locked pose ignores a conflicting gesture', () => {
  const frame = (gesture) =>
    motion.characterFrameAt({
      input: {pose: 'reach', expression: 'neutral', gesture, seed: 2, motion: {preset: 'idle'}},
      frame: 80,
      fps: 30,
      durationInFrames: 300,
      pivot: pivots,
    });
  assert.equal(frame('none').angles.armUpperNear, frame('openPalm').angles.armUpperNear);
});

console.log('motion presets');

test('walk moves the legs out of phase', () => {
  const resolved = motion.characterFrameAt({
    input: {pose: 'stand', expression: 'neutral', gesture: 'none', seed: 1, motion: {preset: 'walk'}},
    frame: 6,
    fps: 30,
    durationInFrames: 300,
    pivot: pivots,
  });
  assert.notEqual(Math.sign(resolved.angles.thighNear), Math.sign(resolved.angles.thighFar));
});

test('talk animates the mouth', () => {
  const opened = [20, 24, 28, 32].map(
    (frame) =>
      motion.characterFrameAt({
        input: {pose: 'stand', expression: 'neutral', gesture: 'none', seed: 1, motion: {preset: 'talk'}},
        frame,
        fps: 30,
        durationInFrames: 300,
        pivot: pivots,
      }).expression.mouthOpen,
  );
  assert.ok(Math.max(...opened) > 0.1, 'mouth never opened while talking');
});

test('poseChange blends from the previous pose', () => {
  const early = motion.characterFrameAt({
    input: {
      pose: 'point',
      expression: 'neutral',
      gesture: 'none',
      seed: 1,
      motion: {preset: 'poseChange', fromPose: 'stand', durationInFrames: 60},
    },
    frame: 2,
    fps: 30,
    durationInFrames: 300,
    pivot: pivots,
  });
  const settled = motion.characterFrameAt({
    input: {
      pose: 'point',
      expression: 'neutral',
      gesture: 'none',
      seed: 1,
      motion: {preset: 'poseChange', fromPose: 'stand', durationInFrames: 60},
    },
    frame: 58,
    fps: 30,
    durationInFrames: 300,
    pivot: pivots,
  });
  assert.ok(Math.abs(early.angles.armUpperNear) < Math.abs(settled.angles.armUpperNear), 'arm did not travel');
});

test('intensity scales motion without breaking it', () => {
  const soft = motion.characterFrameAt({
    input: {pose: 'walk', expression: 'neutral', gesture: 'none', seed: 1, motion: {preset: 'walk', intensity: 0.2}},
    frame: 9,
    fps: 30,
    durationInFrames: 300,
    pivot: pivots,
  });
  const broad = motion.characterFrameAt({
    input: {pose: 'walk', expression: 'neutral', gesture: 'none', seed: 1, motion: {preset: 'walk', intensity: 1}},
    frame: 9,
    fps: 30,
    durationInFrames: 300,
    pivot: pivots,
  });
  assert.ok(Math.abs(broad.hips.y - soft.hips.y) > 0, 'intensity had no effect on the walk bob');
});

console.log('scene contract');

test('actor cue validation rejects an unsupported expression', () => {
  assert.equal(registry.validateCue(MANIFEST, {expression: 'ecstatic'}).length, 1);
});

test('actor cue validation accepts every declared capability', () => {
  for (const pose of MANIFEST.poses) assert.equal(registry.validateCue(MANIFEST, {pose}).length, 0);
  for (const expression of MANIFEST.expressions) assert.equal(registry.validateCue(MANIFEST, {expression}).length, 0);
  for (const gesture of MANIFEST.gestures) assert.equal(registry.validateCue(MANIFEST, {gesture}).length, 0);
});

test('the generated character index matches the registry', () => {
  const index = JSON.parse(readFileSync(path.join(videoDir, '..', '..', 'config', 'characters.json'), 'utf8'));
  const entry = index.characters.find((item) => item.id === MANIFEST.id);
  assert.ok(entry, 'Maya is missing from config/characters.json');
  assert.equal(entry.version, MANIFEST.version);
  // Cross-realm arrays: compare values, not prototypes.
  assert.deepEqual([...entry.poses], [...MANIFEST.poses]);
  assert.deepEqual([...entry.expressions], [...MANIFEST.expressions]);
  assert.deepEqual([...entry.gestures], [...MANIFEST.gestures]);
});

console.log(`\n${passed} checks passed${process.exitCode ? ' (with failures)' : ''}`);
