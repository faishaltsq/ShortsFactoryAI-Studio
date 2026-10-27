/**
 * Drive chrome-headless-shell over CDP and pipe frames straight into ffmpeg.
 *
 * This is the secondary renderer's whole process boundary. It exists because ADR-0007 forbids
 * `--disable-web-security` and requires no network at capture time, and because the upstream
 * technique (`scripts/export-frames.mjs`) depends on Puppeteer, which this repository does not
 * have and does not want.
 *
 * No package is imported. Node's global `WebSocket` and `fetch` are the whole client.
 *
 * The isolation is layered so that a bug in one layer does not open the network:
 *
 *   1. `--proxy-server` points at a dead port, so any request that is not the document fails.
 *   2. `--host-resolver-rules` maps every host to 0.0.0.0, so DNS cannot resolve to anything.
 *   3. `Network.setBlockedURLs` refuses http/https/ws/wss before the page is navigated.
 *
 * `--proxy-bypass-list` is deliberately absent: measured, it re-enables loopback and defeats
 * layer 1.
 *
 * Usage is in packages/core/motion/emit.py::build_render_argv. Every path must be absolute.
 */

import {spawn} from 'node:child_process';
import {createHash} from 'node:crypto';
import {existsSync, mkdirSync, readFileSync, renameSync, rmSync, writeFileSync} from 'node:fs';
import {mkdtemp, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';

const EXIT = {
  OK: 0,
  BAD_ARGS: 2,
  NOT_READY: 3,
  CAPTURE_FAILED: 4,
  ENCODE_FAILED: 5,
  TIMEOUT: 6,
};

const USAGE =
  'usage: node bang-render.mjs --props=<abs> --out=<abs> --staging=<abs> --chrome=<abs> ' +
  '[--html=<abs>] [--frames=<n>] [--fps=<n>] [--frame-cap=<n>] [--wall-clock=<s>] ' +
  '[--ffmpeg=<path>] [--json]';

function parseArgs(argv) {
  const parsed = {};
  for (const raw of argv) {
    if (!raw.startsWith('--')) throw new Error(`unexpected argument: ${raw}`);
    const body = raw.slice(2);
    const eq = body.indexOf('=');
    if (eq === -1) {
      parsed[body] = true;
      continue;
    }
    parsed[body.slice(0, eq)] = body.slice(eq + 1);
  }
  return parsed;
}

function requireAbsolute(value, name) {
  if (typeof value !== 'string' || !value) throw new Error(`${name} is required`);
  if (!path.isAbsolute(value)) throw new Error(`${name} must be absolute: ${value}`);
  return value;
}

function positiveInt(value, name, fallback) {
  if (value === undefined) {
    if (fallback === undefined) throw new Error(`${name} is required`);
    return fallback;
  }
  const number = Number(value);
  if (!Number.isInteger(number) || number <= 0) throw new Error(`${name} must be a positive integer`);
  return number;
}

function fail(code, message) {
  process.stderr.write(`${message}\n`);
  process.exit(code);
}

function sha256(buffer) {
  return createHash('sha256').update(buffer).digest('hex');
}

/** Kill the whole tree. Python's timeout kills node; Chrome is a grandchild and would survive. */
function killTree(child) {
  if (!child || child.killed) return;
  try {
    if (process.platform === 'win32') {
      spawn('taskkill', ['/PID', String(child.pid), '/T', '/F'], {stdio: 'ignore'});
    } else {
      child.kill('SIGKILL');
    }
  } catch {
    try {
      child.kill();
    } catch {
      /* already gone */
    }
  }
}

class Cdp {
  constructor(socket) {
    this.socket = socket;
    this.nextId = 1;
    this.pending = new Map();
    this.listeners = [];
    socket.addEventListener('message', (event) => {
      const message = JSON.parse(event.data);
      if (message.id && this.pending.has(message.id)) {
        const {resolve, reject} = this.pending.get(message.id);
        this.pending.delete(message.id);
        if (message.error) reject(new Error(JSON.stringify(message.error)));
        else resolve(message.result);
        return;
      }
      if (message.method) for (const listener of this.listeners) listener(message);
    });
  }

  onMessage(listener) {
    this.listeners.push(listener);
  }

  send(method, params = {}, sessionId) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, {resolve, reject});
      this.socket.send(JSON.stringify({id, method, params, ...(sessionId ? {sessionId} : {})}));
    });
  }

  close() {
    try {
      this.socket.close();
    } catch {
      /* already closed */
    }
  }
}

async function connect(wsUrl) {
  const socket = new WebSocket(wsUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener('open', resolve, {once: true});
    socket.addEventListener('error', () => reject(new Error('CDP socket error')), {once: true});
  });
  return new Cdp(socket);
}

/** Wait for Chrome to print its DevTools endpoint, or read DevToolsActivePort. */
async function endpointFor(child, profileDir) {
  let captured = '';
  const collect = (chunk) => {
    captured += chunk.toString();
  };
  child.stdout.on('data', collect);
  child.stderr.on('data', collect);

  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    const match = captured.match(/ws:\/\/[^\s]+/);
    if (match) return match[0];
    await new Promise((resolve) => setTimeout(resolve, 50));
  }

  const activePort = path.join(profileDir, 'DevToolsActivePort');
  if (existsSync(activePort)) {
    const port = readFileSync(activePort, 'utf8').split('\n')[0].trim();
    const response = await fetch(`http://127.0.0.1:${port}/json/version`);
    const version = await response.json();
    if (version.webSocketDebuggerUrl) return version.webSocketDebuggerUrl;
  }
  throw new Error(`chrome did not expose a DevTools endpoint: ${captured.slice(-600)}`);
}

function launchArgs(profileDir, width, height) {
  return [
    '--remote-debugging-port=0',
    `--user-data-dir=${profileDir}`,
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-extensions',
    '--disable-background-networking',
    '--disable-sync',
    '--metrics-recording-only',
    '--hide-scrollbars',
    '--mute-audio',
    '--disable-gpu',
    '--force-color-profile=srgb',
    // Isolation layer 1 and 2. No --proxy-bypass-list: it re-enables loopback.
    '--proxy-server=http://127.0.0.1:9',
    '--host-resolver-rules=MAP * 0.0.0.0',
    `--window-size=${width},${height}`,
    'about:blank',
  ];
}

async function capture({args, props, document, staging, width, height, fps, frames, wallClockS}) {
  const profileDir = await mkdtemp(path.join(tmpdir(), 'bang-profile-'));
  const child = spawn(args.chrome, launchArgs(profileDir, width, height), {
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  let timedOut = false;
  const watchdog = setTimeout(() => {
    timedOut = true;
    killTree(child);
  }, wallClockS * 1000);

  // `.partial.mp4`, not `.partial`: ffmpeg picks its muxer from the extension.
  const partial = `${args.out}.partial.mp4`;
  rmSync(partial, {force: true});
  const ffmpegArgs = [
    '-y',
    '-f', 'image2pipe',
    '-vcodec', 'mjpeg',
    '-framerate', String(fps),
    '-i', '-',
    // captureScreenshot emits full-range JPEG; without this the file is yuvj420p and the media
    // gate rejects it. The filter plus -color_range tv is what produces a limited-range file.
    '-vf', 'scale=in_range=full:out_range=tv,format=yuv420p',
    '-c:v', 'libx264',
    '-crf', '18',
    '-preset', 'veryfast',
    '-pix_fmt', 'yuv420p',
    '-colorspace', 'bt709',
    '-color_primaries', 'bt709',
    '-color_trc', 'bt709',
    '-color_range', 'tv',
    '-r', String(fps),
    '-movflags', '+faststart',
    // Encode to a sibling temp path and rename on success. Writing --out directly leaves a
    // playable-looking partial file when the watchdog fires, which is worse than no file.
    partial,
  ];
  const encoder = spawn(args.ffmpeg, ffmpegArgs, {stdio: ['pipe', 'ignore', 'pipe']});
  let encoderError = '';
  encoder.stderr.on('data', (chunk) => {
    encoderError += chunk.toString();
  });
  const encoderDone = new Promise((resolve) => encoder.on('close', resolve));
  encoder.stdin.on('error', () => {
    /* EPIPE after a watchdog kill is expected, not a new failure */
  });

  let cdp = null;
  let failed = true;
  try {
    cdp = await connect(await endpointFor(child, profileDir));
    const {targetId} = await cdp.send('Target.createTarget', {url: 'about:blank'});
    const {sessionId} = await cdp.send('Target.attachToTarget', {targetId, flatten: true});
    const send = (method, params) => cdp.send(method, params, sessionId);

    await send('Page.enable');
    await send('Runtime.enable');
    await send('Network.enable');
    // Isolation layer 3.
    await send('Network.setBlockedURLs', {
      urls: ['http://*', 'https://*', 'ws://*', 'wss://*'],
    });
    await send('Emulation.setDeviceMetricsOverride', {
      width,
      height,
      deviceScaleFactor: 1,
      mobile: false,
    });

    await send('Page.navigate', {url: `file:///${document.replace(/\\/g, '/')}`});

    // An exception inside the page returns `exceptionDetails` instead of throwing here. Ignoring
    // it is how a broken seek produces 900 identical frames and a green render.
    const evaluate = async (expression) => {
      const result = await send('Runtime.evaluate', {
        expression,
        awaitPromise: true,
        returnByValue: true,
      });
      if (result.exceptionDetails) {
        const detail = result.exceptionDetails.exception?.description
          ?? result.exceptionDetails.text
          ?? 'unknown page exception';
        throw new Error(`page exception: ${String(detail).slice(0, 400)}`);
      }
      return result;
    };

    const readyDeadline = Date.now() + 30_000;
    let ready = false;
    while (Date.now() < readyDeadline) {
      const probe = await evaluate(
        '!!(window.OPENER && window.OPENER.ready && ' +
          '(!window.OPENER.clipsReady || window.OPENER.clipsReady()))',
      );
      if (probe.result && probe.result.value === true) {
        ready = true;
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    if (!ready) throw new Error('the document never became ready (window.OPENER.ready)');

    await evaluate('document.fonts.ready.then(function () { return true; })');
    const shape = await evaluate(
      'JSON.stringify({W: window.OPENER.W, H: window.OPENER.H, DURATION: window.OPENER.DURATION})',
    );
    const reported = JSON.parse(shape.result.value);
    if (reported.W !== width || reported.H !== height) {
      throw new Error(
        `document stage is ${reported.W}x${reported.H}, requested ${width}x${height}`,
      );
    }
    const expectedFrames = Math.ceil(reported.DURATION * fps);
    if (expectedFrames !== frames) {
      throw new Error(
        `document DURATION ${reported.DURATION}s is ${expectedFrames} frames at ${fps} fps, ` +
          `but ${frames} were requested`,
      );
    }

    const cancelFile = path.join(staging, 'CANCEL');
    // One template literal, then one substitution. Chaining `+` and `.replace` applies the
    // replace to the LAST literal only, which silently leaves `TIME` undefined in the earlier
    // fragments and makes every captured frame the same picture.
    const seekExpression = (time) =>
      `window.OPENER.seekFrame ? window.OPENER.seekFrame(${time}) : ` +
      `(window.OPENER.seek ? window.OPENER.seek(${time}) : window.OPENER.tl.time(${time}));` +
      'new Promise(function (r) { requestAnimationFrame(function () {' +
      'requestAnimationFrame(function () { r(true); }); }); })';

    let digest = createHash('sha256');
    for (let index = 0; index < frames; index += 1) {
      if (timedOut) throw new Error('wall clock exceeded');
      if (index % 30 === 0 && existsSync(cancelFile)) throw new Error('cancelled');

      await evaluate(seekExpression(index / fps));
      const shot = await send('Page.captureScreenshot', {
        format: 'jpeg',
        quality: 95,
        optimizeForSpeed: true,
      });
      const buffer = Buffer.from(shot.data, 'base64');
      digest.update(buffer);
      if (!encoder.stdin.write(buffer)) {
        await new Promise((resolve) => encoder.stdin.once('drain', resolve));
      }
    }
    encoder.stdin.end();
    const code = await encoderDone;
    if (code !== 0) throw new Error(`ffmpeg exited ${code}: ${encoderError.slice(-800)}`);
    renameSync(partial, args.out);

    // The page's own title is the only channel a probe script has to report what it managed to do.
    // Recording it makes "the page could not read a local file" an assertion instead of a hope.
    const titleProbe = await evaluate('document.title');
    const receipt = {
      frames,
      fps,
      width,
      height,
      frame_sha256: digest.digest('hex'),
      props_sha256: sha256(readFileSync(props)),
      document: path.basename(document),
      document_title: String(titleProbe.result?.value ?? ''),
    };
    writeFileSync(`${args.out}.json`, JSON.stringify(receipt, null, 2), 'utf8');
    failed = false;
    return receipt;
  } finally {
    clearTimeout(watchdog);
    if (cdp) cdp.close();
    killTree(child);
    // A failed or killed render leaves nothing behind: no partial file, no stale output.
    rmSync(partial, {force: true});
    if (failed) rmSync(args.out, {force: true});
    try {
      encoder.stdin.destroy();
    } catch {
      /* already closed */
    }
    try {
      rmSync(profileDir, {recursive: true, force: true});
    } catch {
      /* the OS reclaims it */
    }
  }
}

async function main() {
  let args;
  try {
    args = parseArgs(process.argv.slice(2));
  } catch (error) {
    fail(EXIT.BAD_ARGS, `${error.message}\n${USAGE}`);
  }

  try {
    for (const name of ['props', 'out', 'staging', 'chrome']) {
      requireAbsolute(args[name], `--${name}`);
    }
    args.ffmpeg = args.ffmpeg || 'ffmpeg';
    const wallClockS = positiveInt(args['wall-clock'], '--wall-clock', 900);
    const frameCap = positiveInt(args['frame-cap'], '--frame-cap', 3000);
    const fps = positiveInt(args.fps, '--fps', undefined);
    const frames = positiveInt(args.frames, '--frames', undefined);

    if (frames > frameCap) throw new Error(`frame count ${frames} exceeds the frame cap ${frameCap}`);
    if (!existsSync(args.props)) throw new Error(`render props missing at ${args.props}`);
    if (!existsSync(args.chrome)) throw new Error(`chrome-headless-shell missing at ${args.chrome}`);
    if (!path.isAbsolute(args.out)) throw new Error('--out must be absolute');

    const props = JSON.parse(readFileSync(args.props, 'utf8'));
    const storyboard = props.storyboard ?? props;
    const width = Number(storyboard.width ?? 1080);
    const height = Number(storyboard.height ?? 1920);
    if (!Number.isInteger(width) || !Number.isInteger(height) || width <= 0 || height <= 0) {
      throw new Error('storyboard width/height must be positive integers');
    }

    mkdirSync(args.staging, {recursive: true});
    const document = args.html;
    if (document === undefined) {
      throw new Error('--html is required: this driver captures a document, it does not author one');
    }
    requireAbsolute(document, '--html');
    if (!existsSync(document)) throw new Error(`document missing at ${document}`);

    const receipt = await capture({
      args,
      props: args.props,
      document,
      staging: args.staging,
      width,
      height,
      fps,
      frames,
      wallClockS,
    });

    if (args.json) process.stdout.write(`${JSON.stringify(receipt)}\n`);
  } catch (error) {
    if (error && error.message === 'wall clock exceeded') {
      fail(EXIT.TIMEOUT, 'wall clock exceeded; no output was written');
    }
    if (error && error.message === 'cancelled') {
      fail(EXIT.TIMEOUT, 'cancelled; no output was written');
    }
    fail(EXIT.CAPTURE_FAILED, `${error && error.message ? error.message : error}`);
  }
}

await main();
