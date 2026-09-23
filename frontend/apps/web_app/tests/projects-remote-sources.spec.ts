/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { spawn, spawnSync } = require('node:child_process');
const { chmodSync, mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { join, resolve } = require('node:path');
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

function projectHashUrlPattern(projectId: string): RegExp {
  return new RegExp(`/projects#(?:[^#]*&)?project-id=${projectId}(?:&|$)`);
}

function runChecked(command: string, args: string[], cwd = REPO_ROOT, env = process.env): void {
  const result = spawnSync(command, args, { cwd, env, encoding: 'utf-8' });
  if (result.status !== 0) {
    throw new Error(`${command} ${args.join(' ')} failed:\n${result.stdout}\n${result.stderr}`);
  }
}

interface RemoteFixtureEvent {
  event: string;
  project_id: string;
  project_name: string;
  path_privacy_verified?: boolean;
  [key: string]: string | boolean | undefined;
}

const MAX_FIXTURE_DIAGNOSTIC_CHARS = 8_000;

function appendFixtureDiagnostic(current: string, chunk: unknown): string {
  const next = `${current}${String(chunk)}`;
  return next.length > MAX_FIXTURE_DIAGNOSTIC_CHARS
    ? next.slice(-MAX_FIXTURE_DIAGNOSTIC_CHARS)
    : next;
}

function sanitizeFixtureDiagnostic(value: string): string {
  return value
    // eslint-disable-next-line no-control-regex -- Strip terminal escape sequences from fixture logs.
    .replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, '')
    .replace(/\bBearer\s+\S+/gi, 'Bearer [REDACTED]')
    .replace(/\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/g, '[REDACTED_JWT]')
    .replace(/((?:authorization|cookie|password|secret|token|otp(?:_key)?|encrypted_[a-z_]*key)\s*["']?\s*[:=]\s*["']?)[^\s"',}]+/gi, '$1[REDACTED]')
    .replace(/\b[A-Za-z0-9+/_=-]{80,}\b/g, '[REDACTED_LONG_VALUE]')
    // eslint-disable-next-line no-control-regex -- Remove non-printing bytes from diagnostic output.
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, '')
    .trim();
}

function fixtureDiagnostic(stdout: string, stderr: string): string {
  return [
    `stdout:\n${sanitizeFixtureDiagnostic(stdout) || '(empty)'}`,
    `stderr:\n${sanitizeFixtureDiagnostic(stderr) || '(empty)'}`,
  ].join('\n');
}

function waitForFixtureEvent(processHandle, eventName: string, timeoutMs = 60000): Promise<RemoteFixtureEvent> {
  return new Promise((resolvePromise, reject) => {
    let output = '';
    let errorOutput = '';
    let settled = false;
    const cleanup = () => {
      clearTimeout(timeout);
      processHandle.stdout.off('data', onData);
      processHandle.stderr?.off('data', onErrorData);
      processHandle.off('close', onClose);
    };
    const fail = (message: string) => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(new Error(`${message}\n${fixtureDiagnostic(output, errorOutput)}`));
    };
    const onData = (chunk) => {
      output = appendFixtureDiagnostic(output, chunk);
      for (const line of output.split('\n')) {
        try {
          const payload = JSON.parse(line);
          if (payload.event !== eventName) continue;
          if (settled) return;
          settled = true;
          cleanup();
          resolvePromise(payload);
          return;
        } catch {
          // Ignore CLI status text and incomplete JSON lines.
        }
      }
    };
    const onErrorData = (chunk) => {
      errorOutput = appendFixtureDiagnostic(errorOutput, chunk);
    };
    const onClose = (code, signal) => {
      fail(`Remote fixture exited before ${eventName} (code=${code ?? 'null'}, signal=${signal ?? 'none'})`);
    };
    const timeout = setTimeout(() => fail(`Timed out waiting for ${eventName}`), timeoutMs);
    processHandle.stdout.on('data', onData);
    processHandle.stderr?.on('data', onErrorData);
    processHandle.once('close', onClose);
  });
}

test.describe('Projects remote sources', () => {
  test.beforeEach(async ({ page }) => {
    skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
    await skipIfFeaturesDisabled(test, page, ['platform:projects']);
    await loginToTestAccount(page);
  });

  // contract-test: supporting surface=gui.web assertions=projects.access.explicit-context,projects.files.no-server-decryption-authority,projects.surface.semantic-parity,projects.uploads.project-wrapped,projects.items.responsive-embeds,projects.files.ignored-exact-inclusion,projects.files.private-path-deny
  test('browses nested connected files transiently and imports only after an explicit action', async ({ page }, testInfo) => {
    test.setTimeout(240000);
    const fixtureStateDir = mkdtempSync(join(tmpdir(), 'openmates-browser-project-source-'));
    chmodSync(fixtureStateDir, 0o700);
    const fixtureEnvironment = { ...process.env, OPENMATES_STATE_DIR: fixtureStateDir };
    let bridge = null;
    let fixture: RemoteFixtureEvent | null = null;
    const persistenceRequests: string[] = [];
    page.on('request', (request) => {
      if (request.method() === 'POST' && /\/(?:upload-embed|embeds)(?:\/|\?|$)|\/projects\/[^/]+\/items(?:\?|$)/.test(request.url())) {
        persistenceRequests.push(new URL(request.url()).pathname);
      }
    });
    try {
      runChecked('npm', ['--prefix', CLI_DIR, 'run', 'build']);
      runChecked(
        'node',
        ['scripts/openmates_cli_test_account.mjs', 'login', '--api-url', API_BASE_URL, '--web-origin', new URL(BASE_URL).origin],
        REPO_ROOT,
        {
          ...fixtureEnvironment,
          OPENMATES_TEST_ACCOUNT_EMAIL: TEST_EMAIL,
          OPENMATES_TEST_ACCOUNT_PASSWORD: TEST_PASSWORD,
          OPENMATES_TEST_ACCOUNT_OTP_KEY: TEST_OTP_KEY,
          OPENMATES_TEST_ACCOUNT_SOURCE_SLOT: '',
        },
      );
      bridge = spawn(
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
          env: { ...fixtureEnvironment, OPENMATES_REMOTE_HOST_SESSION: join(fixtureStateDir, 'session.json') },
          stdio: ['ignore', 'pipe', 'pipe'],
        },
      );
      fixture = await waitForFixtureEvent(bridge, 'fixture_ready');
      expect(fixture.path_privacy_verified).toBe(true);
      await page.goto('/projects');
      const connectedProject = page.getByTestId('project-landing-card').filter({ hasText: fixture.project_name });
      await expect(connectedProject).toBeVisible({ timeout: 30000 });
      await connectedProject.click();
      await expect(page).toHaveURL(projectHashUrlPattern(fixture.project_id));
      await expect(page.getByTestId('projects-page')).toBeVisible({ timeout: 30000 });
      const sourceCard = page.getByTestId('project-remote-source-card').filter({ hasText: 'Live remote source' });
      await expect(sourceCard).toBeVisible({ timeout: 30000 });
      await expect(sourceCard).toContainText('connected');
      await expect(page.getByTestId('project-item-card')).toHaveCount(0);

      await page.getByTestId('project-connected-source-root').filter({ hasText: 'Live remote source' }).click();
      const directoryResults = sourceCard.getByTestId('project-remote-directory-results');
      await expect(directoryResults).toBeVisible({ timeout: 30000 });
      await expect(directoryResults.getByTestId('project-remote-entry').filter({ hasText: /debug\.log|other\.log|customer-export|^private$/ })).toHaveCount(0);
      await directoryResults.getByTestId('project-remote-entry').filter({ hasText: 'src' }).click();
      await expect(sourceCard.getByTestId('project-remote-entry').filter({ hasText: 'remote-demo.ts' })).toBeVisible();

      await sourceCard.getByTestId('project-remote-entry').filter({ hasText: /\blib\b/ }).click();
      await sourceCard.getByTestId('project-remote-entry').filter({ hasText: /\bdeep\b/ }).click();
      const largeFile = sourceCard.getByTestId('project-remote-preview-card').filter({ hasText: 'large-demo.ts' });
      await expect(largeFile).toBeVisible();
      await testInfo.attach('connected-project-nested-files', { body: await sourceCard.screenshot(), contentType: 'image/png' });
      await largeFile.getByTestId('project-remote-preview-open').click();
      const fullscreenOverlay = page.getByTestId('project-remote-fullscreen-overlay');
      await expect(fullscreenOverlay).toBeVisible({ timeout: 30000 });
      await expect(fullscreenOverlay).toContainText('Remote fullscreen end marker');
      await closeFullscreen(page, fullscreenOverlay);
      await expect(fullscreenOverlay).toHaveCount(0);
      await expect(page.getByTestId('project-item-card')).toHaveCount(0);
      expect(persistenceRequests).toEqual([]);

      // Search from the source root after exercising multiple nested directories.
      await sourceCard.getByTestId('project-remote-source-browse').click();

      await sourceCard.getByTestId('project-remote-search-input').fill('remoteDemo');
      await sourceCard.getByTestId('project-remote-search-submit').click();
      const searchResults = sourceCard.getByTestId('project-remote-search-results');
      await expect(searchResults).toContainText('remote-demo.ts', { timeout: 30000 });
      await expect(searchResults).not.toContainText('PRIVATE_DUMMY_CANARY');
      await expect(searchResults).not.toContainText('debug.log');
      await searchResults.getByRole('button', { name: /remote-demo\.ts/i }).click();

      await expect(fullscreenOverlay).toBeVisible({ timeout: 30000 });
      await expect(fullscreenOverlay).toContainText('OpenMates live remote preview');
      await closeFullscreen(page, fullscreenOverlay);
      await expect(page.getByTestId('project-item-card')).toHaveCount(0);
      expect(persistenceRequests).toEqual([]);

      // Reload must reconstruct source metadata, not a durable copy of any previewed file.
      await page.reload();
      await expect(sourceCard).toBeVisible({ timeout: 30000 });
      await expect(page.getByTestId('project-item-card')).toHaveCount(0);
      await expect(page.getByTestId('project-remote-fullscreen-overlay')).toHaveCount(0);
      expect(persistenceRequests).toEqual([]);

      // Preserve the existing deliberate import behavior after proving viewing is transient.
      await sourceCard.getByTestId('project-remote-source-browse').click();
      await sourceCard.getByTestId('project-remote-entry').filter({ hasText: /\bsrc\b/ }).click();
      await sourceCard.getByTestId('project-remote-preview-card').filter({ hasText: 'remote-demo.ts' }).getByTestId('project-remote-preview-open').click();
      await expect(fullscreenOverlay).toBeVisible({ timeout: 30000 });
      await closeFullscreen(page, fullscreenOverlay);
      const remotePreview = page.getByTestId('project-remote-preview-card').filter({ hasText: 'remote-demo.ts' }).first();
      await remotePreview.getByTestId('project-remote-preview-upload').click();
      const importedFile = page.getByTestId('project-item-card').filter({ hasText: 'remote-demo.ts' }).first();
      await expect(importedFile).toBeVisible({ timeout: 30000 });
      await page.getByRole('button', { name: 'List', exact: true }).click();
      await expect(importedFile).toHaveAttribute('aria-disabled', 'false');
      await importedFile.click();
      const storedFullscreen = page.getByTestId('embed-fullscreen-overlay');
      await expect(storedFullscreen).toBeVisible({ timeout: 30000 });
      await expect(storedFullscreen).toContainText('OpenMates live remote preview');
      await closeFullscreen(page, storedFullscreen);
      await importedFile.press('Enter');
      await expect(storedFullscreen).toBeVisible();
      await closeFullscreen(page, storedFullscreen);

      const stopped = waitForFixtureEvent(bridge, 'bridge_stopped');
      bridge.kill('SIGUSR1');
      await stopped;
      await expect(sourceCard).toContainText('offline', { timeout: 30000 });
      await expect(sourceCard.getByTestId('project-remote-source-browse')).toBeDisabled();
    } finally {
      if (bridge && bridge.exitCode === null) {
        bridge.kill('SIGTERM');
        await new Promise((resolvePromise) => bridge.once('exit', resolvePromise));
      }
      rmSync(fixtureStateDir, { recursive: true, force: true });
    }
  });
});
