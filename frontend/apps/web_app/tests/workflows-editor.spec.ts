/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Workflows V1 web editor smoke coverage.
 *
 * Purpose: verifies the deployed Workflows route can create canonical starter
 * workflows, edit retention, run server-side tests, and delete workflows.
 * Security: uses the shared E2E test account and cleans up only workflows made
 * during the current test run.
 */

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
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
	test('creates, edits, runs, and deletes canonical workflows', async ({ page }) => {
		test.setTimeout(180000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');

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
			await page.goto(getE2EDebugUrl('/workflows'), { waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('workflows-page')).toBeVisible({ timeout: 30000 });

			await page.getByTestId('workflow-retention-select').selectOption('none');
			await page.getByTestId('create-rain-workflow').click();
			await expect(page.getByTestId('selected-workflow-retention')).toContainText('No durable run content', { timeout: 30000 });
			await expect(page.getByTestId('workflow-editor')).toBeVisible();
			await expect(page.getByTestId('workflow-action-palette')).toContainText('Add action');
			await expect(page.getByTestId('workflow-node-stack')).toContainText('then');
			await expect(page.getByTestId('workflow-node-stack')).toContainText('If true:');
			await expect(page.getByTestId('workflow-node-stack')).toContainText('If false:');
			await expect(page.getByTestId('workflow-node-stack')).toContainText('Do nothing');
			await expect(page.getByTestId('workflow-node-stack')).toContainText('Weather | Get forecast for Berlin');
			await expect(page.getByTestId('workflow-node-stack')).toContainText('rain probability > 60');

			await page.getByTestId('workflow-title-input').fill('Daily rain alert edited');
			await page.getByTestId('workflow-node-summary').nth(1).click();
			await expect(page.getByTestId('workflow-node-expanded')).toBeVisible();
			await page.getByTestId('workflow-node-location-input').fill('Paris');
			await page.getByTestId('add-report-node').click();
			await expect(page.getByTestId('workflow-node-card')).toHaveCount(6);
			await page.getByTestId('save-workflow').click();
			await expect(page.getByTestId('workflow-node-stack')).toContainText('Weather | Get forecast for Paris', { timeout: 30000 });
			await expect(page.getByTestId('workflow-node-stack')).toContainText('Create report');
			await expect(page.getByTestId('workflows-list')).toContainText('Daily rain alert edited');

			await page.getByTestId('toggle-workflow').click();
			await expect(page.getByTestId('workflow-detail')).toContainText('disabled', { timeout: 30000 });
			await page.getByTestId('toggle-workflow').click();
			await expect(page.getByTestId('workflow-detail')).toContainText('active', { timeout: 30000 });

			await page.getByTestId('run-workflow').click();
			const rainRun = page.getByTestId('workflow-run-row').first();
			await expect(rainRun).toContainText('completed', { timeout: 30000 });
			await expect(rainRun).toContainText('ephemeral none');

			await page.getByTestId('selected-workflow-retention-select').selectOption('last_5');
			await page.getByTestId('save-workflow-retention').click();
			await expect(page.getByTestId('selected-workflow-retention')).toContainText('Keep latest 5 encrypted runs', { timeout: 30000 });

			await page.getByTestId('workflow-retention-select').selectOption('last_5');
			await page.getByTestId('create-news-workflow').click();
			await expect(page.getByTestId('selected-workflow-retention')).toContainText('Keep latest 5 encrypted runs', { timeout: 30000 });
			await expect(page.getByTestId('workflow-node-stack')).toContainText('News | Search OpenAI news');
			await page.getByTestId('run-workflow').click();
			await expect(page.getByTestId('workflow-run-row').first()).toContainText('durable last_5', { timeout: 30000 });

			await page.getByTestId('delete-workflow').click();
			await expect(page.getByTestId('workflow-node-stack')).toContainText('Weather | Get forecast for Paris', { timeout: 30000 });
			await page.getByTestId('delete-workflow').click();
			await expect(page.getByText('Build your first workflow')).toBeVisible({ timeout: 30000 });
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
