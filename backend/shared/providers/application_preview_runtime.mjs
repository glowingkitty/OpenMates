// Public template tooling only. Build snapshots contain no user source, cookies
// or account credentials. One request is accepted per fresh disposable sandbox.
import fs from 'node:fs';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import { createServer } from 'vite';
import { compile } from 'svelte/compiler';
import '@sveltejs/vite-plugin-svelte';

const require = createRequire('/home/user/.cache/openmates-application-capture/package.json');
const { chromium } = require('playwright');
const requestPath = '/tmp/openmates-preview-request.json';
const statusPath = '/tmp/openmates-preview-status.json';
const pngPath = '/tmp/openmates-preview-capture.png';
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
function status(value) {
  fs.writeFileSync(statusPath + '.tmp', JSON.stringify(value));
  fs.renameSync(statusPath + '.tmp', statusPath);
}

// Pay process/module/compiler/browser initialization once during template build.
compile('<h1>Template ready</h1>', { generate: 'client', filename: 'Warm.svelte' });
const browser = await chromium.launch({
  headless: true,
  args: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
         '--no-zygote', '--single-process', '--js-flags=--jitless'],
});
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
const page = await context.newPage();
await page.goto('about:blank');
status({ status: 'waiting', version: 1 });
fs.writeFileSync('/tmp/openmates-preview-template-ready', '1');

let request;
while (true) {
  try {
    const candidate = JSON.parse(fs.readFileSync(requestPath, 'utf8'));
    if (candidate.files && Object.keys(candidate.files).length && Object.entries(candidate.files).every(([path, digest]) =>
        createHash('sha256').update(fs.readFileSync('/home/user/' + path)).digest('hex') === digest)) {
      request = candidate;
      break;
    }
  } catch (_) { /* The file API may still be uploading this revision. */ }
  await pause(25);
}
const began = performance.now();
const timings = {};
let stage = 'create_server';
try {
  if (!Number.isInteger(request.port) || request.port < 1024 || request.port > 65535 ||
      !/^[a-f0-9]{32}$/.test(request.revision)) throw new Error('Invalid startup request');
  let ready = false;
  const server = await createServer({
    configFile: '/home/user/vite.config.openmates.mjs',
    server: { host: '0.0.0.0', port: request.port, strictPort: true },
    plugins: [{
      name: 'openmates-revision-readiness',
      configureServer(server) {
        server.middlewares.use((_req, res, next) => {
          if (ready) res.setHeader('X-OpenMates-Preview-Ready', request.revision);
          next();
        });
      },
    }],
  });
  timings.create_server_ms = performance.now() - began;
  stage = 'compile_application';
  // Compile the new user revision before making its root publicly ready.
  await server.listen();
  await server.transformRequest('/src/App.svelte');
  timings.compile_ms = performance.now() - began - timings.create_server_ms;
  stage = 'local_readiness';
  for (let count = 0; count < 2; count++) {
    const response = await fetch('http://127.0.0.1:' + request.port + '/');
    await response.text();
    if (!response.ok) throw new Error('Local application readiness failed');
    if (count === 0) await pause(50);
  }
  ready = true;
  timings.ready_ms = performance.now() - began;
  status({ status: 'running', revision: request.revision, timings });

  stage = 'capture';
  try {
    await page.goto('http://127.0.0.1:' + request.port + '/', { waitUntil: 'load', timeout: 60000 });
    try { await page.waitForLoadState('networkidle', { timeout: 5000 }); } catch (_) { /* bounded settle */ }
    await page.evaluate(() => document.fonts && document.fonts.ready);
    await page.waitForTimeout(500);
    await page.screenshot({ path: pngPath + '.tmp', type: 'png', fullPage: true });
    fs.renameSync(pngPath + '.tmp', pngPath);
    timings.capture_ms = performance.now() - began - timings.ready_ms;
    status({ status: 'captured', revision: request.revision, timings });
  } finally {
    try { await browser.close(); } catch (_) { /* Sandbox teardown still owns the process lifetime. */ }
  }
} catch (error) {
  // Keep source/stack traces inside the VM; only a content-free state is read.
  fs.writeFileSync('/tmp/openmates-preview-error.txt', String(error && error.stack || error));
  status({ status: 'failed', stage, timings });
}
