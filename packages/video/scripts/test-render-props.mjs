/**
 * Regression test for the render-props bug.
 *
 * Remotion merges composition props as `{...defaultProps, ...editorProps, ...inputProps}`, so a
 * `--props` file silently overrode the adapted `defaultProps` and a raw product storyboard reached
 * `Short`. Adapting in `RemotionRoot` alone therefore fixed Studio preview but not rendering.
 *
 * This asserts the metadata functions' return values directly rather than driving Remotion's
 * resolver: `ResolveCompositionConfig` reads `window.remotion_inputProps` and needs a browser, so a
 * cheap end-to-end assertion is not available. The contract being checked is the one that broke —
 * that the `props` returned by the metadata functions are the ADAPTED ones.
 */

import {register} from 'node:module';
import {readFileSync} from 'node:fs';

register('./ts-resolve-hook.mjs', import.meta.url);

const {calculateShortMetadata, calculateSceneMetadata, resolveStoryboard, isDonorStoryboard} =
  await import('../src/storyboard-props.ts');
const {validateSceneData} = await import('../src/scene-data.ts');

const PRODUCT = JSON.parse(readFileSync(new URL('../fixtures/product-storyboard.json', import.meta.url), 'utf8'));
const DONOR = JSON.parse(readFileSync(new URL('../fixtures/all-templates.json', import.meta.url), 'utf8'));

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

const clone = (value) => JSON.parse(JSON.stringify(value));
const tick = async (value) => value;

console.log('# render-props regression');

// --- Short: the exact case that broke -------------------------------------------------------
const shortMeta = await tick(calculateShortMetadata({props: {storyboard: PRODUCT}, defaultProps: {}, compositionId: 'Short', isRendering: true}));
const effective = shortMeta.props.storyboard;

check(effective !== PRODUCT, 'Short metadata returns a NEW storyboard object, not the raw input');
check(
  typeof effective.theme === 'object' && effective.theme !== null,
  `Short metadata theme is a resolved object (${effective.theme.id}), not the raw string`,
);
check(
  effective.scenes.every((scene) => Array.isArray(scene.assetRefs) && scene.assetRefs.length === 0),
  'Short metadata drops the non-content-addressed assetRefs',
);
check(
  effective.scenes.every((scene) => scene.text.every((t) => t.style && typeof t.style.role === 'string')),
  'Short metadata gives every text element a style.role',
);
check(
  effective.scenes.every((scene) => scene.transition && typeof scene.transition.type === 'string'),
  'Short metadata maps transitions to the donor vocabulary',
);
check(
  effective.scenes.every((scene) => scene.animation && scene.animation.preset === 'fadeIn'),
  'Short metadata supplies the required animation',
);

// The regression itself: metadata must be self-consistent with what a composition validates.
let validated = 0;
for (const scene of effective.scenes) {
  try {
    validateSceneData(scene);
    validated += 1;
  } catch (err) {
    failures += 1;
    console.log(`FAIL adapted scene ${scene.sceneId} fails validateSceneData: ${err.message}`);
  }
}
check(validated === effective.scenes.length, `all ${validated} adapted scenes pass validateSceneData`);

check(
  shortMeta.durationInFrames === 900 && shortMeta.fps === 30 && shortMeta.width === 1080 && shortMeta.height === 1920,
  `Short metadata reports 900 frames / 30fps / 1080x1920 (got ${shortMeta.durationInFrames}/${shortMeta.fps}/${shortMeta.width}x${shortMeta.height})`,
);

// The metadata path must carry the declared camera and motion, not just the adapter in isolation:
// `calculateShortMetadata` is what a real `--props` render goes through.
check(
  effective.scenes.every((scene) => scene.camera && typeof scene.camera.move === 'string'),
  `Short metadata props carry camera: ${effective.scenes.map((s) => s.camera?.move).join(',')}`,
);
check(
  effective.scenes.every((scene) => scene.motion && Array.isArray(scene.motion.beats)),
  `Short metadata props carry motion.beats: ${effective.scenes.map((s) => s.motion?.beats.length).join(',')}`,
);
check(
  effective.scenes[0].camera.target === PRODUCT.scenes[0].text[0].id,
  'the camera target survives into the rendered props and names a real element',
);

// A donor storyboard must pass through untouched — the fix must not break existing renders.
const donorMeta = await tick(calculateShortMetadata({props: {storyboard: DONOR}, defaultProps: {}, compositionId: 'Short', isRendering: true}));
check(donorMeta.props.storyboard === DONOR, 'a donor storyboard passes through by identity (no re-adaptation)');

// --- Per-template compositions --------------------------------------------------------------
const sceneMeta = await tick(
  calculateSceneMetadata({
    props: {scene: DONOR.scenes.find((s) => s.template === 'IllustratedStory'), theme: {}, storyboard: PRODUCT},
    defaultProps: {},
    compositionId: 'IllustratedStory',
    isRendering: true,
  }),
);
check(
  sceneMeta.props.scene.sceneId === 'sc1',
  `IllustratedStory metadata picks the adapted scene from the carried storyboard (${sceneMeta.props.scene.sceneId})`,
);
check(
  sceneMeta.props.scene.text.every((t) => t.style && typeof t.style.role === 'string'),
  'IllustratedStory metadata hands the composition an adapted scene',
);
check(
  sceneMeta.durationInFrames === sceneMeta.props.scene.durationInFrames,
  'scene metadata duration follows the adapted scene',
);

// Without a carried storyboard the already-adapted default scene is kept.
const donorScene = DONOR.scenes.find((s) => s.template === 'IllustratedStory');
const plainSceneMeta = await tick(
  calculateSceneMetadata({props: {scene: donorScene, theme: {}}, defaultProps: {}, compositionId: 'IllustratedStory', isRendering: true}),
);
check(plainSceneMeta.props.scene === donorScene, 'no storyboard prop -> the default scene is preserved by identity');

// --- Fail loud ------------------------------------------------------------------------------
const throws = (label, fn) => {
  try {
    fn();
  } catch (err) {
    if (err instanceof Error) {
      pass(`${label} -> throws: ${err.message}`);
    } else {
      failures += 1;
      console.log(`FAIL ${label} threw a non-Error`);
    }
    return;
  }
  failures += 1;
  console.log(`FAIL ${label} did not throw`);
};

throws('resolveStoryboard(garbage) throws rather than casting', () => resolveStoryboard({nope: 1}));
throws('resolveStoryboard(null) throws', () => resolveStoryboard(null));
throws('a product storyboard missing scenes throws', () => {
  const broken = clone(PRODUCT);
  delete broken.scenes;
  resolveStoryboard(broken);
});
throws('a donor-shaped storyboard with no text style throws', () => {
  const broken = clone(DONOR);
  broken.scenes[0].text = [{id: 'x', text: 'y'}];
  resolveStoryboard(broken);
});
throws('Short metadata throws on a malformed storyboard', () =>
  calculateShortMetadata({props: {storyboard: {bad: true}}, defaultProps: {}, compositionId: 'Short', isRendering: true}),
);

check(isDonorStoryboard(DONOR) === true, 'isDonorStoryboard accepts the donor fixture');
check(isDonorStoryboard(PRODUCT) === false, 'isDonorStoryboard rejects the product shape');

console.log(`\n${failures === 0 ? 'PASS' : 'FAIL'} render-props regression: ${failures} failure(s)`);
process.exit(failures === 0 ? 0 : 1);
