/** Real npm direct client/facade and in-memory fetch IO; no profiles/network. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
// argument-parser-start
function parseArguments(args) {
  const names = new Map([['--root', 'root'], ['--fixture', 'fixture'], ['--capability', 'capability']]);
  const parsed = {};
  for (let index = 0; index < args.length; index += 2) {
    const name = args[index];
    const field = names.get(name);
    assert.ok(field, 'Unknown adapter argument');
    assert.ok(!Object.hasOwn(parsed, field), 'Duplicate adapter argument');
    const value = args[index + 1];
    assert.ok(value && !value.startsWith('--'), 'Missing adapter argument value');
    parsed[field] = value;
  }
  assert.ok(parsed.fixture, 'Supply --fixture');
  assert.equal(parsed.capability, 'sdk.drafts');
  return parsed;
}
// argument-parser-end
const parsed = parseArguments(process.argv.slice(2));
const root = resolve(parsed.root ?? new URL('../../..', import.meta.url).pathname);
const { OpenMates, OpenMatesApiError, OpenMatesConfigError } = await import(pathToFileURL(resolve(root, 'frontend/packages/openmates-cli/dist/sdk-entry.js')));
const bytes = readFileSync(parsed.fixture);
const capability = parsed.capability;
const fixture = JSON.parse(bytes).capabilities[capability];
const results = [];
const originalFetch = globalThis.fetch;
function client(options = {}) {
  return new OpenMates({ apiUrl: 'https://api.example.invalid', deviceId: 'synthetic-device', apiKey: fixture.credential, ...options });
}
function io(raw = null, { session = fixture.session, status = 200, empty = false } = {}) {
  const calls = [];
  return { calls, fetch: async (url, options) => {
    const { pathname, origin } = new URL(url);
    calls.push({ path: pathname, options });
    assert.equal(origin, 'https://api.example.invalid');
    assert.equal(options.headers.Authorization, 'Bearer sk-api-synthetic');
    assert.ok(!JSON.stringify(options).includes('.synthetic'));
    if (options.method === 'POST') {
      assert.equal(pathname, '/v1/sdk/session');
      return Response.json(session);
    }
    assert.equal(options.method, 'GET');
    assert.ok(pathname.startsWith('/v1/sdk/drafts'));
    if (status !== 200) return Response.json({ detail: 'synthetic-error' }, { status });
    return Response.json(pathname === '/v1/sdk/drafts' ? { drafts: empty ? [] : [raw] } : { draft: raw && pathname.endsWith('/' + raw.chat_id) ? raw : null });
  } };
}
async function runIO(peer, run) {
  globalThis.fetch = peer.fetch;
  try { return await run(); } finally { globalThis.fetch = originalFetch; }
}
try {
  for (const vector of fixture.vectors.filter(v => v.kind === 'record')) {
    const raw = vector.draft;
    const peer = io(raw);
    const c = client();
    const normalized = { chatId: raw.chat_id, encryptedDraftMd: raw.encrypted_draft_md, encryptedDraftPreview: raw.encrypted_draft_preview, draftV: raw.draft_v };
    await runIO(peer, async () => {
      assert.deepEqual(await c.drafts.listEncrypted(), [normalized]);
      assert.deepEqual(await c.drafts.getEncrypted(raw.chat_id), normalized);
      assert.equal(peer.calls.filter(x => x.options.method === 'POST').length, 0);
      for (const decoded of [(await c.drafts.list())[0], await c.drafts.get(raw.chat_id)]) {
        assert.deepEqual(decoded, { ...normalized, markdown: vector.markdown, preview: vector.preview });
      }
      assert.equal(peer.calls.filter(x => x.options.method === 'POST').length, 1);
      assert.equal(await c.drafts.get('missing'), null);
      assert.equal('create' in c.drafts, false); assert.equal('clear' in c.drafts, false);
    });
    results.push({ id: vector.id, status: 'passed' });
  }
  const raw = fixture.vectors[0].draft;
  for (const [id, session] of [['wrong-account-key', fixture.wrong_account_session], ['project-grant-not-account-key', fixture.project_grant_session]]) {
    const c = client();
    await runIO(io(raw, { session }), () => assert.rejects(() => c.drafts.get(raw.chat_id), OpenMatesConfigError));
    results.push({ id, status: 'passed' });
  }
  const broken = { ...raw, encrypted_draft_md: 'not-authenticated' };
  const c = client();
  await runIO(io(broken), () => assert.rejects(() => c.drafts.get(raw.chat_id), OpenMatesConfigError));
  results.push({ id: 'corrupt-markdown', status: 'passed' });
  for (const empty of [false, true]) {
    const peer = io(null, { empty }); const c = client();
    const observed = await runIO(peer, () => empty ? c.drafts.list() : c.drafts.get('missing'));
    assert.deepEqual(observed, empty ? [] : null);
    assert.equal(peer.calls.length, 1); assert.equal(peer.calls[0].options.method, 'GET');
    results.push({ id: empty ? 'empty-list-no-key-unwrap' : 'get-missing-no-key-unwrap', status: 'passed' });
  }
  const peer = io(raw);
  const anonymous = client({ apiKey: undefined, anonymous: true, anonymousId: 'synthetic-anonymous' });
  await runIO(peer, () => assert.rejects(() => anonymous.drafts.get(raw.chat_id), OpenMatesConfigError));
  assert.equal(peer.calls.length, 0);
  results.push({ id: 'anonymous-refused-no-request', status: 'passed' });
  for (const test of fixture.error_cases) {
    const peer = io(raw, { status: test.status }); const c = client();
    await runIO(peer, () => assert.rejects(() => c.drafts.get(raw.chat_id), error => error instanceof OpenMatesApiError && error.status === test.status));
    assert.equal(peer.calls.length, 1);
    results.push({ id: test.id, status: 'passed' });
  }
  const limits = [];
  for (const limit of fixture.open_parity_limits) {
    const c = client();
    const decoded = await runIO(io(limit.draft), () => c.drafts.get(limit.draft.chat_id));
    assert.deepEqual(Array.from({ length: decoded.preview.length }, (_, i) => decoded.preview.charCodeAt(i)), limit.npm_preview_utf16);
    limits.push({ id: limit.id, status: 'open-existing-sdk-divergence', observed: 'legacy UTF16 slice ends in lone surrogate' });
  }
  assert.deepEqual(results.map(v => v.id).sort(), fixture.vectors.map(v => v.id).sort());
  console.log(JSON.stringify({ capability, language: 'npm', status: 'passed', fixtureSha256: createHash('sha256').update(bytes).digest('hex'), results, openParityLimits: limits }));
} finally { globalThis.fetch = originalFetch; }
