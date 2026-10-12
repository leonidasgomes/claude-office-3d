import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawn, execFileSync } from 'node:child_process';
import { cp, mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import { PNG } from 'pngjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const output = fileURLToPath(new URL('./results/', import.meta.url));
const base = 'http://127.0.0.1:8765';
const result = { status: 'failed', stage: 'setup', commit: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim(),
  platform: process.platform, node: process.version, sandboxRequested: true,
  screenshots: {}, httpErrors: [], errors: [], consoleErrors: [], contextLosses: 0, blockedRequests: [], requestsFailed: [] };
let browser, server, serverLog = "", serverReady = false;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
function stats(bytes) {
  const p = PNG.sync.read(bytes), colors = new Set();
  let min = 255, max = 0;
  for (let i = 0; i < p.data.length; i += 4) {
    colors.add(`${p.data[i] >> 3},${p.data[i + 1] >> 3},${p.data[i + 2] >> 3}`);
    min = Math.min(min, p.data[i], p.data[i + 1], p.data[i + 2]);
    max = Math.max(max, p.data[i], p.data[i + 1], p.data[i + 2]);
  }
  return { width: p.width, height: p.height, quantizedColors: colors.size, range: max - min };
}
async function capture(page, name) {
  const bytes = await page.locator('#cena > canvas').screenshot({ type: 'png', timeout: 10000 });
  assert(bytes.length < 400000, 'Screenshot exceeds bounded log evidence size');
  await writeFile(`${output}${name}.png`, bytes);
  // Short lines avoid truncation; no artifact storage or cache is created in CI.
  const encoded = bytes.toString('base64');
  const sha256 = createHash('sha256').update(bytes).digest('hex');
  result.screenshots[name] = { bytes: bytes.length, sha256 };
  console.log(`OFFICE_PNG_BEGIN ${name} ${bytes.length} ${sha256}`);
  for (let i = 0; i < encoded.length; i += 2000) console.log(`OFFICE_PNG_DATA ${encoded.slice(i, i + 2000)}`);
  console.log(`OFFICE_PNG_END ${name}`);
  return bytes;
}
try {
  await mkdir(output, { recursive: true });
  // Same pinned Three.js version as index.html, through the app's supported vendor path.
  await cp(new URL('./node_modules/three/', import.meta.url), `${root}vendor/three`, { recursive: true });
  server = spawn('python3', ['-u', 'ferramentas/webgl/serve.py'], { cwd: root,
    env: { PATH: process.env.PATH, PYTHONUNBUFFERED: '1' }, stdio: ['ignore', 'pipe', 'pipe'] });
  for (const stream of [server.stdout, server.stderr]) stream.on('data', b => {
    serverLog = (serverLog + b).slice(-12000);
    if (serverLog.includes('Synthetic Office ready on loopback; background integrations disabled')) serverReady = true;
  });
  for (let i = 0; i < 60; i++) {
    if (server.exitCode !== null) throw new Error('Synthetic server exited before readiness');
    if (serverReady) {
      try {
        const response = await fetch(`${base}/config`, { signal: AbortSignal.timeout(1000) });
        const config = await response.json();
        if (response.ok && config.titulo === 'Office Linux - validacao sintetica' && server.exitCode === null) break;
      } catch {}
    }
    if (i === 59) throw new Error('Synthetic server readiness timed out');
    await sleep(250);
  }
  result.stage = 'browser-launch';
  // Exact defaults from pinned Playwright 1.56.1. Keep browser protections enabled.
  const relaxedDefaults = [
    '--unsafely-disable-devtools-self-xss-warnings', '--disable-client-side-phishing-detection',
    '--disable-ipc-flooding-protection', '--disable-popup-blocking', '--disable-prompt-on-repost',
    '--disable-hang-monitor', '--password-store=basic', '--use-mock-keychain',
    '--disable-features=AcceptCHFrame,AvoidUnnecessaryBeforeUnloadCheckSync,DestroyProfileOnBrowserClose,DialMediaRouteProvider,GlobalMediaControls,HttpsUpgrades,LensOverlay,MediaRouter,PaintHolding,ThirdPartyStoragePartitioning,Translate,AutoDeElevate,RenderDocument'
  ];
  browser = await chromium.launch({ channel: 'chromium', headless: true, chromiumSandbox: true,
    ignoreDefaultArgs: relaxedDefaults, timeout: 30000 });
  result.browser = browser.version();
  const cdp = await browser.newBrowserCDPSession();
  result.browserArguments = (await cdp.send('Browser.getBrowserCommandLine')).arguments;
  assert(!result.browserArguments.some(a => /^(--no-sandbox|--disable-setuid-sandbox|--enable-unsafe-swiftshader|--disable-web-security|--ignore-certificate-errors)(=|$)/.test(a)), 'Unsafe browser launch flags');
  assert(!result.browserArguments.some(a => relaxedDefaults.includes(a) || a.startsWith('--disable-features=')), 'Browser protection override remains');
  result.browserArguments = result.browserArguments.map(a => a.startsWith('--user-data-dir=') ? '--user-data-dir=<ephemeral-profile>' : a.startsWith('/') ? '<chromium-executable>' : a);
  const context = await browser.newContext({ viewport: { width: 1000, height: 700 }, deviceScaleFactor: 1, serviceWorkers: 'block' });
  await context.route('**/*', route => {
    const u = new URL(route.request().url());
    if (u.origin === base) return route.continue();
    result.blockedRequests.push(u.origin);
    return route.abort('blockedbyclient');
  });
  await context.routeWebSocket('**/*', socket => {
    result.blockedRequests.push(`WebSocket:${new URL(socket.url()).origin}`);
    socket.close();
  });
  const page = await context.newPage();
  page.on('response', response => {
    if (response.status() >= 400) result.httpErrors.push({ method: response.request().method(),
      path: new URL(response.url()).pathname, status: response.status() });
  });
  page.on('pageerror', e => result.errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') result.consoleErrors.push(m.text()); });
  page.on('requestfailed', r => result.requestsFailed.push({ url: new URL(r.url()).pathname, error: r.failure()?.errorText }));
  result.stage = 'webgl-preflight';
  result.preflight = await page.evaluate(() => {
    const canvas = document.createElement('canvas'); canvas.width = canvas.height = 16;
    const gl = canvas.getContext('webgl2');
    if (!gl) return { available: false };
    gl.clearColor(1, 0, 0, 1); gl.clear(gl.COLOR_BUFFER_BIT);
    gl.enable(gl.SCISSOR_TEST); gl.scissor(8, 0, 8, 16);
    gl.clearColor(0, 1, 0, 1); gl.clear(gl.COLOR_BUFFER_BIT);
    const red = new Uint8Array(4), green = new Uint8Array(4);
    gl.readPixels(2, 2, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, red);
    gl.readPixels(12, 2, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, green);
    const ext = gl.getExtension('WEBGL_debug_renderer_info');
    return { available: true, red: [...red], green: [...green], error: gl.getError(),
      vendor: gl.getParameter(gl.VENDOR), renderer: ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER), version: gl.getParameter(gl.VERSION) };
  });
  assert.equal(result.preflight.available, true, 'ENVIRONMENT_BLOCKER: WebGL2 context unavailable');
  assert.deepEqual(result.preflight.red, [255, 0, 0, 255]);
  assert.deepEqual(result.preflight.green, [0, 255, 0, 255]);
  assert.equal(result.preflight.error, 0);
  await context.addInitScript(() => {
    window.__visualContexts = [];
    const original = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (...args) {
      const gl = original.apply(this, args);
      if (gl && /^webgl2?$/.test(args[0]) && !window.__visualContexts.some(x => x.canvas === this)) {
        const record = { canvas: this, gl, losses: 0, drawCalls: 0, triangles: 0 };
        for (const method of ['drawArrays', 'drawElements', 'drawArraysInstanced', 'drawElementsInstanced']) {
          if (typeof gl[method] !== 'function') continue;
          const draw = gl[method];
          gl[method] = function (...values) {
            const value = draw.apply(this, values);
            record.drawCalls++;
            const count = method.startsWith('drawArrays') ? values[2] : values[1];
            const instances = method.endsWith('Instanced') ? values.at(-1) : 1;
            if (values[0] === gl.TRIANGLES) record.triangles += Math.floor(count / 3) * instances;
            return value;
          };
        }
        this.addEventListener('webglcontextlost', () => { record.losses++; });
        window.__visualContexts.push(record);
      }
      return gl;
    };
  });
  result.stage = 'office-scene';
  await page.goto(base, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForFunction(() => window.__office && document.querySelector('#cena > canvas'), null, { timeout: 30000 });
  await sleep(2000);
  const before = await capture(page, 'scene-before');
  result.before = stats(before);
  assert(result.before.quantizedColors > 100 && result.before.range > 80, 'Scene pixels are blank or uniform');
  result.cameraBefore = await page.evaluate(() => window.__office.camera.position.toArray());
  const box = await page.locator('#cena > canvas').boundingBox();
  await page.mouse.move(box.x + box.width * 0.55, box.y + box.height * 0.55);
  await page.mouse.wheel(0, -600);
  await sleep(1200);
  result.cameraAfter = await page.evaluate(() => window.__office.camera.position.toArray());
  assert(result.cameraAfter.some((v, i) => Math.abs(v - result.cameraBefore[i]) > 0.1), 'Wheel did not move camera');
  const after = await capture(page, 'scene-after');
  result.after = stats(after);
  const a = PNG.sync.read(before), b = PNG.sync.read(after);
  assert.equal(a.data.length, b.data.length);
  let changed = 0;
  for (let i = 0; i < a.data.length; i += 4) {
    if (Math.abs(a.data[i] - b.data[i]) + Math.abs(a.data[i + 1] - b.data[i + 1]) + Math.abs(a.data[i + 2] - b.data[i + 2]) > 30) changed++;
  }
  result.changedPixelRatio = changed / (a.width * a.height);
  assert(result.changedPixelRatio > 0.05, 'No substantial visual change after camera interaction');
  result.sceneContext = await page.evaluate(() => {
    const c = window.__visualContexts.find(x => x.canvas.matches('#cena > canvas'));
    return c ? { drawCalls: c.drawCalls, triangles: c.triangles, losses: c.losses, lost: c.gl.isContextLost(), error: c.gl.getError(), width: c.gl.drawingBufferWidth, height: c.gl.drawingBufferHeight } : null;
  });
  assert(result.sceneContext && !result.sceneContext.lost && result.sceneContext.losses === 0 && result.sceneContext.error === 0);
  assert(result.sceneContext.drawCalls > 0 && result.sceneContext.triangles > 100, 'No substantial real 3D drawing observed');
  result.contextLosses = result.sceneContext.losses;
  assert.deepEqual(result.httpErrors, []);
  assert.deepEqual(result.errors, []);
  assert.deepEqual(result.consoleErrors, []);
  assert.deepEqual(result.blockedRequests, []);
  assert.deepEqual(result.requestsFailed, []);
  result.stage = 'complete'; result.status = 'passed';
} catch (e) {
  result.failure = e.message;
  if (result.stage === 'setup') result.serverDiagnostics = serverLog.replace(/(?:[A-Za-z]:)?\/[^\s"']+/g, '<path>').slice(-4000);
  console.error(`WEBGL_VALIDATION_FAILED: ${result.stage}: ${e.message}`);
  process.exitCode = 1;
} finally {
  if (browser) await browser.close();
  if (server) { server.kill('SIGTERM'); await Promise.race([new Promise(r => server.once('exit', r)), sleep(3000)]); if (server.exitCode === null) server.kill('SIGKILL'); }
  await mkdir(output, { recursive: true });
  await writeFile(`${output}result.json`, JSON.stringify(result, null, 2));
  console.log(`OFFICE_WEBGL_RESULT ${JSON.stringify(result)}`);
}
