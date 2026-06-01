/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { getTestAccount } = require('./signup-flow-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

test.describe('Projects v1 flow', () => {
  test.beforeEach(async ({ page }) => {
    skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
    await loginToTestAccount(page);
  });

  test('creates and deletes a project', async ({ page }) => {
    await page.goto('/projects');
    await page.waitForLoadState('domcontentloaded');
    await expect(page.getByTestId('projects-page')).toBeVisible({ timeout: 30000 });
    await expect(page.getByTestId('projects-load-error')).toHaveCount(0);
    await expect(page.getByTestId('chats-nav-link')).toBeVisible();
    await expect(page.getByTestId('projects-nav-link')).toBeVisible();
    await expect(page.getByTestId('projects-nav-link')).toHaveClass(/active/);
    await expect(page.getByTestId('all-projects-section')).toBeVisible();

    const projectName = `E2E Project ${Date.now()}`;
    await page.getByTestId('project-create-main-button').click();
    await expect(page.getByTestId('projects-sidebar')).toBeVisible();
    await page.getByTestId('project-name-input').fill(projectName);
    await page.getByTestId('project-create-button').click();

    await expect(page.getByTestId('project-card').filter({ hasText: projectName })).toBeVisible();
    await expect(page.getByTestId('recent-project-card').filter({ hasText: projectName })).toBeVisible();
    await expect(page.getByTestId('project-empty-items')).toBeVisible();

    page.once('dialog', (dialog) => dialog.accept());
    await page.getByTestId('project-delete-button').click();
    await expect(page.getByTestId('project-card').filter({ hasText: projectName })).toHaveCount(0);
  });
});
