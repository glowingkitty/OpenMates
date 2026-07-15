/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Workflows V1 web editor smoke coverage.
 *
 * Purpose: verifies the deployed Workflows route opens a clean Figma detail
 * canvas with the shared editable header, contextual dirty-state controls, and
 * inline mobile node expansion without the rejected management UI.
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
			await expect(page.getByTestId('workflow-mixed-row')).toBeVisible();
			await page.getByTestId('workflow-mixed-row').getByTestId('workflow-landing-card').filter({ hasText: 'Tell me if it will rain tomorrow' }).click();
			await expect(page.getByTestId('workflow-editor')).toBeVisible();
			await expect(page).toHaveURL(/\/workflows\/[^/?#]+/);
			await expect(page.getByTestId('workflows-list')).toHaveCount(0);
			await expect(page.getByTestId('workspace-detail-header')).toHaveAttribute('data-header-system', 'workflow-detail');
			await expect(page.getByTestId('workflow-detail-actions')).toBeVisible();
			const headerBox = await page.getByTestId('workspace-detail-header').boundingBox();
			const actionsBox = await page.getByTestId('workflow-detail-actions').boundingBox();
			if (!headerBox || !actionsBox) throw new Error('Workflow header and actions must be measurable.');
			expect(actionsBox.x).toBeLessThan(headerBox.x + headerBox.width / 2);
			await expect(page.getByTestId('workspace-detail-title')).toHaveText('Daily rain alert');
			await expect(page.getByTestId('workflow-detail-metadata')).toContainText(/Next run (soon|in \d+ min|in \d+ hr|in \d+ days?)/);
			await expect(page.getByTestId('workflow-title-input')).toHaveCount(0);
			await expect(page.getByTestId('workflow-description-input')).toHaveCount(0);
			await expect(page.getByTestId('workflow-retention-select')).toHaveCount(0);
			await expect(page.getByTestId('selected-workflow-retention')).toHaveCount(0);
			await expect(page.getByTestId('selected-workflow-retention-select')).toHaveCount(0);
			await expect(page.getByTestId('run-workflow')).toBeVisible();
			await expect(page.getByTestId('delete-workflow')).toBeVisible();
			await expect(page.getByTestId('workflow-run-history')).toHaveAttribute('href', /\/workflows\/[^/?#]+\/runs$/);
			await expect(page.getByTestId('workflow-action-palette')).toContainText('Add action');
			await expect(page.getByTestId('workflow-node-stack')).toContainText('then');
			await expect(page.getByTestId('workflow-node-stack')).toContainText('If true:');
			await expect(page.getByTestId('workflow-node-stack')).toContainText('If false:');
			await expect(page.getByTestId('workflow-node-stack')).toContainText('Do nothing');
			await expect(page.getByTestId('workflow-node-stack')).toContainText('Weather | Get forecast for Berlin');
			await expect(page.getByTestId('workflow-node-stack')).toContainText('rain probability > 60');

			await expect(page.getByTestId('save-workflow')).toHaveCount(0);
			await expect(page.getByTestId('undo-workflow')).toHaveCount(0);

			const mobileWeatherNode = page.getByTestId('workflow-node-card').nth(1);
			await mobileWeatherNode.getByTestId('workflow-node-summary').click();
			await expect(mobileWeatherNode.getByTestId('workflow-node-expanded')).toBeVisible();
			await mobileWeatherNode.getByTestId('workflow-node-location-input').fill('Paris');
			await expect(page.getByTestId('undo-workflow')).toBeVisible();
			await expect(page.getByTestId('save-workflow')).toBeVisible();
			await expect(page.getByTestId('save-workflow')).toBeEnabled();
			const saveWorkflowResponse = page.waitForResponse(
				(response) => response.url().includes('/v1/workflows/') && response.request().method() === 'PATCH' && response.ok(),
				{ timeout: 30000 }
			);
			await page.getByTestId('save-workflow').click();
			await saveWorkflowResponse;
			await expect(page.getByTestId('workflow-node-stack')).toContainText('Weather | Get forecast for Paris', { timeout: 30000 });
			await expect(page.getByTestId('save-workflow')).toHaveCount(0);
			await expect(page.getByTestId('undo-workflow')).toHaveCount(0);
			await expect(page.getByTestId('workflow-version-history')).toBeVisible();
			await expect(page.getByTestId('workflow-version-history-retention')).toContainText('Keeps up to 25 definitions');
			const historicalVersion = page.locator('[data-testid="workflow-version-row"][data-current="false"]').first();
			await expect(historicalVersion).toBeVisible();
			await historicalVersion.click();
			await expect(page.getByTestId('workflow-version-graph-inspection')).toBeVisible();
			await expect(page.getByTestId('workflow-version-inspection-node')).toHaveCount(6);
			await page.getByTestId('workflow-version-restore').click();
			await expect(page.getByTestId('workflow-version-restore-confirmation')).toContainText('creates a new current version');
			await page.route('**/v1/workflows/*/versions/*/restore', (route) => route.fulfill({ status: 500, json: { detail: 'restore failed' } }), { times: 1 });
			await page.getByTestId('workflow-version-restore-confirm').click();
			await expect(page.getByTestId('workflow-version-error')).toBeVisible();
			const restoreResponse = page.waitForResponse(
				(response) => response.url().includes('/versions/') && response.url().endsWith('/restore') && response.request().method() === 'POST' && response.ok(),
				{ timeout: 30000 }
			);
			await page.getByTestId('workflow-version-restore-confirm').click();
			await restoreResponse;
			await expect(page.getByTestId('workflow-version-restored')).toContainText('new current version');
			await expect(page.locator('[data-testid="workflow-version-row"][data-current="true"]')).toHaveCount(1);
			await expect(page.getByTestId('toggle-workflow')).toBeVisible();
			await expect(page.getByTestId('create-blank-workflow')).toBeVisible();
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
