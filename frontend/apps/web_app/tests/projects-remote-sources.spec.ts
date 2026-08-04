/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { spawn, spawnSync } = require('node:child_process');
const { homedir } = require('node:os');
const { resolve } = require('node:path');
const { test, expect } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { closeFullscreen } = require('./helpers/embed-test-helpers');
const { skipIfFeaturesDisabled, skipWithoutCredentials } = require('./helpers/env-guard');
const { getTestAccount } = require('./signup-flow-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org';
const API_BASE_URL = process.env.PLAYWRIGHT_TEST_API_URL || BASE_URL.replace('://app.dev.', '://api.dev.').replace('://app.', '://api.');
const REPO_ROOT = resolve(__dirname, '../../../..');
const CLI_DIR = resolve(REPO_ROOT, 'frontend/packages/openmates-cli');
const CLI_SESSION_PATH = resolve(homedir(), '.openmates/session.json');

function projectHashUrlPattern(projectId: string): RegExp {
  return new RegExp(`/projects#(?:[^#]*&)?project-id=${projectId}(?:&|$)`);
}

function runChecked(command: string, args: string[], cwd = REPO_ROOT, env = process.env): void {
  const result = spawnSync(command, args, { cwd, env, encoding: 'utf-8' });
  if (result.status !== 0) {
    throw new Error(`${command} ${args.join(' ')} failed:\n${result.stdout}\n${result.stderr}`);
  }
}

function waitForFixtureEvent(processHandle, eventName: string, timeoutMs = 60000): Promise<Record<string, string>> {
  return new Promise((resolvePromise, reject) => {
    let output = '';
    const timeout = setTimeout(() => reject(new Error(`Timed out waiting for ${eventName}: ${output}`)), timeoutMs);
    const onData = (chunk) => {
      output += chunk.toString();
      for (const line of output.split('\n')) {
        try {
          const payload = JSON.parse(line);
          if (payload.event !== eventName) continue;
          clearTimeout(timeout);
          processHandle.stdout.off('data', onData);
          resolvePromise(payload);
          return;
        } catch {
          // Ignore CLI status text and incomplete JSON lines.
        }
      }
    };
    processHandle.stdout.on('data', onData);
    processHandle.once('exit', (code) => {
      clearTimeout(timeout);
      reject(new Error(`Remote fixture exited before ${eventName} (${code}): ${output}`));
    });
  });
}

test.describe('Projects remote sources', () => {
  test.beforeEach(async ({ page }) => {
    skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
    await skipIfFeaturesDisabled(test, page, ['platform:projects']);
    await loginToTestAccount(page);
  });

  test('browses a real foreground CLI source and observes offline state', async ({ page }) => {
    test.setTimeout(240000);
    runChecked('npm', ['run', 'build'], CLI_DIR);
    runChecked(
      'node',
      ['scripts/openmates_cli_test_account.mjs', 'login', '--api-url', API_BASE_URL],
      REPO_ROOT,
      {
        ...process.env,
        OPENMATES_TEST_ACCOUNT_EMAIL: TEST_EMAIL,
        OPENMATES_TEST_ACCOUNT_PASSWORD: TEST_PASSWORD,
        OPENMATES_TEST_ACCOUNT_OTP_KEY: TEST_OTP_KEY,
        OPENMATES_TEST_ACCOUNT_SOURCE_SLOT: '',
      },
    );
    const bridge = spawn(
      'node',
      [
        '--experimental-strip-types',
        '--loader',
        './frontend/packages/openmates-cli/tests/loader.mjs',
        'scripts/project_remote_access_live.mjs',
        'serve',
        API_BASE_URL,
      ],
      {
        cwd: REPO_ROOT,
        env: { ...process.env, OPENMATES_REMOTE_HOST_SESSION: CLI_SESSION_PATH },
        stdio: ['ignore', 'pipe', 'pipe'],
      },
    );
    let fixture: Record<string, string> | null = null;
    try {
      fixture = await waitForFixtureEvent(bridge, 'fixture_ready');
      await page.goto(`/projects#project-id=${fixture.project_id}`);
      await expect(page).toHaveURL(projectHashUrlPattern(fixture.project_id));
      await expect(page.getByTestId('projects-page')).toBeVisible({ timeout: 30000 });
      const sourceCard = page.getByTestId('project-remote-source-card').filter({ hasText: 'Live remote source' });
      await expect(sourceCard).toBeVisible({ timeout: 30000 });
      await expect(sourceCard).toContainText('connected');

      await sourceCard.getByTestId('project-remote-source-browse').click();
      const directoryResults = sourceCard.getByTestId('project-remote-directory-results');
      await expect(directoryResults).toBeVisible({ timeout: 30000 });
      await directoryResults.getByTestId('project-remote-entry').filter({ hasText: 'src' }).click();
      await expect(sourceCard.getByTestId('project-remote-entry').filter({ hasText: 'remote-demo.ts' })).toBeVisible();

      await sourceCard.getByTestId('project-remote-search-input').fill('remoteDemo');
      await sourceCard.getByTestId('project-remote-search-submit').click();
      const searchResults = sourceCard.getByTestId('project-remote-search-results');
      await expect(searchResults).toContainText('remote-demo.ts', { timeout: 30000 });
      await searchResults.getByRole('button', { name: /remote-demo\.ts/i }).click();

      const fullscreenOverlay = page.getByTestId('project-remote-fullscreen-overlay');
      await expect(fullscreenOverlay).toBeVisible({ timeout: 30000 });
      await expect(fullscreenOverlay).toContainText('OpenMates live remote preview');
      await closeFullscreen(page, fullscreenOverlay);
      const remotePreview = page.getByTestId('project-remote-preview-card').filter({ hasText: 'remote-demo.ts' }).first();
      await expect(remotePreview).toBeVisible();
      await remotePreview.getByTestId('project-remote-preview-upload').click();
      await expect(page.getByTestId('project-item-card').filter({ hasText: 'remote-demo.ts' }).first()).toBeVisible({ timeout: 30000 });

      const stopped = waitForFixtureEvent(bridge, 'bridge_stopped');
      bridge.kill('SIGUSR1');
      await stopped;
      await expect(sourceCard).toContainText('offline', { timeout: 30000 });
      await expect(sourceCard.getByTestId('project-remote-source-browse')).toBeDisabled();
    } finally {
      if (bridge.exitCode === null) {
        bridge.kill('SIGTERM');
        await new Promise((resolvePromise) => bridge.once('exit', resolvePromise));
      }
    }
  });
});
