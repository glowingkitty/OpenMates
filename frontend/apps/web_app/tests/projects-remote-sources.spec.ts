/* eslint-disable @typescript-eslint/no-require-imports */
export {};
import type { RemoteFixtureEvent } from './helpers/project-remote-fixture';
const { copyRemoteHostSession, waitForFixtureEvent, stopFixtureProcess } = require('./helpers/project-remote-fixture');

const { spawn, spawnSync } = require('node:child_process');
const { chmodSync, mkdtempSync, readFileSync, rmSync } = require('node:fs');
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
  return new RegExp(`/#(?:[^#]*&)?project-id=${projectId}(?:&|$)`);
}

function runChecked(command: string, args: string[], cwd = REPO_ROOT, env = process.env): void {
  const result = spawnSync(command, args, { cwd, env, encoding: 'utf-8' });
  if (result.status !== 0) {
    throw new Error(`${command} ${args.join(' ')} failed:\n${result.stdout}\n${result.stderr}`);
  }
}

function prepareRemoteHostSession(fixtureStateDir: string, fixtureEnvironment): void {
  if (process.env.GITHUB_ACTIONS === 'true' && process.env.CI_TEST_MODE === 'e2e' && process.env.OPENMATES_STATE_DIR) {
    // Provisioning already performed real v2 signup, crypto and TOTP. Keep the
    // host's refreshed cookies and source store in its own disposable directory.
    copyRemoteHostSession(process.env.OPENMATES_STATE_DIR, fixtureStateDir);
    return;
  }
  runChecked('node', ['scripts/openmates_cli_test_account.mjs', 'login', '--api-url', API_BASE_URL,
    '--web-origin', new URL(BASE_URL).origin], REPO_ROOT, {
    ...fixtureEnvironment,
    OPENMATES_TEST_ACCOUNT_EMAIL: TEST_EMAIL,
    OPENMATES_TEST_ACCOUNT_PASSWORD: TEST_PASSWORD,
    OPENMATES_TEST_ACCOUNT_OTP_KEY: TEST_OTP_KEY,
    OPENMATES_TEST_ACCOUNT_SOURCE_SLOT: '',
  });
}

async function expectDesktopProjectSplit(page): Promise<void> {
  const projectBox = await page.getByTestId('projects-page').boundingBox();
  const viewerBox = await page.getByTestId('project-embed-viewer').boundingBox();
  expect(projectBox).not.toBeNull();
  expect(viewerBox).not.toBeNull();
  expect(projectBox!.width).toBeLessThanOrEqual(401);
  expect(viewerBox!.x).toBeGreaterThanOrEqual(projectBox!.x + projectBox!.width);
}

test.describe('Projects remote sources', () => {
  test.beforeEach(async ({ page }) => {
    skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
    await skipIfFeaturesDisabled(test, page, ['platform:projects']);
    await loginToTestAccount(page);
  });

  // contract-test: direct surface=gui.web assertions=projects.access.explicit-context,projects.files.no-server-decryption-authority
  test('offers a deliberate re-login when the browser device binding is unavailable', async ({ page }) => {
    test.setTimeout(180000);
    const fixtureStateDir = mkdtempSync(join(tmpdir(), 'openmates-browser-project-relogin-'));
    chmodSync(fixtureStateDir, 0o700);
    const fixtureEnvironment = { ...process.env, OPENMATES_STATE_DIR: fixtureStateDir };
    let bridge = null;
    try {
      runChecked('npm', ['--prefix', CLI_DIR, 'run', 'build']);
      prepareRemoteHostSession(fixtureStateDir, fixtureEnvironment);
      bridge = spawn('node', [
        '--experimental-strip-types', '--loader',
        './frontend/packages/openmates-cli/tests/loader.mjs',
        'scripts/project_remote_access_live.mjs', 'serve', API_BASE_URL,
      ], {
        cwd: REPO_ROOT,
        env: { ...fixtureEnvironment, OPENMATES_REMOTE_HOST_SESSION: join(fixtureStateDir, 'session.json') },
        stdio: ['ignore', 'pipe', 'pipe'],
      });
      const fixture = await waitForFixtureEvent(bridge, 'fixture_ready');
      let refused = false;
      await page.route(/\/projects\/[^/]+\/sources\/[^/]+\/requests(?:\?|$)/, async (route) => {
        const request = route.request();
        if (!refused && request.method() === 'POST' && request.postDataJSON()?.operation === 'list') {
          refused = true;
          await route.fulfill({
            status: 409,
            contentType: 'application/json',
            body: JSON.stringify({ detail: 'REQUESTER_DEVICE_IDENTITY_UNAVAILABLE' }),
          });
          return;
        }
        await route.continue();
      });
      await page.goto('/projects');
      await page.getByTestId('project-landing-card').filter({ hasText: fixture.project_name }).click();
      await page.getByTestId('project-tab-folders').click();
      await expect(page.getByTestId('project-remote-error')).toContainText('fresh sign-in');
      await expect(page.getByTestId('project-remote-error')).not.toContainText('disconnected');
      await expect(page.getByTestId('project-source-relogin')).toBeVisible();
      await expect(page).toHaveURL(projectHashUrlPattern(fixture.project_id));
      await page.getByTestId('project-source-relogin').click();
      await expect(page).toHaveURL(projectHashUrlPattern(fixture.project_id));
      await expect(page.getByTestId('login-email-input')).toBeVisible({ timeout: 30000 });
    } finally {
      if (bridge) await stopFixtureProcess(bridge);
      rmSync(fixtureStateDir, { recursive: true, force: true });
    }
  });

  // contract-test: supporting surface=gui.web assertions=projects.access.explicit-context,projects.files.no-server-decryption-authority,projects.surface.semantic-parity,projects.uploads.project-wrapped,projects.items.responsive-embeds,projects.files.ignored-exact-inclusion,projects.files.private-path-deny,projects.files.connected-embed-previews,workspace-shell.nav.released-surfaces-visible
  test('browses nested connected files transiently and imports only after an explicit action', async ({ page }, testInfo) => {
    test.setTimeout(360000);
    await page.setViewportSize({ width: 1512, height: 921 });
    const fixtureStateDir = mkdtempSync(join(tmpdir(), 'openmates-browser-project-source-'));
    chmodSync(fixtureStateDir, 0o700);
    const fixtureEnvironment = { ...process.env, OPENMATES_STATE_DIR: fixtureStateDir };
    let bridge = null;
    let fixture: RemoteFixtureEvent | null = null;
    const persistenceRequests: string[] = [];
    const fileReadOperations: string[] = [];
    let observeFileReads = false;
    page.on('request', (request) => {
      if (observeFileReads && request.method() === 'POST' && /\/projects\/[^/]+\/sources\/[^/]+\/requests/.test(request.url())) {
        const operation = request.postDataJSON()?.operation;
        if (operation === 'read_text' || operation === 'read_file_chunk' || operation === 'read_image_chunk') {
          fileReadOperations.push(operation);
        }
      }
      if (request.method() === 'POST' && /\/(?:upload-embed|embeds)(?:\/|\?|$)|\/projects\/[^/]+\/items(?:\?|$)/.test(request.url())) {
        persistenceRequests.push(new URL(request.url()).pathname);
      }
    });
    try {
      runChecked('npm', ['--prefix', CLI_DIR, 'run', 'build']);
      prepareRemoteHostSession(fixtureStateDir, fixtureEnvironment);
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
      // Exercise the browser download fallback deterministically in headless CI.
      await page.addInitScript(() => {
        Object.defineProperty(window, 'showSaveFilePicker', { configurable: true, value: undefined });
      });
      await page.goto('/projects');
      const connectedProject = page.getByTestId('project-landing-card').filter({ hasText: fixture.project_name });
      await expect(connectedProject).toBeVisible({ timeout: 30000 });
      await connectedProject.click();
      await expect(page).toHaveURL(projectHashUrlPattern(fixture.project_id));
      await expect(page.getByTestId('projects-page')).toBeVisible({ timeout: 30000 });
      await expect(page.getByTestId('projects-nav-link')).toHaveAttribute('aria-current', 'page');
      await expect(page.getByTestId('chats-nav-link')).not.toHaveAttribute('aria-current', 'page');
      const readme = page.getByTestId('project-readme-content');
      const readmeImage = readme.getByRole('img', { name: 'Connected diagram' });
      await expect(readmeImage).toHaveAttribute('src', /^blob:/, { timeout: 30000 });
      await expect.poll(() => readmeImage.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(0);
      const externalDocs = readme.getByRole('link', { name: 'External docs' });
      await expect(externalDocs).toHaveAttribute('target', '_blank');
      await expect(externalDocs).toHaveAttribute('rel', /noopener/);
      await expect(externalDocs).toHaveAttribute('rel', /noreferrer/);
      observeFileReads = true;
      await page.getByTestId('project-tab-folders').click();
      await expect(page.getByTestId('project-connected-source-root')).toHaveCount(0);
      const sourceRoot = page.getByLabel('Project folder path').getByRole('button', { name: 'Live remote source' });
      await expect(page.getByLabel('Project folder path')).toHaveCount(0);
      await expect(page.getByTestId('project-folders-panel').locator('.section-title')).toHaveCount(0);
      await expect(page.getByTestId('project-remote-entry').filter({ hasText: 'docs' })).toBeVisible({ timeout: 30000 });
      await expect(page.getByTestId('project-item-card')).toHaveCount(0);
      await page.getByTestId('project-tab-overview').click();
      const returnedImage = page.getByTestId('project-readme-content').getByRole('img', { name: 'Connected diagram' });
      await expect(returnedImage).toHaveAttribute('src', /^blob:/);
      await expect.poll(() => returnedImage.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(0);
      await page.getByTestId('project-tab-folders').click();
      const sourceBrowser = page.getByTestId('project-remote-browser');
      const directoryResults = sourceBrowser.getByTestId('project-remote-directory-results');
      await expect(directoryResults).toBeAttached({ timeout: 30000 });
      const remoteEntries = directoryResults.getByTestId('project-remote-entry');
      await expect(remoteEntries.first()).toBeVisible();
      const actionTile = page.getByTestId('project-folder-actions');
      const [actionsBox, firstTileBox, secondTileBox] = await Promise.all([
        actionTile.boundingBox(), remoteEntries.nth(0).boundingBox(), remoteEntries.nth(1).boundingBox(),
      ]);
      expect(actionsBox && firstTileBox && secondTileBox).toBeTruthy();
      await expect(page.getByLabel('Project folder path')).toHaveCount(0);
      expect(Math.abs(actionsBox!.y - firstTileBox!.y)).toBeLessThanOrEqual(2);
      expect(Math.abs(firstTileBox!.y - secondTileBox!.y)).toBeLessThanOrEqual(2);
      expect(actionsBox!.x).toBeLessThan(firstTileBox!.x);
      expect(firstTileBox!.x).toBeLessThan(secondTileBox!.x);
      await testInfo.attach('connected-project-root-tiles', { body: await page.getByTestId('project-browser-list').screenshot(), contentType: 'image/png' });
      await page.getByRole('button', { name: 'List', exact: true }).click();
      const [firstRowBox, secondRowBox] = await Promise.all([remoteEntries.nth(0).boundingBox(), remoteEntries.nth(1).boundingBox()]);
      expect(firstRowBox && secondRowBox).toBeTruthy();
      expect(firstRowBox!.width).toBeGreaterThan(firstTileBox!.width * 2);
      expect(secondRowBox!.y).toBeGreaterThanOrEqual(firstRowBox!.y + firstRowBox!.height);
      await testInfo.attach('connected-project-root-list', { body: await page.getByTestId('project-browser-list').screenshot(), contentType: 'image/png' });
      await page.getByRole('button', { name: 'Tile', exact: true }).click();
      await expect(remoteEntries.getByTestId('project-remote-cloud-badge')).toHaveCount(await remoteEntries.count());
      expect(fileReadOperations).toEqual([]);
      await expect(directoryResults.getByTestId('project-remote-entry').filter({ hasText: /debug\.log|other\.log|customer-export|^private$|\.env|\.gitignore|\.openmates/ })).toHaveCount(0);
      const srcFolder = remoteEntries.filter({ hasText: 'src' });
      await expect(srcFolder.getByTestId('project-remote-folder-child')).toHaveCount(2);
      await expect(srcFolder).toContainText('lib');
      await expect(srcFolder).toContainText('remote-demo.ts');
      await expect(srcFolder).toContainText(/1 file, 1 folder.*in files/);
      await expect(srcFolder).not.toContainText('PRIVATE_DUMMY_CANARY');
      const docsFolder = remoteEntries.filter({ hasText: 'docs' });
      await expect(docsFolder.getByTestId('project-remote-folder-child')).toContainText('readme-image.png');
      await expect(docsFolder).toContainText(/1 file.*KiB in files/);
      const binaryFile = directoryResults.getByTestId('project-remote-preview-card').filter({ hasText: 'diagram.png' });
      await expect(binaryFile).toHaveAttribute('data-file-kind', 'image');
      await expect(binaryFile).toContainText('5 B');
      await expect(binaryFile.getByTestId('project-remote-preview-upload')).toHaveCount(0);
      await binaryFile.locator('.unified-embed-preview').click();
      await expect(page.getByTestId('file-embed-fullscreen')).toContainText('diagram.png', { timeout: 30000 });
      await closeFullscreen(page, page.getByTestId('project-remote-fullscreen-overlay'));
      const unknownBinary = directoryResults.getByTestId('project-remote-preview-card').filter({ hasText: 'mystery.dat' });
      await expect(unknownBinary).toContainText('Open for file details and download');
      await unknownBinary.locator('.unified-embed-preview').click();
      await expect(page.getByTestId('file-embed-fullscreen')).toContainText('mystery.dat');
      const binaryDownloadPromise = page.waitForEvent('download');
      await page.getByTestId('file-embed-fullscreen').getByTestId('embed-download-button').click();
      const binaryDownload = await binaryDownloadPromise;
      expect(binaryDownload.suggestedFilename()).toBe('mystery.dat');
      expect(readFileSync(await binaryDownload.path())).toEqual(Buffer.from([0x41, 0x00, 0x42, 0x43]));
      await closeFullscreen(page, page.getByTestId('project-remote-fullscreen-overlay'));
      const emptyFile = directoryResults.getByTestId('project-remote-preview-card').filter({ hasText: 'empty.dat' });
      await emptyFile.locator('.unified-embed-preview').click();
      const emptyDownloadPromise = page.waitForEvent('download');
      await page.getByTestId('file-embed-fullscreen').getByTestId('embed-download-button').click();
      expect(readFileSync(await (await emptyDownloadPromise).path())).toHaveLength(0);
      await closeFullscreen(page, page.getByTestId('project-remote-fullscreen-overlay'));
      const largeBinaryFile = directoryResults.getByTestId('project-remote-preview-card').filter({ hasText: 'large-binary.dat' });
      await largeBinaryFile.locator('.unified-embed-preview').click();
      const largeDownloadPromise = page.waitForEvent('download');
      await page.getByTestId('file-embed-fullscreen').getByTestId('embed-download-button').click();
      await expect(page.getByTestId('project-remote-download-status')).toContainText('large-binary.dat');
      const largeDownload = await largeDownloadPromise;
      expect(largeDownload.suggestedFilename()).toBe('large-binary.dat');
      const expectedLargeBytes = Buffer.alloc(4 * 1024 * 1024 + 1);
      for (let index = 0; index < expectedLargeBytes.length; index += 1) expectedLargeBytes[index] = index % 251;
      expect(readFileSync(await largeDownload.path())).toEqual(expectedLargeBytes);
      await closeFullscreen(page, page.getByTestId('project-remote-fullscreen-overlay'));
      await expect(unknownBinary.getByTestId('project-remote-preview-upload')).toHaveCount(0);
      await expect(page.getByTestId('project-remote-error')).toHaveCount(0);
      const readmeFile = directoryResults.getByTestId('project-remote-preview-card').filter({ hasText: 'README.md' });
      await expect(readmeFile.getByTestId('project-remote-preview-pending')).toContainText('Open to render preview');
      await expect(readmeFile.getByTestId('project-remote-preview-pending')).not.toContainText('Connected project');
      await docsFolder.click();
      await expect(page.getByLabel('Project folder path').getByText('docs', { exact: true })).toBeVisible();
      await expect(page.getByLabel('Project folder path').getByText('.', { exact: true })).toHaveCount(0);
      await expect(sourceRoot).toBeVisible();
      const rasterFile = sourceBrowser.getByTestId('project-remote-preview-card').filter({ hasText: 'readme-image.png' });
      await rasterFile.locator('.unified-embed-preview').click();
      await expect(page.getByTestId('project-remote-fullscreen-overlay').locator('img.full-image')).toHaveAttribute('src', /^blob:/, { timeout: 30000 });
      await closeFullscreen(page, page.getByTestId('project-remote-fullscreen-overlay'));
      await sourceRoot.click();
      await expect(page.getByLabel('Project folder path')).toHaveCount(0);
      await directoryResults.getByTestId('project-remote-entry').filter({ hasText: 'src' }).click();
      await expect(sourceBrowser.getByTestId('project-remote-entry').filter({ hasText: 'remote-demo.ts' })).toBeVisible();
      await sourceBrowser.getByTestId('project-remote-entry').filter({ hasText: /\blib\b/ }).click();
      await sourceBrowser.getByTestId('project-remote-entry').filter({ hasText: /\bdeep\b/ }).click();
      const largeFile = sourceBrowser.getByTestId('project-remote-preview-card').filter({ hasText: 'large-demo.ts' });
      await expect(largeFile).toBeVisible();
      await expect(largeFile.getByTestId('project-remote-cloud-badge')).toBeVisible();
      await testInfo.attach('connected-project-nested-files', { body: await page.getByTestId('project-browser-list').screenshot(), contentType: 'image/png' });
      await expect(largeFile.getByTestId('project-remote-preview-pending')).toContainText('Open to render preview');
      await expect(largeFile.getByTestId('project-remote-preview-pending')).not.toContainText('Remote fullscreen end marker');
      await largeFile.locator('.unified-embed-preview').click();
      const fullscreenOverlay = page.getByTestId('project-remote-fullscreen-overlay');
      await expect(fullscreenOverlay).toBeVisible({ timeout: 30000 });
      await expect(fullscreenOverlay).toContainText('Remote fullscreen end marker');
      await fullscreenOverlay.getByRole('button', { name: 'More' }).click();
      await expect(fullscreenOverlay.getByTestId('embed-download-button')).toBeVisible();
      const codeDownloadPromise = page.waitForEvent('download', { timeout: 30000 });
      await fullscreenOverlay.getByTestId('embed-download-button').click();
      const codeDownload = await codeDownloadPromise;
      expect(codeDownload.suggestedFilename()).toBe('large-demo.ts');
      expect(readFileSync(await codeDownload.path(), 'utf8')).toBe(
        '// Bounded remote text fixture\n'.repeat(1_500)
          + 'export const completeRemoteFile = "Remote fullscreen end marker";\n');
      const provenance = fullscreenOverlay.getByTestId('embed-header-provenance');
      const lineCount = fullscreenOverlay.getByTestId('embed-header-subtitle');
      await expect(provenance).toHaveText('Streamed from Live remote source');
      await expect(provenance.getByTestId('embed-header-provenance-icon')).toBeVisible();
      await expect(lineCount).toContainText('1501 lines');
      const provenanceBox = await provenance.boundingBox();
      const lineCountBox = await lineCount.boundingBox();
      expect(provenanceBox).not.toBeNull();
      expect(lineCountBox).not.toBeNull();
      expect(provenanceBox!.y + provenanceBox!.height).toBeLessThanOrEqual(lineCountBox!.y + 1);
      await expect(page.getByTestId('project-folder-actions').getByRole('button')).toHaveCount(3);
      await expect(page.getByTestId('project-folder-actions').getByRole('button').first()).toHaveCSS('filter', 'none');
      await expect(page.getByTestId('project-remote-parent')).toHaveCount(0);
      await expect(page.getByTestId('project-remote-search-input')).toHaveCount(0);
      await expect(page.getByTestId('project-remote-preview-meta')).toHaveCount(0);
      await expectDesktopProjectSplit(page);
      await testInfo.attach('connected-project-fullscreen-split', { body: await page.locator('.projects-workspace-layout').screenshot(), contentType: 'image/png' });
      await closeFullscreen(page, fullscreenOverlay);
      await expect(fullscreenOverlay).toHaveCount(0);
      await expect(page.getByTestId('project-item-card')).toHaveCount(0);
      expect(persistenceRequests).toEqual([]);

      // Search from the source root after exercising multiple nested directories.
      await sourceRoot.click();

      await page.getByTestId('project-folder-search').fill('remote-demo');
      await page.getByTestId('project-folder-search').press('Enter');
      const searchResults = page.getByTestId('project-remote-search-results');
      await expect(searchResults.getByTestId('project-search-current-heading')).toHaveText('Current folder:');
      await expect(searchResults.getByTestId('project-search-across-heading')).toHaveText(`Across ${fixture.project_name}:`);
      await expect(searchResults).toContainText('remote-demo.ts', { timeout: 30000 });
      await expect(searchResults).not.toContainText('PRIVATE_DUMMY_CANARY');
      await expect(searchResults).not.toContainText('debug.log');
      await searchResults.getByTestId('project-remote-preview-card').filter({ hasText: 'remote-demo.ts' }).first().locator('.unified-embed-preview').click();

      await expect(fullscreenOverlay).toBeVisible({ timeout: 30000 });
      await expect(fullscreenOverlay).toContainText('OpenMates live remote preview');
      await closeFullscreen(page, fullscreenOverlay);
      await expect(page.getByTestId('project-item-card')).toHaveCount(0);
      expect(persistenceRequests).toEqual([]);

      // Reload must reconstruct source metadata, not a durable copy of any previewed file.
      await page.reload();
      await page.getByTestId('project-tab-folders').click();
      await expect(page.getByTestId('project-remote-entry').first()).toBeVisible({ timeout: 30000 });
      await expect(page.getByTestId('project-item-card')).toHaveCount(0);
      await expect(page.getByTestId('project-remote-fullscreen-overlay')).toHaveCount(0);
      expect(persistenceRequests).toEqual([]);

      // Preserve the existing deliberate import behavior after proving viewing is transient.
      await sourceBrowser.getByTestId('project-remote-entry').filter({ hasText: /\bsrc\b/ }).click();
      await sourceBrowser.getByTestId('project-remote-preview-card').filter({ hasText: 'remote-demo.ts' }).locator('.unified-embed-preview').click();
      await expect(fullscreenOverlay).toBeVisible({ timeout: 30000 });
      await fullscreenOverlay.getByRole('button', { name: 'More' }).click();
      await fullscreenOverlay.getByTestId('project-remote-fullscreen-import').click();
      await closeFullscreen(page, fullscreenOverlay);
      await page.getByLabel('Project folder path').getByRole('button', { name: 'Project root' }).click();
      const importedFile = page.getByTestId('project-item-card').filter({ hasText: 'remote-demo.ts' }).first();
      await expect(importedFile).toBeVisible({ timeout: 30000 });
      await expect(importedFile.getByTestId('project-remote-cloud-badge')).toHaveCount(0);
      const importedPreview = importedFile.locator('.unified-embed-preview');
      await expect(importedPreview).toBeVisible({ timeout: 30_000 });
      await importedPreview.click();
      const storedFullscreen = page.getByTestId('embed-fullscreen-overlay');
      await expect(storedFullscreen).toBeVisible({ timeout: 30000 });
      await expect(storedFullscreen).toContainText('OpenMates live remote preview');
      await expect(storedFullscreen.getByTestId('embed-header-provenance')).toHaveCount(0);
      await expectDesktopProjectSplit(page);
      await closeFullscreen(page, storedFullscreen);
      await importedPreview.focus();
      await importedPreview.press('Enter');
      await expect(storedFullscreen).toBeVisible();
      await closeFullscreen(page, storedFullscreen);

      // A source going offline must close its decrypted image and revoke cached blob URLs.
      await page.getByTestId('project-connected-source-root').filter({ hasText: 'Live remote source' }).click();
      await sourceBrowser.getByTestId('project-remote-entry').filter({ hasText: 'docs' }).click();
      await sourceBrowser.getByTestId('project-remote-preview-card').filter({ hasText: 'readme-image.png' })
        .locator('.unified-embed-preview').click();
      const activeImage = page.getByTestId('project-remote-fullscreen-overlay').locator('img.full-image');
      await expect(activeImage).toHaveAttribute('src', /^blob:/, { timeout: 30000 });
      const activeImageUrl = await activeImage.getAttribute('src');
      expect(activeImageUrl).toBeTruthy();

      const stopped = waitForFixtureEvent(bridge, 'bridge_stopped');
      bridge.kill('SIGUSR1');
      await stopped;
      await expect(page.getByTestId('project-remote-fullscreen-overlay')).toHaveCount(0, { timeout: 30000 });
      await expect(page.getByTestId('project-remote-error')).toContainText('offline', { timeout: 30000 });
      await page.getByLabel('Project folder path').getByRole('button', { name: 'Project root' }).click();
      const offlineSourceCard = page.getByTestId('project-connected-source-root').filter({ hasText: 'Live remote source' });
      await expect(offlineSourceCard).toContainText('offline', { timeout: 30000 });
      await expect(offlineSourceCard).toHaveAttribute('data-status', 'offline');
      await expect(offlineSourceCard).not.toContainText('docs');
      await expect.poll(() => page.evaluate(async (url) => {
        try { return (await fetch(url)).ok; } catch { return false; }
      }, activeImageUrl!)).toBe(false);
    } finally {
      if (bridge) await stopFixtureProcess(bridge);
      rmSync(fixtureStateDir, { recursive: true, force: true });
    }
  });
});
