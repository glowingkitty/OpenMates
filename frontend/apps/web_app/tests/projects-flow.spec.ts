/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled, skipWithoutCredentials } = require('./helpers/env-guard');
const { getTestAccount } = require('./signup-flow-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

function projectHashUrlPattern(projectId: string): RegExp {
  return new RegExp(`/projects#(?:[^#]*&)?project-id=${projectId}(?:&|$)`);
}

test.describe('Projects v1 flow', () => {
  test.describe.configure({ timeout: 120000 });

  test.beforeEach(async ({ page }) => {
    skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
    await skipIfFeaturesDisabled(test, page, ['platform:projects']);
    await loginToTestAccount(page);
  });

  test('creates and deletes a project', async ({ page }) => {
    await page.goto('/projects');
    await page.waitForLoadState('domcontentloaded');
    await expect(page.getByTestId('projects-page')).toBeVisible({ timeout: 30000 });
    await expect(page.getByTestId('projects-load-error')).toHaveCount(0);
    await expect(page.getByTestId('chats-nav-link')).toBeVisible({ timeout: 30000 });
    await expect(page.getByTestId('projects-nav-link')).toHaveCount(0);
    await expect(page.getByTestId('projects-start-screen')).toBeVisible();
    await expect(page.getByTestId('daily-inspiration-banner')).toBeVisible();
    await expect(page.getByTestId('project-input-composer')).toBeVisible();
    await expect(page.getByTestId('project-input-mic')).toBeVisible();

    const projectName = `E2E Project ${Date.now()}`;
    const created = page.waitForResponse(
      (response) => response.request().method() === 'POST' && response.url().endsWith('/v1/projects') && response.ok()
    );
    await page.getByTestId('project-input-textarea').fill(projectName);
    await expect(page.getByTestId('project-input-submit')).toBeVisible();
    await page.getByTestId('project-input-submit').click();
    const projectId = (await (await created).json()).project.project_id;

    await expect(page).toHaveURL(projectHashUrlPattern(projectId));
    await expect(page.getByTestId('project-management')).toBeVisible();
    await expect(page.getByTestId('project-empty-items')).toBeVisible();

    await page.goto(`/projects/${encodeURIComponent(projectId)}`, { waitUntil: 'domcontentloaded' });
    await expect(page).toHaveURL(projectHashUrlPattern(projectId));
    await expect(page.getByTestId('workspace-detail-title')).toHaveText(projectName, { timeout: 30000 });

    await page.getByTestId('project-detail-back').click();
    await expect(page).toHaveURL(/\/projects$/);
    await expect(page.getByTestId('projects-start-screen')).toBeVisible();
    await expect(page.getByTestId('project-landing-card').filter({ hasText: projectName }).first()).toBeVisible();

    await page.getByTestId('project-landing-card').filter({ hasText: projectName }).first().click();
    await expect(page).toHaveURL(projectHashUrlPattern(projectId));

    const deleted = page.waitForResponse(
      (response) => response.request().method() === 'DELETE' && response.url().endsWith(`/v1/projects/${projectId}`) && response.ok()
    );
    page.once('dialog', (dialog) => dialog.accept());
    await page.getByTestId('project-delete-button').click();
    await deleted;
    await expect(page.getByTestId('projects-start-screen')).toBeVisible({ timeout: 30000 });
    await expect(page.getByTestId('project-landing-card').filter({ hasText: projectName })).toHaveCount(0);
  });
});
