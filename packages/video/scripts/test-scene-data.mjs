import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import ts from 'typescript';
import vm from 'node:vm';
// `scene-data.ts` imports the object vocabulary, so this loader resolves local
// modules instead of assuming a single file. Keeping the suite dependency-free (no
// test runner, no bundler) is the convention in this package.
const srcDir = fileURLToPath(new URL('../src/', import.meta.url));
const cache = new Map();
/** Resolve a specifier against the importing module's directory (relative to src/). */
const toRel = (fromRel, specifier) => {
  const abs = path.resolve(path.dirname(path.join(srcDir, fromRel)), specifier);
  const rel = path.relative(srcDir, abs).split(path.sep).join('/');
  return rel.startsWith('.') ? rel : `./${rel}`;
};
const load = (rel0) => {
  const rel = rel0.replace(/^\.\//, '').replace(/\.ts$/, '');
  if (cache.has(rel)) return cache.get(rel);
  const source = readFileSync(path.join(srcDir, `${rel}.ts`), 'utf8');
  const compiled = ts.transpileModule(source, {
    compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022},
  }).outputText;
  const module = {exports: {}};
  // Each module gets a require that resolves against its own directory, so nested
  // `../themes/...` imports resolve the same way tsc resolves them.
  const require = (specifier) => load(toRel(rel, specifier));
  vm.runInNewContext(compiled, {module, exports: module.exports, require, console, Math, Number, Object, Array, String, JSON});
  cache.set(rel, module.exports);
  return module.exports;
};
const {validateSceneData, validateExplainerData, localImage} = load('scene-data');
const fixture = JSON.parse(readFileSync(new URL('../fixtures/all-templates.json', import.meta.url), 'utf8'));
for (const scene of fixture.scenes) {
  assert.doesNotThrow(() => validateSceneData(scene));
  if (!['KineticTypography', 'EducationalExplainer'].includes(scene.template)) {
    assert.throws(() => validateSceneData({...scene, data: undefined}));
    assert.throws(() => validateSceneData({...scene, data: {...scene.data, arbitrary: 'tsx'}}));
  }
}
for (const src of ['https://example.com/image.png', '../escape.png', '/absolute.png', 'assets/no-hash.png', 'data:image/svg+xml,bad']) {
  assert.throws(() => localImage(src));
}
assert.equal(localImage(`assets/${'a'.repeat(64)}.png`), `assets/${'a'.repeat(64)}.png`);
const graph = fixture.scenes.find(s => s.template === 'InfographicMotion');
assert.throws(() => validateSceneData({...graph, data: {...graph.data, items: [{label: 'bad', value: NaN}]}}));
assert.throws(() => validateSceneData({...graph, data: {...graph.data, maxValue: 1}}));

// Causal state: test camelCase and snake_case in both validateExplainerData and validateSceneData
const explainerBase = {
  environment: 'abstract',
  objects: [{kind: 'satellite', x: 0.5, y: 0.5, size: 0.4}],
  callouts: [],
  flows: [],
};
const camelCausal = {
  initialState: 'Orbiting',
  causalAction: 'Time dilation',
  resultingState: 'Clock drift',
  transition: 'Syncing',
};
const snakeCausal = {
  initial_state: 'Orbiting',
  causal_action: 'Time dilation',
  resulting_state: 'Clock drift',
  transition: 'Syncing',
};
const explainerCamel = validateExplainerData({...explainerBase, causalState: camelCausal});
assert.equal(explainerCamel.causalState?.causalAction, 'Time dilation');
const explainerSnake = validateExplainerData({...explainerBase, causal_state: snakeCausal});
assert.equal(explainerSnake.causalState?.causalAction, 'Time dilation');

const explainerScene = fixture.scenes.find(s => s.template === 'ObjectExplainer');
assert.doesNotThrow(() => validateSceneData({...explainerScene, causalState: camelCausal}));
assert.doesNotThrow(() => validateSceneData({...explainerScene, causal_state: snakeCausal}));
assert.throws(() => validateSceneData({...explainerScene, causal_state: {...snakeCausal, unknownKey: 'nope'}}));
assert.throws(() => validateSceneData({...explainerScene, causal_state: {...snakeCausal, causal_action: ''}}));
assert.throws(() => validateSceneData({...explainerScene, causal_state: {initial_state: 'only'}}));

console.log('PASS template contracts: six valid fixtures, incomplete/unknown/remote/nonfinite rejected');
