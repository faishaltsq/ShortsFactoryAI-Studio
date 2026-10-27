#!/usr/bin/env node
/**
 * Export the character registry to `config/characters.json`.
 *
 * The Python normaliser and the storyboard prompt both need the set of character ids
 * that actually exist. Importing TypeScript from Python is not an option, so the
 * registry is projected into a small JSON index — the same pattern as
 * `scripts/export_schemas.py` for the artifact contracts.
 *
 *   node scripts/export-character-index.mjs          write the file
 *   node scripts/export-character-index.mjs --check  fail if it is stale
 *
 * The index is derived, never hand-edited: `--check` runs in the test suite.
 */
import {readFileSync, writeFileSync, existsSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
import ts from 'typescript';
import vm from 'node:vm';

const videoDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const rootDir = path.resolve(videoDir, '..', '..');
const target = path.join(rootDir, 'config', 'characters.json');

/** Compile one TS module to CommonJS and evaluate it with a stubbed import. */
const loadModule = (relPath, stubs = {}) => {
  const source = readFileSync(path.join(videoDir, relPath), 'utf8');
  const js = ts.transpileModule(source, {
    compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX},
  }).outputText;
  const mod = {exports: {}};
  const req = createRequire(import.meta.url);
  const localRequire = (specifier) => {
    if (specifier in stubs) return stubs[specifier];
    throw new Error(`unexpected import ${specifier} while reading ${relPath}`);
  };
  vm.runInNewContext(js, {module: mod, exports: mod.exports, require: localRequire, console, Number, Math, Object, Array, String, JSON});
  return mod.exports;
};

// Load the manifest chain with minimal stubs. The registry pulls in React components,
// which are irrelevant to the index; only the data modules are needed.
const ids = loadModule('src/character/ids.ts');
const validate = loadModule('src/character/validate.ts', {
  './ids': ids,
});
const maya = loadModule('src/character/assets/maya/manifest.ts', {
  './art': loadModule('src/character/assets/maya/art.ts', {'../../ids': ids}),
});

const manifest = maya.MAYA;
validate.validateCharacter(manifest);

const index = {
  version: 1,
  generatedFrom: 'packages/video/src/character/assets',
  characters: [
    {
      id: manifest.id,
      version: manifest.version,
      displayName: manifest.displayName,
      artStyle: manifest.artStyle,
      poses: manifest.poses,
      expressions: manifest.expressions,
      gestures: manifest.gestures,
      license: manifest.license.id,
      provenance: manifest.provenance.source,
    },
  ],
};

const text = JSON.stringify(index, null, 2) + '\n';

if (process.argv.includes('--check')) {
  if (!existsSync(target)) {
    console.error(`missing ${path.relative(rootDir, target)}; run scripts/export-character-index.mjs`);
    process.exit(1);
  }
  if (readFileSync(target, 'utf8') !== text) {
    console.error(`${path.relative(rootDir, target)} is stale; run scripts/export-character-index.mjs`);
    process.exit(1);
  }
  console.log(`character index verified (${index.characters.length} character)`);
} else {
  writeFileSync(target, text);
  console.log(`wrote ${path.relative(rootDir, target)} (${index.characters.length} character)`);
}
