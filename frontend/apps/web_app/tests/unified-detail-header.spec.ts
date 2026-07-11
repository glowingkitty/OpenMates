/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Red interaction contract for editable fields in the shared detail header.
 *
 * The spec owns one Workflow record and deletes that exact record. It verifies
 * title and description editing semantics without sharing mutable fixtures with
 * another Playwright spec or depending on concurrent test execution.
 */

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

function deriveApiUrl(baseUrl: string): string {
	const url = new URL(baseUrl || 'https://app.dev.openmates.org');
	if (url.hostname.startsWith('app.')) return `${url.protocol}//api.${url.hostname.slice(4)}`;
	if (url.hostname === 'localhost') return 'http://localhost:8000';
	return 'https://api.openmates.org';
}

function workflowGraph() {
	return {
		version: 1,
		trigger_node_id: 'manual',
		nodes: [{ id: 'manual', type: 'manual_trigger', title: 'Manual', config: {} }],
		edges: []
	};
}

test.describe('Unified detail header editing', () => {
	test('Workflow title and description expose hints, save, and undo semantics', async ({ page }) => {
		test.setTimeout(180000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:workflows']);

		const apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
		const suffix = `${Date.now()}-${test.info().workerIndex}`;
		const originalTitle = `Unified header workflow ${suffix}`;
		const originalDescription = `Persisted description ${suffix}`;
		let workflowId = '';

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page);

		try {
			const createResponse = await page.request.post(`${apiUrl}/v1/workflows`, {
				data: {
					title: originalTitle,
					description: originalDescription,
					graph: workflowGraph(),
					enabled: false
				}
			});
			expect(createResponse.ok()).toBe(true);
			workflowId = (await createResponse.json()).workflow.id;

			await page.goto(getE2EDebugUrl(`/workflows/${workflowId}`), { waitUntil: 'domcontentloaded' });
			const header = page.getByTestId('workspace-detail-header');
			await expect(header).toBeVisible({ timeout: 30000 });
			await expect(header).toHaveAttribute('data-header-system', 'workspace-detail');

			const titleField = header.getByTestId('workspace-detail-title-field');
			await titleField.hover();
			await expect(titleField.getByTestId('workspace-detail-title-edit')).toBeVisible();
			await titleField.getByTestId('workspace-detail-title-edit').focus();
			await titleField.getByTestId('workspace-detail-title-edit').press('Enter');

			const titleInput = titleField.getByTestId('workspace-detail-title-input');
			await expect(titleInput).toBeVisible();
			await expect(titleField.getByTestId('workspace-detail-title-hint')).toBeVisible();
			await titleInput.fill(`Unsaved title ${suffix}`);
			await expect(titleField.getByTestId('workspace-detail-title-save')).toBeVisible();
			await expect(titleField.getByTestId('workspace-detail-title-undo')).toBeVisible();
			await titleField.getByTestId('workspace-detail-title-undo').click();
			await expect(header.getByTestId('workspace-detail-title')).toHaveText(originalTitle);

			await header.getByTestId('workspace-detail-title').click();
			await titleField.getByTestId('workspace-detail-title-input').fill(`Saved title ${suffix}`);
			const titleSave = page.waitForResponse(
				(response) => response.request().method() === 'PATCH' && response.url().endsWith(`/v1/workflows/${workflowId}`) && response.ok()
			);
			await titleField.getByTestId('workspace-detail-title-input').press('Enter');
			await titleSave;
			await expect(header.getByTestId('workspace-detail-title')).toHaveText(`Saved title ${suffix}`);

			const descriptionField = header.getByTestId('workspace-detail-description-field');
			await descriptionField.getByTestId('workspace-detail-description').click();
			const descriptionInput = descriptionField.getByTestId('workspace-detail-description-input');
			await expect(descriptionInput).toBeVisible();
			await expect(descriptionField.getByTestId('workspace-detail-description-hint')).toBeVisible();
			await descriptionInput.fill(`Saved description ${suffix}`);
			await expect(descriptionField.getByTestId('workspace-detail-description-save')).toBeVisible();
			await expect(descriptionField.getByTestId('workspace-detail-description-undo')).toBeVisible();
			const descriptionSave = page.waitForResponse(
				(response) => response.request().method() === 'PATCH' && response.url().endsWith(`/v1/workflows/${workflowId}`) && response.ok()
			);
			await descriptionField.getByTestId('workspace-detail-description-save').click();
			await descriptionSave;
			await expect(descriptionField.getByTestId('workspace-detail-description')).toHaveText(`Saved description ${suffix}`);

			await descriptionField.getByTestId('workspace-detail-description').click();
			await descriptionField.getByTestId('workspace-detail-description-input').fill(`Keyboard description ${suffix}`);
			const keyboardSave = page.waitForResponse(
				(response) => response.request().method() === 'PATCH' && response.url().endsWith(`/v1/workflows/${workflowId}`) && response.ok()
			);
			await descriptionField.getByTestId('workspace-detail-description-input').press('Control+Enter');
			await keyboardSave;
			await expect(descriptionField.getByTestId('workspace-detail-description')).toHaveText(`Keyboard description ${suffix}`);
		} finally {
			if (workflowId) {
				await page.request.delete(`${apiUrl}/v1/workflows/${encodeURIComponent(workflowId)}`).catch(() => null);
			}
		}
	});
});
