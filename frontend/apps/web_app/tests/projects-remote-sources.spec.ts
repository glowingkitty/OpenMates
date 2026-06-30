/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { getTestAccount } = require('./signup-flow-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org';
const API_BASE_URL = process.env.PLAYWRIGHT_TEST_API_URL || BASE_URL.replace('://app.dev.', '://api.dev.').replace('://app.', '://api.');

test.describe('Projects remote sources', () => {
  test.beforeEach(async ({ page }) => {
    skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
    await loginToTestAccount(page);
  });

  test('renders attached remote source status in Projects', async ({ page }) => {
    await page.goto('/projects');
    await page.waitForLoadState('domcontentloaded');
    await expect(page.getByTestId('projects-page')).toBeVisible({ timeout: 30000 });

    const projectName = `E2E Remote Source ${Date.now()}`;
    await page.getByTestId('project-create-main-button').click();
    await expect(page.getByTestId('projects-sidebar')).toBeVisible();
    await page.getByTestId('project-name-input').fill(projectName);
    await page.getByTestId('project-create-button').click();
    await expect(page.getByTestId('project-card').filter({ hasText: projectName }).first()).toBeVisible();

    const sourceId = `source-${Date.now()}`;
    const projectId = await page.evaluate(async ({ name, apiBaseUrl }) => {
      const response = await fetch(`${apiBaseUrl}/v1/projects`, { credentials: 'include' });
      if (!response.ok) throw new Error(`Project list failed: ${response.status}`);
      const data = await response.json();
      const projects = Array.isArray(data.projects) ? data.projects : [];
      const latest = projects.sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0))[0];
      if (!latest?.project_id) throw new Error(`Could not resolve project id for ${name}`);
      return latest.project_id;
    }, { name: projectName, apiBaseUrl: API_BASE_URL });

    await page.evaluate(async ({ apiBaseUrl, projectId, sourceId }) => {
      const timestamp = Math.floor(Date.now() / 1000);
      const response = await fetch(`${apiBaseUrl}/v1/projects/${encodeURIComponent(projectId)}/sources`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source_id: sourceId,
          source_type: 'remote_git_repository',
          encrypted_display_name: 'opaque-ciphertext',
          encrypted_metadata: 'opaque-ciphertext',
          capabilities: ['read', 'search'],
          status: 'connected',
          created_at: timestamp,
          updated_at: timestamp,
        }),
      });
      if (!response.ok) throw new Error(`Project source create failed: ${response.status} ${await response.text()}`);
    }, { apiBaseUrl: API_BASE_URL, projectId, sourceId });

    await page.reload();
    await expect(page.getByTestId('projects-page')).toBeVisible({ timeout: 30000 });
    await expect(page.getByTestId('project-card').filter({ hasText: projectName }).first()).toBeVisible();
    await expect(page.getByTestId('project-remote-sources-section')).toBeVisible();
    await expect(page.getByTestId('project-remote-source-card').filter({ hasText: sourceId })).toBeVisible();
    await expect(page.getByTestId('project-remote-source-card').filter({ hasText: 'connected' })).toBeVisible();

    await page.getByTestId('project-settings-button').click();
    const projectSettings = page.locator(`[data-testid="settings-menu"][data-active-view="projects/${projectId}"]`);
    await expect(projectSettings).toBeVisible({ timeout: 10000 });
    await expect(projectSettings.getByTestId('project-settings-page')).toBeVisible();
    await expect(projectSettings.getByTestId('project-settings-title')).toContainText(projectName);
    await expect(projectSettings.getByTestId('project-settings-source-card').filter({ hasText: sourceId })).toBeVisible();
    await projectSettings.getByTestId('project-settings-write-mode-safe-writes').click();
    await expect(projectSettings).toContainText('Project write policy saved.');
    await expect(projectSettings).toContainText('Auto approve safe writes');

    await page.getByTestId('icon-button-close').click();

    await page.getByTestId('message-editor').click();
    await page.keyboard.type('@E2E');
    await expect(page.getByTestId('mention-dropdown')).toBeVisible();
    await page.getByTestId('mention-result').filter({ hasText: projectName }).first().click();

    const editor = page.getByTestId('message-editor');
    await expect(editor.locator('[data-mention-type="project"]')).toBeVisible();
    await expect(editor.getByTestId('project-access-chip')).toContainText('Read & Write');
    await editor.getByTestId('project-access-chip').press('Enter');
    await expect(editor.getByTestId('project-access-chip')).toContainText('Read');

    page.once('dialog', (dialog) => dialog.accept());
    await page.getByTestId('project-delete-button').click();
    await expect(page.getByTestId('project-card').filter({ hasText: projectName })).toHaveCount(0);
  });
});
