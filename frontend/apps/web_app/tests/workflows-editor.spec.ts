/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Workflows V1 web editor smoke coverage.
 *
 * Purpose: verifies the deployed Workflows route opens a focused editor with
 * explicit dirty-state controls, supports inline mobile node expansion, and
 * can run and delete a workflow.
 * Security: uses the shared E2E test account and cleans up only workflows made
 * during the current test run.
 */

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

function deriveApiUrl(baseUrl: string): string {
	try {
		const url = new URL(baseUrl);
		if (url.hostname === 'openmates.org' || url.hostname === 'www.openmates.org') return 'https://api.openmates.org';
		if (url.hostname.startsWith('app.')) return `${url.protocol}//api.${url.hostname.slice(4)}`;
		if (url.hostname === 'localhost') return 'http://localhost:8000';
	} catch {
		// Fall through to the production API default.
	}
	return 'https://api.openmates.org';
}

test.describe('Workflows editor', () => {
	test('opens a focused editor with explicit dirty-state controls', async ({ page }) => {
		test.setTimeout(180000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:workflows']);

		const apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
		const log = (message: string, metadata: Record<string, unknown> = {}) => {
			console.log(`[WORKFLOWS_E2E] ${message} ${JSON.stringify(metadata)}`);
		};
		const screenshot = async () => {};

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page, log, screenshot);

		const initialResponse = await page.request.get(`${apiUrl}/v1/workflows`);
		expect(initialResponse.ok()).toBe(true);
		const initialData = await initialResponse.json();
		const initialIds = new Set((initialData.workflows ?? []).map((workflow: { id: string }) => workflow.id));

		try {
			await page.setViewportSize({ width: 390, height: 844 });
			await page.goto(getE2EDebugUrl('/workflows'), { waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('workflows-page')).toBeVisible({ timeout: 30000 });
			await expect(page.getByTestId('workflow-recommendations')).toBeVisible();
			await page.getByTestId('workflow-recommendations').getByTestId('resume-chat-card').first().click();
			await expect(page.getByTestId('workflow-editor')).toBeVisible();
			await expect(page.getByTestId('workflows-list')).toHaveCount(0);
			await expect(page.getByTestId('workflow-title-input')).toHaveValue('Daily rain alert');
			await expect(page.getByTestId('workflow-description-input')).toBeVisible();
			await expect(page.getByTestId('workflow-action-palette')).toContainText('Add action');
			await expect(page.getByTestId('workflow-node-stack')).toContainText('then');
			await expect(page.getByTestId('workflow-node-stack')).toContainText('If true:');
			await expect(page.getByTestId('workflow-node-stack')).toContainText('If false:');
			await expect(page.getByTestId('workflow-node-stack')).toContainText('Do nothing');
			await expect(page.getByTestId('workflow-node-stack')).toContainText('Weather | Get forecast for Berlin');
			await expect(page.getByTestId('workflow-node-stack')).toContainText('rain probability > 60');

			await expect(page.getByTestId('save-workflow')).toBeDisabled();
			await page.getByTestId('workflow-title-input').fill('Daily rain alert edited');
			await expect(page.getByTestId('undo-workflow')).toBeVisible();
			await expect(page.getByTestId('undo-workflow')).toBeEnabled();
			await expect(page.getByTestId('save-workflow')).toBeEnabled();
			await page.getByTestId('undo-workflow').click();
			await expect(page.getByTestId('workflow-title-input')).toHaveValue('Daily rain alert');
			await expect(page.getByTestId('save-workflow')).toBeDisabled();

			const mobileWeatherNode = page.getByTestId('workflow-node-card').nth(1);
			await mobileWeatherNode.getByTestId('workflow-node-summary').click();
			await expect(mobileWeatherNode.getByTestId('workflow-node-expanded')).toBeVisible();
			await mobileWeatherNode.getByTestId('workflow-node-location-input').fill('Paris');
			await expect(page.getByTestId('save-workflow')).toBeEnabled();
			await page.getByTestId('workflow-title-input').fill('Daily rain alert edited');
			await page.getByTestId('workflow-description-input').fill('Check Paris weather every morning.');
			const saveWorkflowResponse = page.waitForResponse(
				(response) => response.url().includes('/v1/workflows/') && response.request().method() === 'PATCH' && response.ok(),
				{ timeout: 30000 }
			);
			await page.getByTestId('save-workflow').click();
			await saveWorkflowResponse;
			await expect(page.getByTestId('workflow-node-stack')).toContainText('Weather | Get forecast for Paris', { timeout: 30000 });
			await expect(page.getByTestId('workflow-description-input')).toHaveValue('Check Paris weather every morning.');

			await page.getByTestId('toggle-workflow').click();
			await expect(page.getByTestId('workflow-detail')).toContainText('disabled', { timeout: 30000 });
			await page.getByTestId('toggle-workflow').click();
			await expect(page.getByTestId('workflow-detail')).toContainText('active', { timeout: 30000 });

			await page.getByTestId('run-workflow').click();
			const rainRun = page.getByTestId('workflow-run-row').first();
			await expect(rainRun).toContainText('completed', { timeout: 30000 });

			await page.getByTestId('delete-workflow').click();
			await expect(page.getByTestId('workflow-title-input')).toHaveCount(0);
		} finally {
			const finalResponse = await page.request.get(`${apiUrl}/v1/workflows`);
			if (finalResponse.ok()) {
				const finalData = await finalResponse.json();
				for (const workflow of finalData.workflows ?? []) {
					if (!initialIds.has(workflow.id)) {
						await page.request.delete(`${apiUrl}/v1/workflows/${encodeURIComponent(workflow.id)}`).catch(() => null);
					}
				}
			}
		}
	});
});
