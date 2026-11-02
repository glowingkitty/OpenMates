/** Actual NAPI client against the shared test-only loopback recovery peer. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
const { SessionClient, SessionClientError } = await import('../../../frontend/packages/openmates-cli/dist/sdk-entry.js');
const CAPABILITY = 'session.recovery-replay.v1';
const ROOT = fileURLToPath(new URL('../../../', import.meta.url));
function session(suite, endpoint) {
  return { api_url: endpoint, session_id: suite.account.session_id, cookies: { auth_refresh_token: suite.account.cookie }, ws_token: null, master_key: suite.account.master_key, hashed_email: 'synthetic-email-hash', user_email_salt: 'synthetic-salt', email_encryption_key: null, created_at: 1, paired_session_expires_at: null, active_team_id: null };
}
function construct(suite, endpoint) { return new SessionClient({ apiUrl: endpoint, appUrl: suite.protocol.app_origin, privacy: { enhanced: false }, allowPrivateOperations: true }); }
async function status(endpoint) { const response = await fetch(endpoint + '/__test/status'); assert.equal(response.status, 200); return await response.json(); }
async function cancelOnClaim(client, endpoint) {
  for (let i = 0; i < 500; i++) { if ((await status(endpoint)).claims === 1) { client.cancel(); return; } await new Promise(resolve => setTimeout(resolve, 10)); }
  throw new Error('test lease claim timeout');
}
export async function runRecovery(suite, vector, fixturePath) {
  // Fixture service only. The public SessionClient never launches any process.
  const peer = spawn(process.env.OPENMATES_SDK_CONFORMANCE_PYTHON ?? 'python3', ['tests/sdk-conformance/recovery_server.py', '--fixture', fixturePath, '--vector', vector.id, '--identity', 'npm'], { cwd: ROOT, stdio: ['ignore', 'pipe', 'ignore'] });
  const lines = createInterface({ input: peer.stdout });
  let client; const seen = new Set(); let cancel;
  try {
    const ready = await Promise.race([new Promise((resolve, reject) => { lines.once('line', line => { try { resolve(JSON.parse(line)); } catch { reject(new Error('fixture readiness failed')); } }); peer.once('error', () => reject(new Error('fixture service unavailable'))); peer.once('exit', () => reject(new Error('fixture service exited'))); }), new Promise((_, reject) => setTimeout(() => reject(new Error('fixture service startup timeout')), 10000).unref())]);
    const endpoint = ready.endpoint; assert.match(endpoint, /^http:\/\/127\.0\.0\.1:\d+$/);
    client = construct(suite, endpoint);
    await client.importSession(session(suite, endpoint));
    let errorCode = null, completed = null;
    try {
      if (vector.mode === 'bad_digest') await client.list('chats');
      else {
        if (vector.mode === 'cancel') cancel = cancelOnClaim(client, endpoint);
        for await (const event of client.stream(suite.protocol.input)) {
          if (event.type === 'update') { for (const key of Object.keys(event.update)) seen.add(key); }
          if (event.type === 'completed') completed = event.chat;
        }
      }
    } catch (error) { assert.ok(error instanceof SessionClientError); errorCode = error.code; assert.ok(!error.message.includes('synthetic-private-server-diagnostic')); }
    if (cancel) await cancel;
    assert.equal(errorCode, vector.error);
    if (vector.error) { assert.equal(completed, null); assert.ok(!seen.has('Completed')); }
    else { const answer = vector.mode === 'terminal' ? suite.protocol.canonical_content : suite.protocol.sealed_content; assert.equal(completed.messages.at(-1).content, answer); assert.notEqual(answer, suite.protocol.transient_content); assert.ok(seen.has('Completed')); }
    if (vector.reconnect) {
      const exported = await client.exportSession({ includeSecrets: true }); await client.close();
      client = construct(suite, endpoint); await client.importSession(exported.session);
      const rows = await client.list('chats'); assert.equal(rows.length, 1);
      const chat = await client.openChat(rows[0].id); assert.equal(chat.messages.at(-1).content, suite.protocol.sealed_content);
    }
    await client.close();
    // Observe fixture close cleanup before evaluating negative no-persist assertions.
    let report; for (let i = 0; i < 100; i++) { report = await status(endpoint); if (report.checks.includes('socket-closed')) break; await new Promise(resolve => setTimeout(resolve, 10)); }
    assert.equal(report.failure, null); assert.equal(report.persists, vector.expected_persists);
    assert.equal(report.admissions, vector.mode === 'bad_digest' ? 0 : 1); assert.equal(report.claims, vector.mode === 'bad_digest' ? 0 : 1);
    assert.equal(report.connections, vector.reconnect ? 2 : 1);
    for (const check of vector.required_checks) assert.ok(report.checks.includes(check), `missing check ${check}`);
    return { id: vector.id, status: 'passed' };
  } finally {
    try { await client?.close(); }
    finally { lines.close(); if (peer.pid && peer.exitCode === null && peer.signalCode === null) { const stopped = new Promise(resolve => peer.once('exit', resolve)); peer.kill('SIGTERM'); await stopped; } }
  }
}
async function main() {
  const args = process.argv.slice(2), option = name => args[args.indexOf(name) + 1]; assert.equal(option('--capability'), CAPABILITY);
  const fixturePath = option('--fixture'), raw = readFileSync(fixturePath), suite = JSON.parse(raw).capabilities[CAPABILITY];
  const results = []; for (const vector of suite.vectors) results.push(await runRecovery(suite, vector, fixturePath));
  assert.ok(results.length); console.log(JSON.stringify({ capability: CAPABILITY, language: 'npm', status: 'passed', fixtureSha256: createHash('sha256').update(raw).digest('hex'), results }));
}
main().catch(() => { console.error('npm recovery protocol conformance failed'); process.exitCode = 1; });
