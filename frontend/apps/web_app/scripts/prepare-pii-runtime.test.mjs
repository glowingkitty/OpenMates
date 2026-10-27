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
