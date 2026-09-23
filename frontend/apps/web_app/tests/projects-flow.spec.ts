/* eslint-disable @typescript-eslint/no-require-imports */
import type { Response } from '@playwright/test';

export {};

const { test, expect } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled, skipWithoutCredentials } = require('./helpers/env-guard');
const { getTestAccount } = require('./signup-flow-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

function projectHashUrlPattern(projectId: string): RegExp {
  return new RegExp(`/projects#(?:[^#]*&)?project-id=${projectId}(?:&|$)`);
}

function projectDeleteResponseMatches(response: Response, projectId: string): boolean {
  return response.request().method() === 'DELETE'
    && new URL(response.url()).pathname === `/v1/projects/${projectId}`
    && response.ok();
}

test.describe('Projects v1 flow', () => {
  test.describe.configure({ timeout: 120000 });

  test.beforeEach(async ({ page }) => {
    skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
    await skipIfFeaturesDisabled(test, page, ['platform:projects']);
    await loginToTestAccount(page);
	});

	// contract-test: supporting surface=gui.web assertions=projects.lifecycle.encrypted-crud,projects.surface.semantic-parity,projects.files.write-policy-setup,projects.focus.default-owned,workspace-shell.nav.released-surfaces-visible,workspace-shell.start.shared-affordances
	test('creates and deletes a project', async ({ page }) => {
    await page.goto('/projects');
    await page.waitForLoadState('domcontentloaded');
    await expect(page.getByTestId('projects-page')).toBeVisible({ timeout: 30000 });
    await expect(page.getByTestId('projects-load-error')).toHaveCount(0);
    await expect(page.getByTestId('chats-nav-link')).toBeVisible({ timeout: 30000 });
    await expect(page.getByTestId('projects-nav-link')).toBeVisible({ timeout: 30000 });
    await expect(page.getByTestId('projects-start-screen')).toBeVisible();
    await expect(page.getByTestId('daily-inspiration-banner')).toBeVisible();
    await expect(page.getByTestId('project-input-composer')).toBeVisible();
    await expect(page.getByTestId('project-input-mic')).toBeVisible();
    await expect(page.getByTestId('project-write-policy-apply-and-show')).not.toBeChecked();
    await expect(page.getByTestId('project-write-policy-always-ask')).not.toBeChecked();
    await page.getByTestId('project-write-policy-apply-and-show').check();

    const projectName = `E2E Project ${Date.now()}`;
    const created = page.waitForResponse(
      (response) => response.request().method() === 'POST' && response.url().endsWith('/v1/projects') && response.ok()
    );
    await page.getByTestId('project-input-textarea').fill(projectName);
    await expect(page.getByTestId('project-input-submit')).toBeVisible();
    await page.getByTestId('project-input-submit').click();
    const createdResponse = await created;
    const createPayload = createdResponse.request().postDataJSON();
    expect(createPayload.write_mode).toBe('apply_and_show');
    expect(createPayload.default_focus_id).toMatch(/^[0-9a-f-]{36}$/i);
    expect(typeof createPayload.encrypted_settings).toBe('string');
    expect(createPayload.encrypted_settings).not.toContain(projectName);
    const projectId = (await createdResponse.json()).project.project_id;

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
      (response) => projectDeleteResponseMatches(response, projectId)
    );
    page.once('dialog', (dialog) => dialog.accept());
    await page.getByTestId('project-delete-button').click();
    await deleted;
    await expect(page.getByTestId('projects-start-screen')).toBeVisible({ timeout: 30000 });
    await expect(page.getByTestId('project-landing-card').filter({ hasText: projectName })).toHaveCount(0);
  });

	// contract-test: direct surface=gui.web assertions=projects.files.write-policy-setup,projects.surface.semantic-parity,projects.lifecycle.encrypted-crud
	test('edits and persists a project write policy without replacing encrypted settings', async ({ page }) => {
    await page.goto('/projects');
    await expect(page.getByTestId('projects-page')).toBeVisible({ timeout: 30000 });
    await page.getByTestId('project-write-policy-apply-and-show').check();

    const projectName = `E2E Project settings ${Date.now()}`;
    const created = page.waitForResponse(
      (response) => response.request().method() === 'POST' && response.url().endsWith('/v1/projects') && response.ok()
    );
    await page.getByTestId('project-input-textarea').fill(projectName);
    await page.getByTestId('project-input-submit').click();
    const projectId = (await (await created).json()).project.project_id;
    const settingsPath = `/#settings/projects/${encodeURIComponent(projectId)}`;
    const settingsResponseMatches = (response: Response) =>
      response.request().method() === 'GET'
      && new URL(response.url()).pathname.endsWith(`/v1/projects/${projectId}/settings`)
      && response.ok();

    const initialSettingsLoaded = page.waitForResponse(settingsResponseMatches);
    await page.goto(settingsPath, { waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('project-settings-page')).toBeVisible({ timeout: 30000 });
    const initialEncryptedSettings = (await (await initialSettingsLoaded).json()).settings.encrypted_settings;
    expect(typeof initialEncryptedSettings).toBe('string');
    await expect(page.getByTestId('project-settings-write-mode-apply-and-show')).toBeDisabled();

    const savedAlwaysAsk = page.waitForResponse(
      (response) => response.request().method() === 'PATCH'
        && new URL(response.url()).pathname.endsWith(`/v1/projects/${projectId}/settings`)
        && response.ok()
    );
    await page.getByTestId('project-settings-write-mode-always-ask').click();
    const alwaysAskResponse = await savedAlwaysAsk;
    expect(alwaysAskResponse.request().postDataJSON()).toMatchObject({ write_mode: 'always_ask' });
    expect(alwaysAskResponse.request().postDataJSON()).not.toHaveProperty('encrypted_settings');
    expect(alwaysAskResponse.request().postDataJSON()).not.toHaveProperty('default_focus_id');

    const alwaysAskReloaded = page.waitForResponse(settingsResponseMatches);
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('project-settings-write-mode-always-ask')).toBeDisabled({ timeout: 30000 });
    expect((await (await alwaysAskReloaded).json()).settings.encrypted_settings).toBe(initialEncryptedSettings);

    const savedApplyAndShow = page.waitForResponse(
      (response) => response.request().method() === 'PATCH'
        && new URL(response.url()).pathname.endsWith(`/v1/projects/${projectId}/settings`)
        && response.ok()
    );
    await page.getByTestId('project-settings-write-mode-apply-and-show').click();
    const applyAndShowResponse = await savedApplyAndShow;
    expect(applyAndShowResponse.request().postDataJSON()).toMatchObject({ write_mode: 'apply_and_show' });
    expect(applyAndShowResponse.request().postDataJSON()).not.toHaveProperty('encrypted_settings');

    const applyAndShowReloaded = page.waitForResponse(settingsResponseMatches);
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('project-settings-write-mode-apply-and-show')).toBeDisabled({ timeout: 30000 });
    expect((await (await applyAndShowReloaded).json()).settings.encrypted_settings).toBe(initialEncryptedSettings);

    await page.goto(`/projects#project-id=${encodeURIComponent(projectId)}`, { waitUntil: 'domcontentloaded' });
    const deleted = page.waitForResponse(
      (response) => projectDeleteResponseMatches(response, projectId)
    );
    page.once('dialog', (dialog) => dialog.accept());
    await page.getByTestId('project-delete-button').click();
    await deleted;
  });
});
