/**
 * Writes a Remotion `--props` file containing the ADAPTED product storyboard, so the still render
 * is driven by the adapter's real output rather than a hand-copied expectation.
 *
 * Usage: node scripts/emit-adapter-props.mjs <out.json>
 */

import {register} from 'node:module';
import {readFileSync, writeFileSync} from 'node:fs';
import {resolve} from 'node:path';

register('./ts-resolve-hook.mjs', import.meta.url);

const {adaptProductStoryboard} = await import('../src/product-adapter.ts');

const out = process.argv[2];
if (!out) {
  console.error('usage: node scripts/emit-adapter-props.mjs <out.json>');
  process.exit(2);
}

const product = JSON.parse(readFileSync(new URL('../fixtures/product-storyboard.json', import.meta.url), 'utf8'));
const storyboard = adaptProductStoryboard(product);

// Remotion receives the product shape and adapts it again through Root.tsx, so this file proves
// the wiring end to end: `{storyboard: <product shape>}` in, adapted StoryboardSpec out.
const payload = {storyboard: product};
writeFileSync(resolve(out), JSON.stringify(payload, null, 2));
console.log(`wrote ${resolve(out)} (${JSON.stringify(payload).length} bytes)`);
console.log(`adapter preview: id=${storyboard.id} scenes=${storyboard.scenes.length} subtitles=${storyboard.subtitles.length}`);
console.log(`first scene: template=${storyboard.scenes[0].template} transition=${storyboard.scenes[0].transition.type} assetRefs=${JSON.stringify(storyboard.scenes[0].assetRefs)}`);
