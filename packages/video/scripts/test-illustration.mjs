import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {readFileSync, writeFileSync, mkdirSync} from 'node:fs';
import {createRequire} from 'node:module';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import ts from 'typescript';
import vm from 'node:vm';
import {freeRemotionPort} from './free-port.mjs';

const videoDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const outDir = process.argv[2];
if (!outDir || !path.isAbsolute(outDir)) throw new Error('Pass an absolute output directory');
mkdirSync(outDir, {recursive: true});

const compile = (rel) => {
  const source = readFileSync(path.join(videoDir, rel), 'utf8');
  const js = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022}}).outputText;
  const mod = {exports: {}};
  vm.runInNewContext(js, {module: mod, exports: mod.exports, require: createRequire(import.meta.url)});
  return mod.exports;
};
const {shotAt} = compile('src/art/shots.ts');

const fixture = JSON.parse(readFileSync(path.join(videoDir, 'fixtures/all-templates.json'), 'utf8'));
const scene = fixture.scenes.find((s) => s.template === 'IllustratedStory');
assert.ok(scene, 'fixture is missing the IllustratedStory scene');

const cli = path.join(videoDir, 'node_modules/@remotion/cli/remotion-cli.js');
const port = await freeRemotionPort();
const still = (name, frame, props) => {
  const propsPath = path.join(outDir, `${name}-props.json`);
  const png = path.join(outDir, `${name}.png`);
  writeFileSync(propsPath, JSON.stringify(props));
  const r = spawnSync(process.execPath, [cli, 'still', 'src/index.ts', 'IllustratedStory', png,
    `--props=${propsPath}`, `--frame=${frame}`, '--overwrite', '--log=error', `--port=${port}`],
    {cwd: videoDir, encoding: 'utf8', timeout: 180000});
  if (r.status !== 0) throw new Error(`${name}@${frame}: ${r.stderr} ${r.stdout}`);
  return png;
};

const stats = (args) => {
  const r = spawnSync('ffmpeg', ['-hide_banner', '-nostats', ...args, '-frames:v', '1', '-f', 'null', '-'],
    {encoding: 'utf8', timeout: 60000});
  if (r.status !== 0) throw new Error(`ffmpeg failed: ${r.stderr}`);
  return Object.fromEntries([...r.stderr.matchAll(/lavfi\.signalstats\.(YMIN|YMAX|YAVG)=([0-9.]+)/g)]
    .map((m) => [m[1], Number(m[2])]));
};
const spread = (png) => stats(['-i', png, '-vf', 'signalstats,metadata=print']);
const diffMean = (a, b) => stats(['-i', a, '-i', b, '-filter_complex', '[0:v][1:v]blend=all_mode=difference,signalstats,metadata=print']).YAVG;

// 1. Art must exist without any typography at all.
const artOnly = {scene: {...scene, text: [], data: {...scene.data, title: undefined, caption: undefined}},
                 theme: fixture.theme, watermark: fixture.watermark.text};
const artA = still('art-0', 0, artOnly);
const artB = still('art-60', 60, artOnly);
const artSpread = spread(artB);
// Measured baseline on this machine: spread 183, motion 11.73, cut 17.20, drift 0.07.
// Thresholds sit near half the baseline so a real regression trips them, not noise.
assert.ok(artSpread.YMAX - artSpread.YMIN >= 80, `illustration is nearly flat (spread ${artSpread.YMAX - artSpread.YMIN})`);

// 2. It must actually animate between two frames.
const motion = diffMean(artA, artB);
assert.ok(motion >= 4, `illustration does not animate (mean frame difference ${motion})`);

// 3. A shot boundary must read as a cut, not a drift.
const full = {scene, theme: fixture.theme, watermark: fixture.watermark.text};
const span = shotAt(scene.data.shots, 0, scene.durationInFrames);
const boundary = span.duration;
const beforeCut = still('cut-before', boundary - 1, full);
const afterCut = still('cut-after', boundary, full);
const midA = still('mid-a', boundary + 20, full);
const midB = still('mid-b', boundary + 21, full);
const cutDelta = diffMean(beforeCut, afterCut);
const driftDelta = diffMean(midA, midB);
assert.ok(cutDelta >= driftDelta * 10 && cutDelta >= 5, `shot boundary is not a cut (cut ${cutDelta} vs drift ${driftDelta})`);

console.log(`PASS illustration: spread ${(artSpread.YMAX - artSpread.YMIN).toFixed(1)}, motion ${motion.toFixed(2)}, cut ${cutDelta.toFixed(2)} vs drift ${driftDelta.toFixed(2)}`);
