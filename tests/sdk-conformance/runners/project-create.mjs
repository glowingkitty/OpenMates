/** Direct npm SDK creation through the shared synthetic HTTP peer. */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
const { OpenMates, OpenMatesConfigError } = await import('../../../frontend/packages/openmates-cli/dist/sdk-entry.js');
const ROOT = fileURLToPath(new URL('../../../', import.meta.url)), CAPABILITY = 'protocol.project-create.v1';
async function runVector(suite, vector, fixturePath) {
  const peer = spawn(process.env.OPENMATES_SDK_CONFORMANCE_PYTHON ?? 'python3', ['tests/sdk-conformance/project_create_server.py', '--fixture', fixturePath, '--vector', vector.id, '--identity', 'npm'], { cwd: ROOT, stdio: ['ignore', 'pipe', 'ignore'] });
  const lines = createInterface({ input: peer.stdout });
  try {
    const ready = await Promise.race([new Promise((resolve, reject) => { lines.once('line', line => { try { resolve(JSON.parse(line)); } catch { reject(new Error('fixture readiness')); } }); peer.once('error', () => reject(new Error('fixture unavailable'))); peer.once('exit', () => reject(new Error('fixture exited'))); }), new Promise((_, reject) => setTimeout(() => reject(new Error('fixture startup timeout')), 10000).unref())]);
    assert.match(ready.endpoint, /^http:\/\/127\.0\.0\.1:\d+$/);
    const client = new OpenMates({ apiUrl: ready.endpoint, apiKey: suite.account.api_key, deviceId: 'synthetic-project-fixture' });
    for (let i = 0; i < vector.repetitions; i++) {
      const operation = () => client.projects.create(vector.input, vector.team ? { teamId: suite.team.team_id } : { personal: true });
      if (vector.error) await assert.rejects(operation, error => error instanceof OpenMatesConfigError);
      else { const output = await operation(); for (const [key, value] of Object.entries(vector.expected)) assert.equal(output[key], value); assert.match(output.projectId, /^[0-9a-f-]{36}$/); }
    }
    const response = await fetch(ready.endpoint + '/__test/status'); assert.equal(response.status, 200); const report = await response.json();
    assert.equal(report.failure, null); assert.equal(report.posts, vector.error ? 0 : vector.repetitions);
    assert.ok(report.checks.includes('bearer-only-transport'));
    if (!vector.error) for (const check of ['backend-required-fields', 'fresh-project-key-and-focus', 'canonical-encrypted-default-focus', 'encrypted-private-fields', 'scope-bound-key-wrapper', 'secret-free-wire', 'safe-write-policy']) assert.ok(report.checks.includes(check));
    return { id: vector.id, status: 'passed' };
  } finally { lines.close(); if (peer.pid && peer.exitCode === null && peer.signalCode === null) { const stopped = new Promise(resolve => peer.once('exit', resolve)); peer.kill('SIGTERM'); await stopped; } }
}
async function main() {
  const args = process.argv.slice(2), option = name => args[args.indexOf(name) + 1]; assert.equal(option('--capability'), CAPABILITY);
  const fixturePath = option('--fixture'), raw = readFileSync(fixturePath), suite = JSON.parse(raw).capabilities[CAPABILITY];
  const results = []; for (const vector of suite.vectors) results.push(await runVector(suite, vector, fixturePath));
  assert.ok(results.length); console.log(JSON.stringify({ capability: CAPABILITY, language: 'npm', status: 'passed', fixtureSha256: createHash('sha256').update(raw).digest('hex'), results }));
}
main().catch(() => { console.error('npm Project creation conformance failed'); process.exitCode = 1; });
