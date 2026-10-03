/* eslint-disable @typescript-eslint/no-require-imports */
export {};
const { test, expect } = require('./helpers/cookie-audit');
const { runCli } = require('./helpers/cli-test-helpers');
const { mkdtempSync, existsSync, readFileSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const path = require('node:path');

// contract-test: supporting surface=cli assertions=pii.surface.semantic-parity,pii.message.owner-local-reveal
test('optional offline anonymization controls never download or activate in headless startup', async () => {
  const directory = mkdtempSync(path.join(tmpdir(), 'cli-privacy-e2e-'));
  const env = { OPENMATES_STATE_DIR: path.join(directory, 'state'), OPENMATES_PRIVACY_DIR: path.join(directory, 'model') };
  const run = (args: string[]) => runCli('http://localhost:8000', ['privacy', ...args], 30_000, { useApiKey: false, record: false, env });
  try {
    const initial = await run(['status', '--json']);
    expect(initial.code).toBe(0);
    expect(JSON.parse(initial.stdout)).toMatchObject({ installed: false, messages: false, documents: false, worker: 'stopped' });
    expect(existsSync(env.OPENMATES_PRIVACY_DIR)).toBe(false);
    const unacknowledged = await run(['install']);
    expect(unacknowledged.code).not.toBe(0);
    expect(unacknowledged.stderr).toContain('--yes');
    expect(existsSync(env.OPENMATES_PRIVACY_DIR)).toBe(false);
    const enable = await run(['enable']);
    expect(enable.code).not.toBe(0);
    expect(existsSync(env.OPENMATES_PRIVACY_DIR)).toBe(false);
    expect((await run(['disable', '--documents'])).code).toBe(0);
    const p = JSON.parse(readFileSync(path.join(env.OPENMATES_STATE_DIR, 'privacy-preferences.json'), 'utf8'));
    expect(p).toMatchObject({ enabled: false, documents: false, projects: [] });
    const end = await run(['status', '--json']);
    expect(JSON.parse(end.stdout)).toMatchObject({ installed: false, messages: false, worker: 'stopped' });
  } finally { rmSync(directory, { recursive: true, force: true }); }
});
