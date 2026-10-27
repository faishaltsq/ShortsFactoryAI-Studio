import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import ts from 'typescript';
import vm from 'node:vm';
// `scene-data.ts` imports the character id vocabulary, so this loader resolves local
// modules instead of assuming a single file. Keeping the suite dependency-free (no
// test runner, no bundler) is the convention in this package.
const base = new URL('../src/', import.meta.url);
const cache = new Map();
const load = (specifier) => {
  const rel = specifier.replace(/^\.\//, '');
  if (cache.has(rel)) return cache.get(rel);
  const source = readFileSync(new URL(`${rel}.ts`, base), 'utf8');
  const compiled = ts.transpileModule(source, {
    compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022},
  }).outputText;
  const module = {exports: {}};
  vm.runInNewContext(compiled, {module, exports: module.exports, require: load, console, Math, Number, Object, Array, String, JSON});
  cache.set(rel, module.exports);
  return module.exports;
};
const {validateSceneData, localImage} = load('scene-data');
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
console.log('PASS template contracts: six valid fixtures, incomplete/unknown/remote/nonfinite rejected');
