/* eslint-disable @typescript-eslint/no-require-imports */
/** Actual chat tool execution against disposable remote and encrypted hosted Projects. */
export {};
const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { spawn } = require('node:child_process');
const { chmodSync, mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { join, resolve } = require('node:path');
const { email, password, otpKey } = getTestAccount();
const ROOT = resolve(__dirname, '../../../..');
const BASE = process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org';
const API = process.env.PLAYWRIGHT_TEST_API_URL || BASE.replace('://app.dev.', '://api.dev.').replace('://app.', '://api.');
let fixtureStateDir: string | null = null;

function run(command: string, args: string[], env = process.env, cwd = ROOT): Promise<string> {
  return new Promise((resolvePromise, reject) => {
    const child = spawn(command, args, { cwd, env, stdio: ['ignore', 'pipe', 'pipe'] });
    let output = '';
    let errors = '';
    child.stdout.on('data', (chunk: Buffer) => { output = `${output}${chunk}`.slice(-32_000); });
    child.stderr.on('data', (chunk: Buffer) => { errors = `${errors}${chunk}`.slice(-8_000); });
    const timer = setTimeout(() => { child.kill('SIGTERM'); reject(new Error('Disposable Project verification timed out')); }, 720_000);
    child.once('error', (error: Error) => { clearTimeout(timer); reject(error); });
    child.once('exit', (code: number) => {
      clearTimeout(timer);
      if (code !== 0) reject(new Error(`Disposable Project verification failed (${code}): ${errors}\n${output}`));
      else resolvePromise(output);
    });
  });
}

test.describe.serial('CLI Project file chat execution', () => {
  test.beforeAll(async () => {
    test.setTimeout(300_000);
    if (process.env.CI || process.env.GITHUB_ACTIONS || process.env.OPENMATES_CI_ISOLATED === '1') {
      throw new Error('CLI Project real-inference verification is dev-only and must be run directly against the dev server, never in CI.');
    }
    if (!email || !password || !otpKey) {
      throw new Error('CLI Project real-inference verification requires the isolated OPENMATES_TEST_ACCOUNT_* email, password, and OTP key.');
    }
    fixtureStateDir = mkdtempSync(join(tmpdir(), 'openmates-project-chat-state-'));
    chmodSync(fixtureStateDir, 0o700);
    const fixtureEnvironment = { ...process.env, OPENMATES_STATE_DIR: fixtureStateDir };
    await run('npm', ['run', 'build'], process.env, resolve(ROOT, 'frontend/packages/openmates-cli'));
    await run('node', ['scripts/openmates_cli_test_account.mjs', 'login', '--api-url', API], {
      ...fixtureEnvironment, OPENMATES_TEST_ACCOUNT_EMAIL: email, OPENMATES_TEST_ACCOUNT_PASSWORD: password,
      OPENMATES_TEST_ACCOUNT_OTP_KEY: otpKey, OPENMATES_TEST_ACCOUNT_SOURCE_SLOT: '',
    });
  });

  test.afterAll(() => {
    if (fixtureStateDir) rmSync(fixtureStateDir, { recursive: true, force: true });
    fixtureStateDir = null;
  });

  // contract-test: direct surface=cli assertions=projects.files.hosted-ciphertext-commit,projects.files.expected-base,projects.files.exact-patch,projects.files.chat-focus-required
  test('creates, reads and patches remote and client-encrypted hosted files through a real chat', async () => {
    test.setTimeout(900_000);
    if (!fixtureStateDir) throw new Error('Private CLI fixture state was not initialized');
    const output = await run('node', ['--experimental-strip-types', '--loader', './frontend/packages/openmates-cli/tests/loader.mjs', 'scripts/project_remote_access_live.mjs', 'chat-files', API], {
      ...process.env, OPENMATES_STATE_DIR: fixtureStateDir,
      OPENMATES_REMOTE_HOST_SESSION: join(fixtureStateDir, 'session.json'),
    });
    const events = output.split('\n').flatMap((line: string) => { try { return [JSON.parse(line)]; } catch { return []; } });
    expect(events.filter((event: any) => event.event === 'chat_file_verified').map((event: any) => event.kind).sort()).toEqual(['hosted', 'remote']);
    expect(events.some((event: any) => event.success === true && event.mode === 'chat-files')).toBe(true);
  });

  // contract-test: direct surface=cli assertions=code-run.remote.confinement,code-run.remote.explicit-approval,code-run.remote.command-lists,code-run.remote.managed-jobs,code-run.output.external-text-guard,code-run.execution.wait-or-continue
  test('runs one exact reviewed command in the disposable remote Project and returns checked terminal output', async () => {
    test.setTimeout(600_000);
    if (!fixtureStateDir) throw new Error('Private CLI fixture state was not initialized');
    const output = await run('node', ['--experimental-strip-types', '--loader', './frontend/packages/openmates-cli/tests/loader.mjs', 'scripts/project_remote_access_live.mjs', 'chat-command', API], {
      ...process.env, OPENMATES_STATE_DIR: fixtureStateDir,
      OPENMATES_REMOTE_HOST_SESSION: join(fixtureStateDir, 'session.json'),
    });
    const events = output.split('\n').flatMap((line: string) => { try { return [JSON.parse(line)]; } catch { return []; } });
    expect(events).toContainEqual(expect.objectContaining({
      event: 'chat_command_verified', review_count: 1, terminal_checked_completion: true, marker_observed: true,
    }));
    expect(events.some((event: any) => event.success === true && event.mode === 'chat-command')).toBe(true);
  });
});
