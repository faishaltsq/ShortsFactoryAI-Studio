import {spawnSync} from 'node:child_process';
import {readFileSync, writeFileSync, mkdirSync} from 'node:fs';
import {createHash} from 'node:crypto';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {freeRemotionPort} from './free-port.mjs';

const videoDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const outputDir = process.argv[2];
if (!outputDir || !path.isAbsolute(outputDir)) throw new Error('Pass an absolute output directory under Hermes scratch or a job root');
mkdirSync(outputDir, {recursive: true});
const storyboard = JSON.parse(readFileSync(path.join(videoDir, 'fixtures/all-templates.json'), 'utf8'));
const cli = path.join(videoDir, 'node_modules/@remotion/cli/remotion-cli.js');
const port = await freeRemotionPort();
const results = [];
for (const scene of storyboard.scenes) {
  const props = path.join(outputDir, `${scene.template}-props.json`);
  const png = path.join(outputDir, `${scene.template}.png`);
  writeFileSync(props, JSON.stringify({scene, theme: storyboard.theme, watermark: storyboard.watermark.text}));
  const result = spawnSync(process.execPath, [cli, 'still', 'src/index.ts', scene.template, png,
    `--props=${props}`, '--frame=100', '--overwrite', '--log=error', `--port=${port}`], {cwd: videoDir, encoding: 'utf8', timeout: 120000});
  if (result.status !== 0) throw new Error(`${scene.template}: ${result.stderr} ${result.stdout} ${result.error ?? ''}`);
  const bytes = readFileSync(png);
  if (bytes.toString('hex', 0, 8) !== '89504e470d0a1a0a' || bytes.readUInt32BE(16) !== 1080 || bytes.readUInt32BE(20) !== 1920) throw new Error('Invalid still dimensions');
  const check = spawnSync('ffmpeg', ['-hide_banner', '-nostats', '-i', png, '-vf',
    'crop=936:1340:72:260,signalstats,metadata=print', '-frames:v', '1', '-f', 'null', '-'], {encoding: 'utf8', timeout: 30000});
  const stats = Object.fromEntries([...check.stderr.matchAll(/lavfi.signalstats.(YMIN|YMAX)=([0-9.]+)/g)].map(m => [m[1], Number(m[2])]));
  if (check.status !== 0 || !Number.isFinite(stats.YMIN) || stats.YMAX - stats.YMIN < 20) throw new Error(`${scene.template}: narrative safe area is blank`);
  results.push({template: scene.template, width: 1080, height: 1920, path: png, sha256: createHash('sha256').update(bytes).digest('hex')});
  writeFileSync(path.join(outputDir, 'stills.json'), JSON.stringify(results, null, 2));
  console.log(`PASS ${scene.template} 1080x1920`);
}
if (results.length !== 7 || new Set(results.map(r => r.template)).size !== 7) throw new Error('Expected all seven templates');
console.log('7/7 real Remotion stills verified');
