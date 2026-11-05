import assert from 'node:assert/strict';
import { test } from 'node:test';
import { execFileSync } from 'node:child_process';
import { assertWebNodeRuntimeSecurity } from '../src/lib/server/webNodeRuntimeSecurity.mjs';

const patched = { BROTLI_DECODER_ERROR_FORMAT_BLOCK_SWITCH: -17 };

// contract-test: supporting surface=gui.web assertions=pii.surface.semantic-parity
test('accepts the patched Node floor and later Node 24 releases', () => {
  for (const nodeVersion of ['24.22.1', 'v24.22.1', '24.22.2', '24.23.0']) {
    assert.doesNotThrow(() => assertWebNodeRuntimeSecurity({ nodeVersion, brotliConstants: patched }));
  }
});

// contract-test: supporting surface=gui.web assertions=pii.surface.semantic-parity
test('rejects pre-patch Node 24 and unsupported Node majors even if a constant is supplied', () => {
  for (const nodeVersion of ['24.22.0', '24.21.9', '20.20.0', '22.23.4', '25.0.0']) {
    assert.throws(() => assertWebNodeRuntimeSecurity({ nodeVersion, brotliConstants: patched }), /Node\.js 24\.22\.1/);
  }
});

// contract-test: supporting surface=gui.web assertions=pii.surface.semantic-parity
test('rejects a claimed patched Node version with a missing or wrong backport signature', () => {
  for (const brotliConstants of [{}, { BROTLI_DECODER_ERROR_FORMAT_BLOCK_SWITCH: -16 }]) {
    assert.throws(() => assertWebNodeRuntimeSecurity({ nodeVersion: '24.22.1', brotliConstants }), /Brotli security patch/);
  }
});

// contract-test: supporting surface=gui.web assertions=pii.surface.semantic-parity
test('server hooks initialize below the preparation floor and preserve security response headers', () => {
  const hooks = new URL('../src/hooks.server.ts', import.meta.url).href;
  execFileSync(process.execPath, ['--experimental-strip-types', '--input-type=module', '-e', `
    import assert from 'node:assert/strict';
    Object.defineProperty(process.versions, 'node', { value: '24.21.0' });
    const { handle } = await import(${JSON.stringify(hooks)});
    const body = 'export const env = {};';
    const response = await handle({
      event: { url: new URL('https://app.dev.openmates.org/privacy'), request: new Request('https://app.dev.openmates.org/privacy') },
      resolve: async () => new Response(body, { headers: { 'Content-Type': 'application/javascript' } })
    });
    assert.equal(response.status, 200);
    assert.equal(await response.text(), body);
    assert.equal(response.headers.get('X-Content-Type-Options'), 'nosniff');
    assert.equal(response.headers.get('X-Frame-Options'), 'DENY');
  `], { stdio: 'pipe' });
});

// contract-test: tooling
test('unpatched server fetch rejects both external and same-origin requests before networking', () => {
  const hooks = new URL('../src/hooks.server.ts', import.meta.url).href;
  execFileSync(process.execPath, ['--experimental-strip-types', '--input-type=module', '-e', `
    import assert from 'node:assert/strict';
    Object.defineProperty(process.versions, 'node', { value: '24.21.0' });
    const { handleFetch } = await import(${JSON.stringify(hooks)});
    let calls = 0;
    for (const url of ['https://untrusted.invalid/data', 'https://app.dev.openmates.org/static.json']) {
      await assert.rejects(handleFetch({ request: new Request(url), fetch: async () => { calls++; return new Response('{}'); } }), /Brotli security patch/);
    }
    assert.equal(calls, 0);
  `], { stdio: 'pipe' });
});

// contract-test: tooling
test('compressed incoming bodies are rejected before a handler reads them', async () => {
  const { handle } = await import('../src/hooks.server.ts');
  let calls = 0;
  for (const encoding of ['br', 'gzip', 'identity, br']) {
    const request = new Request('https://app.dev.openmates.org/s/abc123', { method: 'POST', body: '{}', headers: { 'Content-Encoding': encoding } });
    const response = await handle({ event: { request, url: new URL(request.url) }, resolve: async () => { calls++; return new Response('unsafe'); } });
    assert.equal(response.status, 415);
    assert.equal(response.headers.get('X-Content-Type-Options'), 'nosniff');
    assert.equal(request.bodyUsed, false);
  }
  assert.equal(calls, 0);
});

// contract-test: supporting surface=gui.web assertions=pii.web.licensing-egress-boundary
test('release pins cover the exact runtime and three immutable model files', async () => {
  const { piiPinnedFiles, piiModel } = await import('./pii-runtime-manifest.mjs');
  assert.deepEqual(Object.keys(piiPinnedFiles), [
    'sdk.js', 'RedactWeb.wasm', 'litert_wasm_compat_internal.js', 'litert_wasm_compat_internal.wasm',
    'model/redact.tflite', 'model/redact_tokenizer.bin', 'model/labels.json',
  ]);
  assert.equal(piiModel.revision, '3ed5033aeb544f454ebde77dc76fd7b7e76cc572');
  for (const pin of Object.values(piiPinnedFiles)) {
    assert.match(pin.sha256, /^[a-f0-9]{64}$/);
    assert.ok(Number.isSafeInteger(pin.bytes) && pin.bytes > 0);
  }
});

// contract-test: supporting surface=gui.web assertions=pii.web.licensing-egress-boundary
test('refuses changed or missing package registry integrity', async () => {
  const { verifyPIIRegistryPins } = await import('./prepare-pii-runtime.mjs');
  const { piiRegistryIntegrities } = await import('./pii-runtime-manifest.mjs');
  const packages = Object.fromEntries(Object.entries(piiRegistryIntegrities).map(([name, integrity]) => [name, { resolution: { integrity } }]));
  assert.doesNotThrow(() => verifyPIIRegistryPins({ packages }));
  assert.throws(() => verifyPIIRegistryPins({}), /registry integrity mismatch/);
  packages['@desert-ant-labs/core@4.1.0'].resolution.integrity = 'sha512-unknown';
  assert.throws(() => verifyPIIRegistryPins({ packages }), /registry integrity mismatch/);
});

// contract-test: supporting surface=gui.web assertions=pii.web.licensing-egress-boundary
test('verifies fresh and cached bytes; rejects poisoned cache before any network', async () => {
  const { mkdtemp, writeFile, readFile, rm } = await import('node:fs/promises');
  const { tmpdir } = await import('node:os');
  const { join } = await import('node:path');
  const { createHash } = await import('node:crypto');
  const { preparePIICachedAsset } = await import('./prepare-pii-runtime.mjs');
  const root = await mkdtemp(join(tmpdir(), 'pii-assets-test-'));
  const cached = join(root, 'model');
  const bytes = Buffer.from('public model fixture');
  const expected = { bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex') };
  let calls = 0;
  const options = { cached, expected, url: 'https://huggingface.co/public/resolve/immutable/model', fetchAsset: async (url, init) => {
    calls++;
    assert.equal(url, options.url);
    assert.equal(init.credentials, 'omit');
    assert.equal(init.referrerPolicy, 'no-referrer');
    return new Response(bytes);
  } };
  try {
    assert.deepEqual(await preparePIICachedAsset(options), bytes);
    assert.deepEqual(await readFile(cached), bytes);
    assert.deepEqual(await preparePIICachedAsset(options), bytes);
    assert.equal(calls, 1);
    await writeFile(cached, Buffer.alloc(bytes.length));
    await assert.rejects(preparePIICachedAsset(options), /integrity mismatch/);
    assert.equal(calls, 1);
  } finally { await rm(root, { recursive: true, force: true }); }
});

// contract-test: supporting surface=gui.web assertions=pii.web.licensing-egress-boundary
test('rejects failed, HTML, oversized, short and altered downloads without caching', async () => {
  const { mkdtemp, readdir, rm } = await import('node:fs/promises');
  const { tmpdir } = await import('node:os');
  const { join } = await import('node:path');
  const { createHash } = await import('node:crypto');
  const { preparePIICachedAsset } = await import('./prepare-pii-runtime.mjs');
  const root = await mkdtemp(join(tmpdir(), 'pii-rejected-test-'));
  const bytes = Buffer.from('okay');
  const expected = { bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex') };
  try {
    for (const response of [
      new Response('error', { status: 404 }),
      new Response(bytes, { headers: { 'content-type': 'text/html' } }),
      new Response('too long'), new Response('no'), new Response('evil'),
    ]) {
      await assert.rejects(preparePIICachedAsset({ cached: join(root, 'model'), expected, url: 'https://huggingface.co/public/model', fetchAsset: async () => response }), /PII (?:model download failed|asset (?:integrity mismatch|size exceeded))/);
      assert.deepEqual(await readdir(root), []);
    }
  } finally { await rm(root, { recursive: true, force: true }); }
});

// contract-test: supporting surface=gui.web assertions=pii.web.licensing-egress-boundary
test('Vercel and Vite dev/preview apply the same zero-network Worker response CSP', async () => {
  const { readFile } = await import('node:fs/promises');
  const { piiWorkerHeaders, piiRuntimePlugin, piiWorkerCSP } = await import('./prepare-pii-runtime.mjs');
  const { piiRuntimeBase } = await import('./pii-runtime-manifest.mjs');
  const vercel = JSON.parse(await readFile(new URL('../vercel.json', import.meta.url), 'utf8'));
  const worker = vercel.headers.find(entry => entry.source === `${piiRuntimeBase}worker.js`);
  assert.equal(worker.headers.find(header => header.key === 'Content-Security-Policy').value, piiWorkerCSP);
  for (const directive of ["connect-src 'none'", "worker-src 'none'", "script-src blob: 'wasm-unsafe-eval'", "default-src 'none'"]) assert.ok(piiWorkerCSP.includes(directive));
  for (const hook of ['configureServer', 'configurePreviewServer']) {
    const installed = [];
    piiRuntimePlugin()[hook]({ middlewares: { use: handler => installed.push(handler) } });
    assert.deepEqual(installed, [piiWorkerHeaders]);
  }
  for (const path of [`${piiRuntimeBase}worker.js`, `${piiRuntimeBase}worker.js?anything`, `${piiRuntimeBase}sdk.js`, '/privacy']) {
    const headers = {};
    let next = 0;
    piiWorkerHeaders({ url: path }, { setHeader: (key, value) => { headers[key] = value; } }, () => next++);
    assert.equal(next, 1);
    assert.equal(headers['Content-Security-Policy'], path.includes('worker.js') ? piiWorkerCSP : undefined);
  }
});

// contract-test: supporting surface=gui.web assertions=pii.web.licensing-egress-boundary
test('Vite orders the Worker policy before an eager SvelteKit-style static responder', async () => {
  const { resolveConfig } = await import('vite');
  const { piiRuntimePlugin, piiWorkerCSP } = await import('./prepare-pii-runtime.mjs');
  const { piiRuntimeBase } = await import('./pii-runtime-manifest.mjs');
  const staticPlugin = {
    name: 'sveltekit-style-static-responder',
    configureServer(server) {
      // SvelteKit's dev asset middleware ends existing static requests here;
      // later middleware never runs, unlike a simple header-only hook mock.
      server.middlewares.use((_req, res) => { res.end('worker source'); });
    },
  };
  // Match the application config: SvelteKit appears before the PII plugin.
  const config = await resolveConfig({
    configFile: false, envDir: false,
    plugins: [staticPlugin, piiRuntimePlugin()],
  }, 'serve');
  const middleware = [];
  const server = { middlewares: { use: handler => middleware.push(handler) } };
  for (const plugin of config.plugins) {
    if ([staticPlugin.name, 'openmates-pii-runtime'].includes(plugin.name)) plugin.configureServer(server);
  }
  const headers = {};
  let body;
  const request = { url: `${piiRuntimeBase}worker.js` };
  const response = {
    setHeader: (key, value) => { headers[key] = value; },
    end: value => { body = value; },
  };
  let index = 0;
  const next = () => middleware[index++]?.(request, response, next);
  next();
  assert.equal(body, 'worker source');
  assert.equal(headers['Content-Security-Policy'], piiWorkerCSP);
  assert.equal(headers['X-Content-Type-Options'], 'nosniff');
});
