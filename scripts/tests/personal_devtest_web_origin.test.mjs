// contract-test-file: tooling
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { stripTypeScriptTypes } from 'node:module';
import test from 'node:test';

// Playwright's tests package is CommonJS. Strip the type-only declarations
// here and load the small helper as ESM without installing browser dependencies.
const helper = new URL('../../frontend/apps/web_app/tests/helpers/personal-devtest-web-origin.ts', import.meta.url);
const source = stripTypeScriptTypes(readFileSync(helper, 'utf8'));
const { preparePersonalDevtestWebOrigin, privateWebRequest } = await import(
  'data:text/javascript;base64,' + Buffer.from(source).toString('base64')
);

const preview = 'http://127.0.0.1:5174';

test('candidate documents and assets only resolve to runner loopback', () => {
  const document = privateWebRequest('https://app.dev.openmates.org/?e2e=1', 'GET', preview);
  assert.equal(document.kind, 'preview');
  assert.equal(document.target.href, preview + '/?e2e=1');
  const escaped = privateWebRequest('https://app.dev.openmates.org//another.example/script.js', 'GET', preview);
  assert.equal(escaped.target.origin, preview);
  assert.equal(escaped.target.pathname, '//another.example/script.js');
  assert.throws(() => privateWebRequest('https://app.dev.openmates.org/', 'GET', 'http://outside.invalid'));
});

test('only real dev API is admitted outside the candidate app origin', () => {
  assert.equal(privateWebRequest('https://api.dev.openmates.org/v1/auth/login', 'POST', preview).kind, 'dev-api');
  for (const url of ['https://api.openmates.org/v1/auth/login', 'https://app.dev.openmates.org.evil.invalid/', preview]) {
    assert.equal(privateWebRequest(url, 'GET', preview).kind, 'blocked');
  }
  assert.equal(privateWebRequest('https://app.dev.openmates.org/', 'POST', preview).kind, 'blocked');
});

test('a failed candidate asset cannot fall through to the real dev site', async (t) => {
  const registration = {};
  const oldPreview = process.env.OPENMATES_PRIVATE_WEB_PREVIEW;
  process.env.OPENMATES_PRIVATE_WEB_PREVIEW = preview;
  t.after(() => {
    if (oldPreview === undefined) delete process.env.OPENMATES_PRIVATE_WEB_PREVIEW;
    else process.env.OPENMATES_PRIVATE_WEB_PREVIEW = oldPreview;
  });
  await preparePersonalDevtestWebOrigin({
    route: async (matcher, apply) => { registration.matcher = matcher; registration.apply = apply; },
    routeWebSocket: async (matcher) => { registration.webSocket = matcher; },
  });
  assert.equal(registration.matcher, '**/*');
  assert.equal(registration.webSocket.test('wss://api.dev.openmates.org/v1/ws?token=fixture'), false);
  assert.equal(registration.webSocket.test('wss://other.invalid/v1/ws'), true);
  t.mock.method(globalThis, 'fetch', async (address, options) => {
    assert.equal(address.origin, preview);
    assert.deepEqual(options.headers, { accept: 'text/javascript' });
    assert.equal(options.redirect, 'manual');
    return new Response('', { status: 404 });
  });
  const aborted = [];
  await registration.apply({
    request: () => ({
      url: () => 'https://app.dev.openmates.org/_app/missing.js',
      method: () => 'GET',
      headers: () => ({ accept: 'text/javascript', cookie: 'synthetic-private', authorization: 'synthetic-private' }),
    }),
    abort: async (error) => aborted.push(error),
    continue: async () => assert.fail('candidate route must never reach the public app'),
    fulfill: async () => assert.fail('a missing asset cannot satisfy startup'),
  });
  assert.deepEqual(aborted, ['failed']);
});
