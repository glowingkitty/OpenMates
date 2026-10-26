import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createServer, request as httpRequest } from 'node:http';
import { once } from 'node:events';
import { createPublicMetadataFetch } from '../src/lib/server/publicMetadataFetch.mjs';

const CHAT = 'https://api.dev.openmates.org/v1/share/chat/test-id/og-metadata?t=123';
const forbiddenFetch = () => { throw new Error('Ordinary fetch must not run'); };

async function fixture(t, handler, options = {}) {
  const requests = [];
  const server = createServer((request, response) => {
    requests.push({ url: request.url, headers: request.headers });
    handler(request, response);
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  t.after(() => new Promise((resolve) => {
    server.closeAllConnections();
    server.close(resolve);
  }));
  const base = `http://127.0.0.1:${server.address().port}`;
  const fetch = createPublicMetadataFetch({
    isPatched: () => false,
    // Only the injected fixture transport substitutes loopback. Production
    // input validation continues to require the fixed first-party HTTPS URLs.
    request: (url, init, callback) => httpRequest(base + url.pathname + url.search, init, callback),
    ...options
  });
  return { fetch, requests };
}

// contract-test: tooling
test('patched runtime preserves the standard SvelteKit fetch path', async () => {
  let calls = 0;
  const fetch = createPublicMetadataFetch({ isPatched: () => true, request: forbiddenFetch });
  const result = await fetch(CHAT, async (input, init) => {
    calls++;
    assert.equal(input, CHAT);
    assert.equal(init.cache, 'no-store');
    return new Response('{"title":"Patched"}');
  });
  assert.equal(calls, 1);
  assert.equal((await result.json()).title, 'Patched');
});

// contract-test: tooling
test('unpatched runtime preserves all three metadata flows using credential-free identity HTTPS', async (t) => {
  const { fetch, requests } = await fixture(t, (_request, response) => {
    response.writeHead(200, { 'content-type': 'application/json', 'set-cookie': 'never-forward=value' });
    response.end('{"title":"Public title","description":"Public description","image":"/public.png"}');
  });
  for (const input of [CHAT, 'https://api.openmates.org/v1/share/embed/test-id/og-metadata', 'https://api.dev.openmates.org/v1/share/short-url/abc123/metadata']) {
    const response = await fetch(input, forbiddenFetch);
    assert.equal((await response.json()).title, 'Public title');
    assert.equal(response.headers.get('set-cookie'), null);
  }
  assert.equal(requests.length, 3);
  for (const { headers } of requests) {
    assert.equal(headers['accept-encoding'], 'identity');
    assert.equal(headers.accept, 'application/json');
    assert.equal(headers.cookie, undefined);
    assert.equal(headers.authorization, undefined);
  }
});

// contract-test: tooling
test('identity response encoding is accepted explicitly', async (t) => {
  const { fetch } = await fixture(t, (_request, response) => {
    response.writeHead(200, { 'content-type': 'application/json', 'content-encoding': 'identity' });
    response.end('{"ok":true}');
  });
  assert.deepEqual(await (await fetch(CHAT, forbiddenFetch)).json(), { ok: true });
});

for (const encoding of ['br', 'BR', 'gzip', 'identity, br']) {
  // contract-test: tooling
  test(`rejects ${encoding} before consuming even a harmless invalid encoded body`, async (t) => {
    const { fetch } = await fixture(t, (_request, response) => {
      response.writeHead(200, { 'content-type': 'application/json', 'content-encoding': encoding });
      response.end('This is intentionally not compressed data, not an exploit payload.');
    });
    await assert.rejects(fetch(CHAT, forbiddenFetch), /Encoded public metadata is not permitted/);
  });
}

// contract-test: tooling
test('redirects are rejected without contacting the Location target', async (t) => {
  const { fetch, requests } = await fixture(t, (_request, response) => {
    response.writeHead(302, { location: 'https://attacker.invalid/compressed' });
    response.end();
  });
  await assert.rejects(fetch(CHAT, forbiddenFetch), /redirects are not permitted/);
  assert.equal(requests.length, 1);
});

// contract-test: tooling
test('rejects non-first-party origins, credentials, paths and query parameters before networking', async () => {
  let calls = 0;
  const fetch = createPublicMetadataFetch({ isPatched: () => false, request: () => { calls++; } });
  for (const input of [
    CHAT.replace('api.dev.openmates.org', 'attacker.invalid'),
    CHAT.replace('https:', 'http:'), CHAT.replace('https://', 'https://user:secret@'),
    CHAT.replace('/og-metadata', '/private'), CHAT.replace('?t=123', '?redirect=https://attacker.invalid'),
    CHAT + '#secret', CHAT.replace('api.dev.openmates.org', 'api.dev.openmates.org:8443')
  ]) await assert.rejects(fetch(input, forbiddenFetch), /only first-party public share metadata/);
  assert.equal(calls, 0);
});

// contract-test: tooling
test('HTTP errors preserve fallback without consuming their bodies', async (t) => {
  const { fetch } = await fixture(t, (_request, response) => { response.writeHead(404); response.end('not JSON'); });
  const response = await fetch(CHAT, forbiddenFetch);
  assert.equal(response.status, 404);
  assert.equal(await response.text(), '');
});

// contract-test: tooling
test('rejects a declared oversized body before consumption', async (t) => {
  const { fetch } = await fixture(t, (_request, response) => {
    response.writeHead(200, { 'content-type': 'application/json', 'content-length': '1000' });
    response.flushHeaders();
  }, { maxBytes: 128 });
  await assert.rejects(fetch(CHAT, forbiddenFetch), /size limit/);
});

// contract-test: tooling
test('rejects an oversized chunked body', async (t) => {
  const { fetch } = await fixture(t, (_request, response) => {
    response.writeHead(200, { 'content-type': 'application/json' });
    response.write('x'.repeat(129));
    response.end();
  }, { maxBytes: 128 });
  await assert.rejects(fetch(CHAT, forbiddenFetch), /size limit/);
});

// contract-test: tooling
test('rejects HTML metadata instead of treating a fallback document as JSON', async (t) => {
  const { fetch } = await fixture(t, (_request, response) => {
    response.writeHead(200, { 'content-type': 'text/html' }); response.end('<html>Fallback</html>');
  });
  await assert.rejects(fetch(CHAT, forbiddenFetch), /must be JSON/);
});

// contract-test: tooling
test('enforces an absolute response deadline and closes the connection', async (t) => {
  const { fetch } = await fixture(t, () => {}, { timeoutMs: 30 });
  await assert.rejects(fetch(CHAT, forbiddenFetch), /deadline exceeded/);
});

// contract-test: tooling
test('honors cancellation without falling back to an unsafe fetch', async (t) => {
  const { fetch } = await fixture(t, () => {});
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(fetch(CHAT, forbiddenFetch, { signal: controller.signal }), /request failed/);
});

// contract-test: tooling
test('rejects an interrupted response and closes its upstream connection', async (t) => {
  let closed;
  const connectionClosed = new Promise((resolve) => { closed = resolve; });
  const { fetch } = await fixture(t, (request, response) => {
    request.socket.once('close', closed);
    response.writeHead(200, { 'content-type': 'application/json', 'content-length': '100' });
    response.write('{"title":', () => setImmediate(() => response.destroy()));
  });
  await assert.rejects(fetch(CHAT, forbiddenFetch), /(?:request failed|response failed|response was interrupted)/);
  await connectionClosed;
});
