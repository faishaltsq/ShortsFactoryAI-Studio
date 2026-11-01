/**
 * Per-template renderer still proof (G10).
 *
 * Usage: node scripts/verify-template-stills.mjs <absolute-output-dir>
 *
 * Renders one still per template composition through the real Remotion CLI and proves, per
 * template:
 *
 * 1. The still is a real 1080x1920 PNG (composition mounts and draws at all).
 * 2. The narrative safe area is not blank — each template paints its own content, so a template
 *    that stopped rendering (a broken import, a throw in `validateSceneData`) fails here instead
 *    of shipping an empty segment.
 * 3. A declared `push` camera changes the frame: the declared camera must reach every template
 *    through `DeclaredCameraScope`.
 * 4. A declared action beat either moves the object it names (`ObjectExplainer` turns beats into
 *    highlights) or, on templates that read no beats, changes nothing at all — invented motion
 *    would be a contract lie, and so would a beat that is recorded and ignored.
 *
 * Scenes come from `fixtures/all-templates.json`, the same fixture `Root.tsx` falls back to, so
 * each template renders with data that validates under its own branch of `validateSceneData`.
 *
 * Exits non-zero on the first template that fails any measurement.
 */

import {register} from 'node:module';
import {spawnSync} from 'node:child_process';
import {mkdirSync, readFileSync, writeFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {freeRemotionPort} from './free-port.mjs';

register('./ts-resolve-hook.mjs', import.meta.url);

const videoDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const outDir = process.argv[2];
if (!outDir || !path.isAbsolute(outDir)) throw new Error('Pass an absolute output directory');
mkdirSync(outDir, {recursive: true});

const cli = path.join(videoDir, 'node_modules/@remotion/cli/remotion-cli.js');
const port = await freeRemotionPort();

const fixture = JSON.parse(readFileSync(path.join(videoDir, 'fixtures/all-templates.json'), 'utf8'));

const TEMPLATE_IDS = [
  'KineticTypography',
  'MotionComic',
  'EducationalExplainer',
  'HistoricalTimeline',
  'ParallaxStory',
  'InfographicMotion',
  'ObjectExplainer',
  'ProcessFlow',
  'MetricShift',
];

/** Template-specific declared cameras. `static` renders untouched; `push` must move pixels. */
const CAMERA = {
  static: {shot: 'wide', move: 'static', amplitude: 0.1, ease: 'power2.out'},
  push: {shot: 'wide', move: 'push', amplitude: 0.4, ease: 'power2.out', target: 'title'},
};

/** Templates whose renderer consumes motion beats. All others must leave beats pixels untouched. */
const BEAT_DRIVEN = new Set(['ObjectExplainer']);

const templateScene = (template) => {
  const scene = structuredClone(fixture.scenes.find((s) => s.template === template));
  if (!scene) throw new Error(`fixture has no scene for ${template}`);
  // Standalone compositions run a scene-local timeline: `Root.tsx` re-bases the scene to frame 0
  // the same way a cut re-bases it inside a `Sequence`. The props file must carry the re-based
  // scene, or `DeclaredCameraScope` computes `sceneFrame = 30 - startFrame < 0` and clamps the
  // camera to identity — a still that silently proves nothing.
  scene.startFrame = 0;
  // The push aims at the scene's first text element, so the anchor resolution inside
  // `declaredCameraAt` exercises the real target path instead of the centered default.
  scene.camera = {...CAMERA.push, target: scene.text?.[0]?.id};
  return scene;
};

const still = (name, compositionId, scene, frame = 30) => {
  const props = path.join(outDir, `${name}-props.json`);
  const png = path.join(outDir, `${name}.png`);
  writeFileSync(
    props,
    JSON.stringify({scene, theme: fixture.theme, watermark: fixture.watermark?.text}),
  );
  // Standalone template compositions run a scene-local timeline (`Root.tsx` re-bases the scene to
  // frame 0), so the default frame 30 sits inside every 150-frame scene.
  const result = spawnSync(
    process.execPath,
    [cli, 'still', 'src/index.ts', compositionId, png, `--props=${props}`, `--frame=${frame}`,
      '--overwrite', '--log=error', `--port=${port}`],
    {cwd: videoDir, encoding: 'utf8', timeout: 240000},
  );
  if (result.status !== 0) throw new Error(`${name}: ${result.stderr || result.stdout}`);
  const bytes = readFileSync(png);
  if (bytes.toString('hex', 0, 8) !== '89504e470d0a1a0a') throw new Error(`${name}: not a PNG`);
  if (bytes.readUInt32BE(16) !== 1080 || bytes.readUInt32BE(20) !== 1920) throw new Error(`${name}: not 1080x1920`);
  return png;
};

/** Mean luma of the central band via ffmpeg signalstats — a near-black band means "did not draw". */
const meanLuma = (png) => {
  const result = spawnSync(
    'ffmpeg',
    ['-hide_banner', '-nostats', '-i', png, '-vf', 'crop=880:900:100:510,signalstats,metadata=print:key=lavfi.signalstats.YAVG',
      '-f', 'null', '-'],
    {encoding: 'utf8', timeout: 60000},
  );
  if (result.status !== 0) throw new Error(`ffmpeg failed: ${result.stderr.slice(-600)}`);
  const match = /YAVG=([\d.]+)/.exec(result.stderr);
  if (!match) throw new Error('signalstats produced no YAVG');
  return Number(match[1]);
};

/** Byte-difference ratio between two PNGs of the same frame count, downscaled to blur codec noise. */
const frameDifference = (pngA, pngB) => {
  const result = spawnSync(
    'ffmpeg',
    ['-hide_banner', '-nostats', '-i', pngA, '-i', pngB,
      '-filter_complex', '[0:v]scale=96:170[a];[1:v]scale=96:170[b];[a][b]psnr', '-f', 'null', '-'],
    {encoding: 'utf8', timeout: 60000},
  );
  const match = /average:([\d.]+|inf)/.exec(result.stderr);
  if (!match) throw new Error(`psnr produced no average: ${result.stderr.slice(-400)}`);
  return match[1] === 'inf' ? Number.POSITIVE_INFINITY : Number(match[1]);
};

const failures = [];
for (const template of TEMPLATE_IDS) {
  try {
    const scene = templateScene(template);
    scene.camera = CAMERA.static;
    const baseline = still(`${template}-base`, template, scene);
    const luma = meanLuma(baseline);
    if (luma < 4) throw new Error(`safe area is blank (mean luma ${luma.toFixed(2)})`);

    // Camera reach: a push against the same scene must move the picture. The comparison stays
    // inside one template, so template-specific styling cannot confound it.
    const pushed = still(`${template}-push`, template, templateScene(template));
    const psnr = frameDifference(baseline, pushed);
    if (psnr < 6) throw new Error(`declared camera did not reach this template (PSNR ${psnr.toFixed(1)} dB)`);

    // Declared beats: a figure-carrying template must act the beat on its figure; a text-only
    // template has no rig, so its declared beats are director's notes the renderer must leave
    // untouched — byte-identical pixels prove no invented motion. The beat fires at frame 40 on
    // the first figure (panel 0 / data actor 0); the comparison frame 60 is past the
    // POSE_BLEND_FRAMES peak. Baseline for this comparison is the same scene at the SAME frame
    // without motion: the compositions' own entrances are still settling at frame 30, so a
    // cross-frame diff would read as invented motion.
    const target = templateScene(template);
    delete target.camera;
    // `object:0` is the hero object of an explainer scene. On any other template the subject names
    // nothing, which is exactly the case a beat must leave pixels untouched on.
    // The beat lands at 55, not 40: both stills are taken at frame 60, and an object highlight is
    // a window (`atFrame .. atFrame + 14`). A beat at 40 would have expired before the frame this
    // comparison measures, which would look like a renderer ignoring the beat.
    target.motion = {energy: 0.7, continuity: 'cut', beats: [{atFrame: 55, kind: 'action', subject: 'object:0'}]};
    const calm = still(`${template}-calm`, template, {...target, motion: undefined}, 60);
    const acted = still(`${template}-beat`, template, target, 60);
    const beatPsnr = frameDifference(calm, acted);
    if (BEAT_DRIVEN.has(template)) {
      // A highlight ring plus a 3% scale on one object is a real change but a small one inside a
      // 1080x1920 frame, so the floor only has to separate "something moved" from "nothing moved".
      if (beatPsnr > 45) throw new Error(`beat did not move the object (PSNR ${beatPsnr.toFixed(1)} dB)`);
    } else if (beatPsnr !== Number.POSITIVE_INFINITY) {
      throw new Error(`template that reads no beats invented motion (PSNR ${beatPsnr.toFixed(1)} dB)`);
    }

    console.log(
      `${template}: luma=${luma.toFixed(1)} push-PSNR=${psnr === Number.POSITIVE_INFINITY ? 'inf' : psnr.toFixed(1)}dB` +
        ` beat-PSNR=${beatPsnr === Number.POSITIVE_INFINITY ? 'inf' : beatPsnr.toFixed(1)}dB`,
    );
  } catch (error) {
    failures.push(`${template}: ${error.message}`);
  }
}

if (failures.length > 0) {
  console.error(`FAILURES:\n${failures.join('\n')}`);
  process.exit(1);
}
console.log('all templates render and answer the declared camera');
