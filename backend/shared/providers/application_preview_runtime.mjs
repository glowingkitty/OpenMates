// Public template tooling only. Snapshots contain public source/dependencies and
// a fresh blank browser context. User code is compiled only in each E2B clone.
import fs from 'node:fs';
import { createHash, randomBytes } from 'node:crypto';
import { createRequire } from 'node:module';
import { createServer } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

const require = createRequire('/home/user/.cache/openmates-application-capture/package.json');
const { chromium } = require('playwright');
const requestPath = '/tmp/openmates-preview-request.json';
const statusPath = '/tmp/openmates-preview-status.json';
const pngPath = '/tmp/openmates-preview-capture.png';
const port = 5173;
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
function status(value) {
  fs.writeFileSync(statusPath + '.tmp', JSON.stringify(value));
  fs.renameSync(statusPath + '.tmp', statusPath);
}

// This section executes at template BUILD time, inside E2B. A clone resumes
// below with the server listening and public dependencies already optimized.
fs.mkdirSync('/home/user/src', { recursive: true });
fs.writeFileSync('/home/user/index.html', '<div id="app"></div>\n<script type="module" src="/src/main.ts"></script>');
fs.writeFileSync('/home/user/src/main.ts', "import { mount } from 'svelte';\nimport App from './App.svelte';\nmount(App, { target: document.getElementById('app') });\n");
fs.writeFileSync('/home/user/src/App.svelte', '<h1 data-openmates-template>Template warming</h1>');
let ready = false;
let revision = randomBytes(16).toString('hex');
const server = await createServer({
  configFile: false,
  root: '/home/user',
  // Never watch a partially uploaded app or restart on its package.json. This
  // one-revision VM explicitly invalidates the graph after digest verification.
  server: { host: '0.0.0.0', port, strictPort: true, allowedHosts: [], hmr: false, watch: null },
  plugins: [svelte({ configFile: false }), {
    name: 'openmates-static-preview',
    transformIndexHtml: {
      order: 'post',
      handler: html => html.replace(/<script\b[^>]*\bsrc=["']\/@vite\/client["'][^>]*><\/script>\s*/g, ''),
    },
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        res.setHeader('Cache-Control', 'no-store');
        if (!ready && req.headers['x-openmates-bootstrap-probe'] !== revision) {
          res.statusCode = 503;
          res.end('Application starting');
          return;
        }
        if (ready) res.setHeader('X-OpenMates-Preview-Ready', revision);
        next();
      });
    },
  }],
});
await server.listen();
const launchOptions = {
  headless: true,
  args: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
         '--no-zygote', '--single-process', '--js-flags=--jitless'],
};
const warmBrowser = await chromium.launch(launchOptions);
const browserOptions = { viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 };
const warmContext = await warmBrowser.newContext({ ...browserOptions,
  extraHTTPHeaders: { 'X-OpenMates-Bootstrap-Probe': revision } });
const warmPage = await warmContext.newPage();
await warmPage.goto('http://127.0.0.1:' + port + '/', { waitUntil: 'networkidle', timeout: 60000 });
await warmPage.locator('[data-openmates-template]').waitFor();
await warmBrowser.close();
// Discard all template browser state before snapshotting. Only public Vite
// dependency caches survive; no cookies or user application state are shared.
// A new process also avoids Chromium single-process context replacement bugs.
const browser = await chromium.launch(launchOptions);
const context = await browser.newContext(browserOptions);
const page = await context.newPage();
await page.goto('about:blank');
status({ status: 'waiting', version: 2 });
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
const timings = { create_server_ms: 0 };
let stage = 'activate_revision';
try {
  if (request.port !== port || !/^[a-f0-9]{32}$/.test(request.revision) ||
      !Array.isArray(request.allowed_hosts) || request.allowed_hosts.length !== 1 ||
      !/^[a-z0-9][a-z0-9.-]*$/i.test(request.allowed_hosts[0])) throw new Error('Invalid startup request');
  revision = request.revision;
  // Vite reads this exact list per request; no wildcard host permission is used.
  server.config.server.allowedHosts = request.allowed_hosts;
  server.moduleGraph.invalidateAll();
  stage = 'compile_application';
  await server.transformRequest('/src/App.svelte');
  await server.transformRequest('/src/main.ts');
  timings.compile_ms = performance.now() - began;
  stage = 'local_readiness';
  for (let count = 0; count < 2; count++) {
    const response = await fetch('http://127.0.0.1:' + port + '/', {
      headers: { 'X-OpenMates-Bootstrap-Probe': revision },
    });
    await response.text();
    if (!response.ok) throw new Error('Local application readiness failed');
    if (count === 0) await pause(50);
  }
  ready = true;
  timings.ready_ms = performance.now() - began;
  status({ status: 'running', revision, timings });

  stage = 'capture';
  try {
    await page.goto('http://127.0.0.1:' + port + '/', { waitUntil: 'load', timeout: 60000 });
    try { await page.waitForLoadState('networkidle', { timeout: 5000 }); } catch (_) { /* bounded settle */ }
    await page.evaluate(() => document.fonts && document.fonts.ready);
    await page.waitForTimeout(500);
    await page.screenshot({ path: pngPath + '.tmp', type: 'png', fullPage: true });
    fs.renameSync(pngPath + '.tmp', pngPath);
    timings.capture_ms = performance.now() - began - timings.ready_ms;
    status({ status: 'captured', revision, timings });
  } finally {
    try { await browser.close(); } catch (_) { /* Sandbox teardown owns the process lifetime. */ }
  }
} catch (error) {
  // Keep source/stack traces inside the VM; only content-free state is read.
  fs.writeFileSync('/tmp/openmates-preview-error.txt', String(error && error.stack || error));
  status({ status: 'failed', stage, timings });
}
