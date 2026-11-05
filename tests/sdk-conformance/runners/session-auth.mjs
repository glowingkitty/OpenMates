/** Positive session auth against in-process transcript mocks; no product calls. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { createServer } from 'node:http';
import { pathToFileURL } from 'node:url';
const { SessionClient, SessionClientError } = await import('../../../frontend/packages/openmates-cli/dist/sdk-entry.js');
const CAPABILITY = 'session.password-totp-rotation.v1';

function match(actual, expected, captures) {
  if (expected && typeof expected === 'object' && '$capture_uuid' in expected) {
    assert.equal(typeof actual, 'string');
    assert.match(actual, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    assert.ok(![...captures.values()].includes(actual), 'each sign-in uses a fresh session ID');
    captures.set(expected.$capture_uuid, actual); return;
  }
  if (expected && typeof expected === 'object' && '$ref' in expected) { assert.equal(actual, captures.get(expected.$ref)); return; }
  if (expected && typeof expected === 'object') {
    assert.deepEqual(Object.keys(actual).sort(), Object.keys(expected).sort());
    for (const key of Object.keys(expected)) match(actual[key], expected[key], captures);
  } else assert.equal(actual, expected);
}

export async function runSessionAuth(vector) {
  let index = 0, failure = null; const captures = new Map();
  const server = createServer(async (request, response) => {
    const step = vector.steps[index];
    try {
      assert.ok(step, 'unexpected request'); assert.equal(request.method, step.method); assert.equal(request.url, step.path);
      assert.equal(request.headers['x-openmates-sdk'], 'npm'); assert.equal(request.headers.origin, vector.app_origin);
      assert.equal(request.headers['x-openmates-expected-principal'] ?? null, step.expected_principal);
      if (step.blocked_effect) { assert.notEqual(step.expected_principal, step.authenticated_principal); assert.equal(step.response.status, 403); }
      assert.equal(request.headers.cookie ?? null, step.cookie); assert.equal(request.headers.authorization, undefined);
      let raw = ''; for await (const chunk of request) { raw += chunk; assert.ok(raw.length < 65536); }
      assert.ok(!raw.includes(vector.account.password) && !raw.includes(vector.account.master_key) && !raw.includes(vector.account.email), 'secret-free auth wire');
      match(JSON.parse(raw), step.body, captures); index++;
      const body = step.response.raw ?? JSON.stringify(step.response.json);
      response.writeHead(step.response.status, { 'content-type': 'application/json', ...Object.fromEntries(step.response.headers), 'content-length': Buffer.byteLength(body) }); response.end(body);
    } catch {
      failure ??= step?.id ?? 'unexpected-request';
      response.writeHead(500, { 'content-type': 'application/json' }); response.end('{"detail":"synthetic protocol mismatch"}');
    }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const endpoint = `http://127.0.0.1:${server.address().port}`;
  const client = new SessionClient({ apiUrl: endpoint, appUrl: vector.app_origin, privacy: { enhanced: false }, allowPrivateOperations: false });
  let revision = 0;
  try {
    for (const action of vector.actions) {
      const operation = async () => {
        if (action.kind === 'login') {
          const user = await client.loginPassword(vector.account.input_email, vector.account.password, action.tfa ?? undefined, ...("stay_logged_in" in action ? [{stayLoggedIn:action.stay_logged_in}] : []));
          assert.equal(user.id, vector.account.owner_id);
        } else if (action.kind === 'validate') await client.validateSession();
        else if (action.kind === 'validate_concurrently') await Promise.all(Array.from({ length: action.count }, () => client.validateSession()));
        else if (action.kind === 'logout') await client.logout();
        else throw new Error('unsupported transcript action');
      };
      if (action.error) await assert.rejects(operation, error => error instanceof SessionClientError && error.code === action.error && !error.message.includes('synthetic-private-server-diagnostic'));
      else await operation();
      if (action.snapshot === null) {
        await assert.rejects(() => client.exportSession({ includeSecrets: true }), error => error instanceof SessionClientError && error.code === 'authentication');
      } else {
        const snapshot = await client.exportSession({ includeSecrets: true });
        assert.ok(snapshot.revision > revision, 'authoritative credential revision advances'); revision = snapshot.revision;
        assert.equal(snapshot.session.api_url, endpoint); assert.equal(snapshot.session.master_key, vector.account.master_key);
        assert.deepEqual(snapshot.session.cookies, { auth_refresh_token: action.snapshot.token });
        assert.equal(snapshot.session.ws_token, action.snapshot.ws_token);
        assert.equal(snapshot.session.hashed_email, vector.account.hashed_email); assert.equal(snapshot.session.email_encryption_key, vector.account.email_key);
      }
    }
    await assert.rejects(() => client.validateSession(), error => error instanceof SessionClientError && error.code === 'authentication');
    assert.equal(failure, null, 'mock transcript assertions'); assert.equal(index, vector.steps.length, 'all expected auth requests were exercised');
    return { id: vector.id, status: 'passed' };
  } finally {
    await client.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
  }
}

async function main() {
  const args = process.argv.slice(2), option = name => args[args.indexOf(name) + 1];
  const capability = option('--capability'); assert.equal(capability, CAPABILITY);
  const bytes = readFileSync(option('--fixture')), suite = JSON.parse(bytes).capabilities[capability];
  const results = []; for (const vector of suite.vectors) results.push(await runSessionAuth(vector)); assert.ok(results.length);
  process.stdout.write(JSON.stringify({ capability, language: 'npm', status: 'passed', fixtureSha256: createHash('sha256').update(bytes).digest('hex'), results }) + '\n');
}
if (process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url) main().catch(() => { process.stderr.write('npm positive session auth conformance failed\n'); process.exitCode = 1; });
