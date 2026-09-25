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
    await expect(page.getByTestId('project-write-policy-dialog')).toHaveCount(0);

    const projectName = `E2E Project ${Date.now()}`;
    const created = page.waitForResponse(
      (response) => response.request().method() === 'POST' && response.url().endsWith('/v1/projects') && response.ok()
    );
    await page.getByTestId('project-input-textarea').fill(projectName);
    await expect(page.getByTestId('project-input-submit')).toBeVisible();
    await page.getByTestId('project-input-submit').click();
    await expect(page.getByTestId('project-write-policy-dialog')).toBeVisible();
    await expect(page.getByTestId('project-write-policy-apply-and-show')).not.toBeChecked();
    await expect(page.getByTestId('project-write-policy-always-ask')).not.toBeChecked();
    await page.getByTestId('project-write-policy-apply-and-show').check();
    await page.getByTestId('project-write-policy-confirm').click();
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
    await page.getByTestId('project-more-button').click();
    await page.getByTestId('project-delete-button').click();
    await deleted;
    await expect(page.getByTestId('projects-start-screen')).toBeVisible({ timeout: 30000 });
    await expect(page.getByTestId('project-landing-card').filter({ hasText: projectName })).toHaveCount(0);
  });

	// contract-test: direct surface=gui.web assertions=projects.files.write-policy-setup,projects.surface.semantic-parity,projects.lifecycle.encrypted-crud
	test('edits and persists a project write policy without replacing encrypted settings', async ({ page }) => {
    await page.goto('/projects');
    await expect(page.getByTestId('projects-page')).toBeVisible({ timeout: 30000 });

    const projectName = `E2E Project settings ${Date.now()}`;
    const created = page.waitForResponse(
      (response) => response.request().method() === 'POST' && response.url().endsWith('/v1/projects') && response.ok()
    );
    await page.getByTestId('project-input-textarea').fill(projectName);
    await page.getByTestId('project-input-submit').click();
    await page.getByTestId('project-write-policy-apply-and-show').check();
    await page.getByTestId('project-write-policy-confirm').click();
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
    await page.getByTestId('project-more-button').click();
    await page.getByTestId('project-delete-button').click();
    await deleted;
  });

	// contract-test: supporting surface=gui.web assertions=projects.surface.semantic-parity,projects.links.openmates-only-encrypted,projects.lifecycle.encrypted-crud
	test('starts project chats and saves workflows in the selected project', async ({ page }) => {
		test.setTimeout(180000);
		await skipIfFeaturesDisabled(test, page, ['platform:workflows']);
		const suffix = Date.now();
		const projectName = `E2E Project navigation ${suffix}`;
		const workflowTitle = `Project workflow ${suffix}`;
		let projectId: string | null = null;
		const workflowIds: string[] = [];
		let apiOrigin: string | null = null;

		try {
			await page.goto('/projects');
			await expect(page.getByTestId('projects-page')).toBeVisible({ timeout: 30000 });

			const created = page.waitForResponse(
				(response) =>
					response.request().method() === 'POST' &&
					new URL(response.url()).pathname === '/v1/projects' &&
					response.ok()
			);
			await page.getByTestId('project-input-textarea').fill(projectName);
			await page.getByTestId('project-input-submit').click();
			await page.getByTestId('project-write-policy-apply-and-show').check();
			await page.getByTestId('project-write-policy-confirm').click();
			const createdResponse = await created;
			apiOrigin = new URL(createdResponse.url()).origin;
			projectId = (await createdResponse.json()).project.project_id;

			await expect(page).toHaveURL(projectHashUrlPattern(projectId));
			await expect(page.getByTestId('project-workspace-header')).toBeVisible();
			await expect(page.getByTestId('workspace-detail-title')).toHaveText(projectName);
			await expect(page.getByTestId('project-started-date')).toContainText('Started');
			await expect(page.getByTestId('project-tabs')).toBeVisible();
			await expect(page.getByTestId('project-tab-overview')).toHaveAttribute(
				'aria-selected',
				'true'
			);
			await expect(page.getByTestId('project-tab-folders')).toBeVisible();
			await expect(page.getByTestId('project-tab-tasks')).toBeVisible();
			await expect(page.getByTestId('project-overview-panel')).toBeVisible();
			await expect(page.getByTestId('project-readme-empty')).toContainText(
				'No project overview created yet.'
			);
			await expect(page.getByTestId('project-readme-upload')).toBeVisible();
			await expect(page.getByTestId('project-readme-create')).toBeVisible();

			await page.getByTestId('project-tab-folders').click();
			await expect(page.getByTestId('project-folders-panel')).toBeVisible();
			await expect(page.getByTestId('project-folder-name-input')).toHaveCount(0);
			await expect(page.getByTestId('project-remote-sources-section')).toHaveCount(0);

			await page.getByTestId('project-folder-create-menu-button').click();
			await page.getByTestId('project-create-chat').click();
			await expect(page).toHaveURL(/\/$/);
			const messageEditor = page.getByTestId('message-editor');
			await expect(messageEditor).toBeVisible({ timeout: 30000 });
			// The inactive composer shows a draft summary and intentionally hides TipTap content.
			// Open the draft before asserting the actual project mention chip.
			await page.getByTestId('message-field').click();
			const projectMention = messageEditor.locator('[data-type="generic-mention"].mention-project');
			await expect(projectMention).toBeVisible({ timeout: 10000 });
			await expect(projectMention).toHaveAttribute(
				'data-mention-syntax',
				`@project:${projectId}:read`
			);
			await expect(projectMention).toHaveAttribute('data-project-access-mode', 'read');
			await expect(projectMention.getByTestId('project-access-chip')).toHaveText('Read');

			await page.goto(`/projects#project-id=${encodeURIComponent(projectId)}`, {
				waitUntil: 'domcontentloaded'
			});
			await expect(page.getByTestId('project-workspace-header')).toBeVisible({ timeout: 30000 });
			await page.getByTestId('project-tab-folders').click();
			await page.getByTestId('project-folder-create-menu-button').click();
			await page.getByTestId('project-create-workflow').click();

			await expect(page).toHaveURL(/\/workflows(?:[?#]|$)/);
			await expect(page.getByTestId('workflow-blank-creator')).toBeVisible({ timeout: 30000 });
			await expect(page.getByTestId('workflow-project-target')).toContainText(projectName);
			await page.getByTestId('workflow-blank-title-input').fill(workflowTitle);
			await page.route('**/v1/workflows', async (route) => {
				if (route.request().method() !== 'POST') return route.continue();
				return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Try again' }) });
			});
			const failedCreate = page.waitForResponse((response) =>
				response.request().method() === 'POST' &&
				new URL(response.url()).pathname === '/v1/workflows' &&
				response.status() === 503
			);
			await page.getByTestId('workflow-blank-create').click();
			await failedCreate;
			await expect(page.getByTestId('workflow-blank-creator')).toBeVisible();
			await expect(page.getByTestId('workflow-project-target')).toContainText(projectName);
			await page.unroute('**/v1/workflows');
			const workflowCreated = page.waitForResponse(
				(response) =>
					response.request().method() === 'POST' &&
					new URL(response.url()).pathname === '/v1/workflows' &&
					response.ok()
			);
			const projectItemCreated = page.waitForResponse(
				(response) =>
					response.request().method() === 'POST' &&
					new URL(response.url()).pathname === `/v1/projects/${projectId}/items` &&
					response.ok()
			);
			await page.getByTestId('workflow-blank-create').click();
			const workflowResponse = await workflowCreated;
			const workflowId = (await workflowResponse.json()).workflow.id;
			workflowIds.push(workflowId);
			const itemResponse = await projectItemCreated;
			const itemPayload = itemResponse.request().postDataJSON();
			expect(itemPayload).toMatchObject({
				folder_id: null,
				item_type: 'workflow',
				target_id: workflowId
			});
			expect(typeof itemPayload.target_id_encrypted).toBe('string');
			expect(typeof itemPayload.encrypted_display_name).toBe('string');
			expect(typeof itemPayload.encrypted_metadata).toBe('string');
			expect(itemPayload.encrypted_display_name).not.toContain(workflowTitle);
			expect(itemPayload.encrypted_metadata).not.toContain(projectName);

			await page.goto(`/projects#project-id=${encodeURIComponent(projectId)}`, {
				waitUntil: 'domcontentloaded'
			});
			await expect(page.getByTestId('project-workspace-header')).toBeVisible({ timeout: 30000 });
			await page.getByTestId('project-tab-folders').click();
			await page.getByTestId('project-folder-create-menu-button').click();
			await page.getByTestId('project-create-workflow').click();
			await expect(page.getByTestId('workflow-project-target')).toContainText(projectName);

			const failedLinkWorkflowTitle = `Unlinked workflow ${suffix}`;
			let failedLinkWorkflowCreates = 0;
			const recordFailedLinkWorkflowCreate = (request: { method(): string; url(): string }) => {
				if (request.method() === 'POST' && new URL(request.url()).pathname === '/v1/workflows') {
					failedLinkWorkflowCreates += 1;
				}
			};
			page.on('request', recordFailedLinkWorkflowCreate);
			await page.route(`**/v1/projects/${projectId}/items*`, async (route) => {
				await route.fulfill({
					status: 503,
					contentType: 'application/json',
					body: JSON.stringify({ detail: 'Project association unavailable' })
				});
			});
			await page.getByTestId('workflow-blank-title-input').fill(failedLinkWorkflowTitle);
			const failedLinkWorkflowCreated = page.waitForResponse(
				(response) =>
					response.request().method() === 'POST' &&
					new URL(response.url()).pathname === '/v1/workflows' &&
					response.ok()
			);
			await page.getByTestId('workflow-blank-create').click();
			const failedLinkWorkflowId = (await (await failedLinkWorkflowCreated).json()).workflow.id;
			workflowIds.push(failedLinkWorkflowId);
			await expect(page).toHaveURL(new RegExp(`workflow-id=${failedLinkWorkflowId}`));
			await expect(page.getByTestId('workflow-management')).toBeVisible({ timeout: 30000 });
			await expect(page.getByTestId('workflow-blank-creator')).toHaveCount(0);
			await expect(page.getByTestId('workflows-error')).toContainText(
				`Workflow created, but it could not be added to ${projectName}.`
			);
			expect(failedLinkWorkflowCreates).toBe(1);
			page.off('request', recordFailedLinkWorkflowCreate);
			await page.unroute(`**/v1/projects/${projectId}/items*`);
		} finally {
			if (apiOrigin) {
				for (const workflowId of workflowIds) {
					await page.request
						.delete(`${apiOrigin}/v1/workflows/${encodeURIComponent(workflowId)}`)
						.catch(() => null);
				}
			}
			if (projectId && apiOrigin) {
				await page.request
					.delete(`${apiOrigin}/v1/projects/${encodeURIComponent(projectId)}`)
					.catch(() => null);
			}
		}
	});
});
