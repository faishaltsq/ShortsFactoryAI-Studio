/**
 * Adapter test. Plain node, no browser, no Remotion runtime.
 *
 * The adapter is TypeScript, and the modules it imports use extensionless relative imports
 * (`./character/ids`), which Node's type-stripping loader cannot resolve on its own. The hook
 * below adds the `.ts` suffix on a miss; nothing else is rewritten.
 */

import {register} from 'node:module';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';

register('./ts-resolve-hook.mjs', import.meta.url);

const root = fileURLToPath(new URL('..', import.meta.url));
const readJson = (rel) => JSON.parse(readFileSync(new URL(rel, import.meta.url), 'utf8'));

const {adaptProductStoryboard, isProductStoryboard} = await import('../src/product-adapter.ts');
const {validateSceneData} = await import('../src/scene-data.ts');
const {TEMPLATE_IDS} = await import('../src/types.ts');

const PRODUCT = readJson('../fixtures/product-storyboard.json');
const DONOR_ROLES = ['title', 'highlight', 'body', 'caption', 'kicker'];
const DONOR_TRANSITIONS = ['none', 'fade', 'slideUp', 'wipe', 'zoom'];

let failures = 0;
const pass = (message) => console.log(`PASS ${message}`);
const check = (condition, message) => {
  if (condition) {
    pass(message);
  } else {
    failures += 1;
    console.log(`FAIL ${message}`);
  }
};

/** Asserts that `fn` throws an Error whose message names `field`. */
const checkThrowsNaming = (label, fn, field) => {
  try {
    fn();
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    if (!(err instanceof Error)) {
      failures += 1;
      console.log(`FAIL ${label}: threw a non-Error (${message})`);
      return;
    }
    if (message.includes(field)) {
      pass(`${label} -> throws naming "${field}": ${message}`);
    } else {
      failures += 1;
      console.log(`FAIL ${label}: message does not name "${field}": ${message}`);
    }
    return;
  }
  failures += 1;
  console.log(`FAIL ${label}: did not throw`);
};

const clone = (value) => JSON.parse(JSON.stringify(value));

console.log(`# adapter test (root: ${root})`);

check(isProductStoryboard(PRODUCT) === true, 'isProductStoryboard accepts the product fixture');

const adapted = adaptProductStoryboard(PRODUCT);
check(adapted.scenes.length === PRODUCT.scenes.length, `adapted ${adapted.scenes.length} scenes`);
check(adapted.id === 'product-sc1', `id derived deterministically: ${adapted.id}`);
check(adapted.language === 'id', `language is 'id'`);
check(adapted.width === 1080 && adapted.height === 1920 && adapted.fps === 30, 'width/height/fps carried through');
check(
  typeof adapted.theme === 'object' && typeof adapted.theme.background === 'string',
  `theme resolved to an object (id=${adapted.theme.id})`,
);

// Rule 4: an unknown product theme id must land on the documented default palette, not a new one.
// `resolveTheme` keeps the requested `id` string but replaces every colour; nothing in the
// renderer reads `theme.id`, so the palette is what has to be the default.
const {DEFAULT_THEME} = await import('../src/themes/brand.ts');
const unknownTheme = adaptProductStoryboard({...clone(PRODUCT), theme: 'not-a-real-theme'});
const PALETTE_KEYS = ['background', 'backgroundAccent', 'primary', 'secondary', 'accent', 'fontHeading', 'fontBody'];
check(
  PALETTE_KEYS.every((key) => unknownTheme.theme[key] === DEFAULT_THEME[key]),
  `unknown theme falls back to the documented default palette (${DEFAULT_THEME.id})`,
);
check(
  JSON.stringify(adaptProductStoryboard({...clone(PRODUCT), theme: 'not-a-real-theme'}).theme) ===
    JSON.stringify(unknownTheme.theme),
  'unknown theme fallback is deterministic',
);
const knownTheme = adaptProductStoryboard({...clone(PRODUCT), theme: 'ember'});
check(
  knownTheme.theme.id === 'ember' && knownTheme.theme.background === '#1a0f0d',
  'a known theme id resolves to its own palette',
);

// Rule 2: roles.
const roles = adapted.scenes.flatMap((scene) => scene.text.map((element) => element.style.role));
check(
  roles.every((role) => DONOR_ROLES.includes(role)),
  `every text role is donor-legal: ${roles.join(',')}`,
);
check(
  adapted.scenes[0].text[0].style.role === 'title' && adapted.scenes[0].text[1].style.role === 'body',
  'title->title and body->body',
);
check(adapted.scenes[1].text[0].style.role === 'caption', 'caption->caption');
check(adapted.scenes[1].text[1].style.role === 'caption', 'label->caption');
check(adapted.scenes[0].text[1].inFrame === 30, 'inFrame comes from atFrame (30)');

// Rule 3: transitions, one of each kind across the fixture.
const transitions = adapted.scenes.map((scene) => scene.transition.type);
check(
  transitions.every((type) => DONOR_TRANSITIONS.includes(type)),
  `every transition is donor-legal: ${transitions.join(',')}`,
);
check(transitions[0] === 'none', 'cut->none');
check(transitions[1] === 'fade', 'fade->fade');
check(transitions[2] === 'wipe', 'wipe->wipe');
check(adapted.scenes[1].transition.durationInFrames === 15, 'frames carried into durationInFrames (15)');
check(
  adaptProductStoryboard({...clone(PRODUCT), scenes: [{...clone(PRODUCT.scenes[0]), transition: {kind: 'push', frames: 9}}]}).scenes[0].transition.type === 'slideUp',
  'push->slideUp',
);
check(
  adaptProductStoryboard({...clone(PRODUCT), scenes: [{...clone(PRODUCT.scenes[0]), transition: {kind: 'match', frames: 0}}]}).scenes[0].transition.type === 'none',
  'match->none',
);

// Rule 5: subtitles get deterministic ids.
check(adapted.subtitles.length === 2, 'two subtitle cues carried');
check(
  adapted.subtitles.every((cue, index) => cue.id === `sub-${index}`),
  `subtitle ids are sub-<index>: ${adapted.subtitles.map((cue) => cue.id).join(',')}`,
);
check(
  adaptProductStoryboard({...clone(PRODUCT), subtitles: undefined}).subtitles.length === 0,
  'absent subtitles become an empty list',
);

// Rule 6: animation is a constant the contract requires.
check(
  adapted.scenes.every((scene) => scene.animation.preset === 'fadeIn'),
  'animation.preset is fadeIn on every scene',
);

// Rule 6b: the declared camera and motion reach the composition props, typed and verbatim.
// This is the regression the whole change exists for: before it, `adaptScene` emitted neither, so
// `SceneSpec.camera` and `SceneSpec.motion.beats` had no path to a pixel.
const PRODUCT_CAMERA = ['static', 'push', 'pull', 'pan', 'tilt', 'orbit'];
const PRODUCT_EASE = ['linear', 'power1.out', 'power2.out', 'power3.out', 'power4.out', 'power1.in', 'power2.in', 'power2.inOut', 'sine.inOut'];
const PRODUCT_BEATS = ['enter', 'emphasis', 'exit', 'action', 'reveal'];

check(
  adapted.scenes.every((scene) => scene.camera && PRODUCT_CAMERA.includes(scene.camera.move)),
  `every scene carries a camera: ${adapted.scenes.map((s) => s.camera?.move).join(',')}`,
);
check(
  adapted.scenes.every((scene) => PRODUCT_EASE.includes(scene.camera.ease)),
  'every camera carries one of the nine contract easings',
);
check(
  adapted.scenes[0].camera.shot === 'wide' && adapted.scenes[0].camera.move === 'push',
  'camera.shot/move survive the adapter verbatim',
);
check(adapted.scenes[0].camera.amplitude === 0.1, 'camera.amplitude survives verbatim (0.1)');
check(adapted.scenes[0].camera.target === 't1', 'camera.target survives verbatim (t1)');
check(
  adapted.scenes[0].camera.target === PRODUCT.scenes[0].text[0].id,
  'the camera target names a real element of the scene',
);
check(
  adapted.scenes[2].camera.move === 'static' && adapted.scenes[2].camera.target === undefined,
  'a static camera carries no target (nothing was invented)',
);

check(
  adapted.scenes.every((scene) => scene.motion && Array.isArray(scene.motion.beats)),
  `every scene carries motion.beats: ${adapted.scenes.map((s) => s.motion?.beats.length).join(',')}`,
);
check(
  adapted.scenes.every((scene) => typeof scene.motion.energy === 'number' && scene.motion.energy >= 0 && scene.motion.energy <= 1),
  'motion.energy is forwarded as a 0..1 number',
);
check(
  adapted.scenes.every((scene) => scene.motion.continuity === 'cut'),
  'motion.continuity is forwarded (cut)',
);
check(
  adapted.scenes.every((scene) => scene.motion.beats.every((beat) => PRODUCT_BEATS.includes(beat.kind))),
  'every beat kind is one of the five the contract allows',
);
check(
  adapted.scenes[0].motion.beats[1].kind === 'action' && adapted.scenes[0].motion.beats[1].atFrame === 66,
  'a beat keeps its kind and atFrame (action @ 66)',
);
check(
  adapted.scenes.every((scene) =>
    scene.motion.beats.every((beat) => scene.text.some((element) => element.id === beat.subject) || /^actor:\d+$/.test(beat.subject)),
  ),
  'every beat subject names a real element or actor selector',
);
check(
  adapted.scenes.every((scene) => scene.motion.beats.every((beat) => beat.atFrame < scene.durationInFrames)),
  'no beat sits past its scene duration (it could never be rendered)',
);

// A scene that declares neither still adapts and still renders: absence must not be an error,
// and it must not be silently replaced with a plausible default either.
const bare = adaptProductStoryboard({
  ...clone(PRODUCT),
  scenes: [{...clone(PRODUCT.scenes[0]), camera: undefined, motion: undefined}],
});
check(bare.scenes[0].camera === undefined, 'an undeclared camera stays absent (no invented default)');
check(bare.scenes[0].motion === undefined, 'undeclared motion stays absent (no invented default)');
try {
  validateSceneData(bare.scenes[0]);
  pass('a scene with no camera and no motion still validates');
} catch (err) {
  failures += 1;
  console.log(`FAIL camera-less scene rejected: ${err instanceof Error ? err.message : err}`);
}

// Fail-loud cases: the adapter re-checks what the Python contract enforces, because a hand-written
// props file never went through Pydantic.
checkThrowsNaming(
  'non-static camera with no target',
  () => adaptProductStoryboard({...clone(PRODUCT), scenes: [{...clone(PRODUCT.scenes[0]), camera: {shot: 'wide', move: 'push', amplitude: 0.1, ease: 'power2.out'}}]}),
  'camera.target',
);
checkThrowsNaming(
  'camera target naming no element',
  () => adaptProductStoryboard({...clone(PRODUCT), scenes: [{...clone(PRODUCT.scenes[0]), camera: {shot: 'wide', move: 'push', target: 'nope', amplitude: 0.1, ease: 'power2.out'}}]}),
  'camera.target',
);
checkThrowsNaming(
  'camera with an unknown move',
  () => adaptProductStoryboard({...clone(PRODUCT), scenes: [{...clone(PRODUCT.scenes[0]), camera: {shot: 'wide', move: 'dolly', target: 't1', amplitude: 0.1, ease: 'power2.out'}}]}),
  'camera.move',
);
checkThrowsNaming(
  'camera amplitude out of range',
  () => adaptProductStoryboard({...clone(PRODUCT), scenes: [{...clone(PRODUCT.scenes[0]), camera: {shot: 'wide', move: 'push', target: 't1', amplitude: 4, ease: 'power2.out'}}]}),
  'camera.amplitude',
);
checkThrowsNaming(
  'static camera with a zoom-sized amplitude',
  () => adaptProductStoryboard({...clone(PRODUCT), scenes: [{...clone(PRODUCT.scenes[0]), camera: {shot: 'wide', move: 'static', amplitude: 0.8, ease: 'power2.out'}}]}),
  'camera.amplitude',
);
checkThrowsNaming(
  'beat with an unknown kind',
  () => adaptProductStoryboard({...clone(PRODUCT), scenes: [{...clone(PRODUCT.scenes[0]), motion: {energy: 0.5, continuity: 'cut', beats: [{atFrame: 0, kind: 'wiggle', subject: 't1'}]}}]}),
  'motion.beats[0]',
);
checkThrowsNaming(
  'motion energy out of range',
  () => adaptProductStoryboard({...clone(PRODUCT), scenes: [{...clone(PRODUCT.scenes[0]), motion: {energy: 3, continuity: 'cut', beats: []}}]}),
  'motion.energy',
);

// Rule 7: only content-addressed refs survive; a dropped ref is not an invented one.
check(
  adapted.scenes[0].assetRefs.length === 0 && adapted.scenes[1].assetRefs.length === 0,
  "assetRefs ['character:maya','bg:desert-dusk'] and ['character:maya'] are dropped to []",
);
const keepable = 'assets/' + 'a'.repeat(64) + '.png';
const kept = adaptProductStoryboard({
  ...clone(PRODUCT),
  scenes: [{...clone(PRODUCT.scenes[0]), assetRefs: ['character:maya', keepable]}],
});
check(
  kept.scenes[0].assetRefs.length === 1 && kept.scenes[0].assetRefs[0] === keepable,
  'a content-addressed ref is kept while the character ref is dropped',
);

// Rule 8 + the fixture assertion: every adapted scene passes the donor validator.
for (const scene of adapted.scenes) {
  try {
    validateSceneData(scene);
    pass(`validateSceneData accepts ${scene.sceneId}`);
  } catch (err) {
    failures += 1;
    console.log(`FAIL validateSceneData rejects ${scene.sceneId}: ${err instanceof Error ? err.message : err}`);
  }
}

// A scene with no image and no data requirement must still validate (none of today's templates
// require an image), so dropping every assetRef is not fatal.
const noRefs = adaptProductStoryboard({
  ...clone(PRODUCT),
  scenes: [{...clone(PRODUCT.scenes[0]), assetRefs: []}],
});
try {
  validateSceneData(noRefs.scenes[0]);
  pass('a scene with zero assetRefs still validates (no template requires an image)');
} catch (err) {
  failures += 1;
  console.log(`FAIL zero-ref scene rejected: ${err instanceof Error ? err.message : err}`);
}

// Rule 8: data passes through untouched, and a template that needs it rejects its absence.
check(
  JSON.stringify(adapted.scenes[0].data) === JSON.stringify(PRODUCT.scenes[0].data),
  'data passes through unchanged',
);
const missingData = adaptProductStoryboard({
  ...clone(PRODUCT),
  scenes: [{...clone(PRODUCT.scenes[0]), data: null}],
});
checkThrowsNaming(
  'IllustratedStory with no data',
  () => validateSceneData(missingData.scenes[0]),
  'data',
);

// Fail-loud cases.
const missingScenes = clone(PRODUCT);
delete missingScenes.scenes;
checkThrowsNaming('storyboard missing scenes', () => adaptProductStoryboard(missingScenes), 'scenes');

const missingDuration = clone(PRODUCT);
delete missingDuration.scenes[0].durationInFrames;
checkThrowsNaming(
  'scene missing durationInFrames',
  () => adaptProductStoryboard(missingDuration),
  'durationInFrames',
);

const badFps = clone(PRODUCT);
badFps.fps = '30';
checkThrowsNaming('non-numeric fps', () => adaptProductStoryboard(badFps), 'fps');

const unknownTemplate = clone(PRODUCT);
unknownTemplate.scenes[0].template = 'NotATemplate';
checkThrowsNaming(
  'scene with unknown template',
  () => adaptProductStoryboard(unknownTemplate),
  'template',
);

// The error must name the scene, not just the field.
try {
  adaptProductStoryboard(missingDuration);
  failures += 1;
  console.log('FAIL scene error does not name the scene id');
} catch (err) {
  const message = err instanceof Error ? err.message : String(err);
  if (message.includes('sc1')) {
    pass(`scene error names the scene id: ${message}`);
  } else {
    failures += 1;
    console.log(`FAIL scene error does not name the scene id: ${message}`);
  }
}

check(isProductStoryboard(null) === false, 'isProductStoryboard rejects null');
check(isProductStoryboard({}) === false, 'isProductStoryboard rejects an empty object');
check(isProductStoryboard({...clone(PRODUCT), scenes: []}) === false, 'isProductStoryboard rejects empty scenes');
check(
  isProductStoryboard(readJson('../fixtures/all-templates.json')) === false,
  'isProductStoryboard rejects the donor fixture (donor behaviour is preserved)',
);
check(TEMPLATE_IDS.includes('IllustratedStory'), 'TEMPLATE_IDS still exports IllustratedStory');

console.log(`\n${failures === 0 ? 'PASS' : 'FAIL'} adapter test: ${failures} failure(s)`);
process.exit(failures === 0 ? 0 : 1);
