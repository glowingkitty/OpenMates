/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Workflows input home coverage.
 *
 * Purpose: verifies the deployed Workflows route exposes chat-like workflow
 * input affordances without reusing chat send behavior, and that text input
 * creates a durable workflow-input session that can be undone.
 * Security: uses the shared E2E account and deletes only workflows created by
 * this spec run.
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

function blankWorkflowGraph(index: number) {
	return {
		version: 1,
		trigger_node_id: 'trigger',
		nodes: [
			{
				id: 'trigger',
				type: 'schedule_trigger',
				title: `Spec schedule ${index}`,
				config: { schedule: { type: 'daily', time: '09:00', timezone: 'Europe/Berlin' } }
			},
			{ id: 'end', type: 'end', title: 'Done', config: {} }
		],
		edges: [{ from: 'trigger', to: 'end' }]
	};
}

test.describe('Workflows input home', () => {
	test('shows workflow input states and can undo a text-created workflow', async ({ page }) => {
		test.setTimeout(180000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');

		const apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
		const createdWorkflowIds = new Set<string>();
		const log = (message: string, metadata: Record<string, unknown> = {}) => {
			console.log(`[WORKFLOWS_INPUT_E2E] ${message} ${JSON.stringify(metadata)}`);
		};
		const screenshot = async () => {};

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page, log, screenshot);

		try {
			let firstSeedWorkflowTitle = '';
			for (let index = 0; index < 6; index += 1) {
				const title = `Input spec seed ${Date.now()} ${index}`;
				const response = await page.request.post(`${apiUrl}/v1/workflows`, {
					data: {
						title,
						graph: blankWorkflowGraph(index),
						enabled: index < 3,
						run_content_retention: index % 2 === 0 ? 'last_5' : 'none'
					}
				});
				expect(response.ok()).toBe(true);
				const data = await response.json();
				createdWorkflowIds.add(data.workflow.id);
				if (index === 0) firstSeedWorkflowTitle = title;
			}

			await page.setViewportSize({ width: 390, height: 844 });
			await page.goto(getE2EDebugUrl('/workflows'), { waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('workflows-page')).toBeVisible({ timeout: 30000 });
			await expect(page.getByTestId('workflows-start-screen')).toBeVisible();
			await expect(page.getByTestId('daily-inspiration-banner')).toBeVisible();
			await expect(page.getByTestId('daily-inspiration-label')).toBeVisible();
			await expect(page.getByTestId('workflow-inspiration-card')).toHaveCount(0);
			await expect(page.getByTestId('workflow-management')).toHaveCount(0);
			await expect(page.getByText('Manage automations')).toHaveCount(0);
			await expect(page.getByTestId('workflows-list')).toHaveCount(0);
			await expect(page.getByTestId('workflow-detail')).toHaveCount(0);
			await expect(page.getByTestId('workflows-show-all')).toHaveCount(0);
			await expect(page.getByTestId('workflows-workspace-center')).toContainText('Hey');
			await expect(page.getByTestId('workflows-workspace-center')).toContainText('What do you want to automate next?');
			await expect(page.getByTestId('workflow-recommendations')).toContainText('Tell me if it will rain tomorrow');
			await expect(page.getByTestId('recent-workflows')).toHaveCount(0);
			await expect(page.getByTestId('resume-chat-card').first()).toBeVisible();
			await expect(page.getByTestId('resume-chat-card').first()).toHaveClass(/resume-chat-card/);
			await expect(page.getByTestId('workflow-input-composer')).toBeVisible();
			await expect(page.getByTestId('workflow-input-textarea')).toHaveAttribute('placeholder', /Ask OpenMates to create or update a workflow/);
			await expect(page.getByTestId('workflow-input-submit')).toBeDisabled();
			await expect(page.getByTestId('message-editor')).toHaveCount(0);

			const startScreenBox = await page.getByTestId('workflows-start-screen').boundingBox();
			const composerBox = await page.getByTestId('workflow-input-composer').boundingBox();
			const centerBox = await page.getByTestId('workflows-workspace-center').boundingBox();
			if (!startScreenBox || !composerBox || !centerBox) throw new Error('Workflows home sections must be measurable.');
			expect(startScreenBox.height).toBeGreaterThan(700);
			expect(composerBox.y + composerBox.height).toBeGreaterThan(760);
			expect(centerBox.y + centerBox.height).toBeLessThan(composerBox.y);

			await page.setViewportSize({ width: 1365, height: 900 });
			await expect(page.getByTestId('daily-inspiration-banner')).toBeVisible();
			await expect(page.getByTestId('resume-chat-large-card').first()).toBeVisible();
			await expect(page.getByTestId('workflow-management')).toHaveCount(0);
			await page.getByTestId('workflow-recommendations').getByText(firstSeedWorkflowTitle).click();
			await expect(page).toHaveURL(/\/workflows\?view=manage/);
			await expect(page.getByTestId('workflow-title-input')).toHaveValue(firstSeedWorkflowTitle, { timeout: 30000 });

			await page.goto(getE2EDebugUrl('/workflows'), { waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('workflow-input-composer')).toBeVisible();

			const createInputResponse = page.waitForResponse(
				(response) => response.url().includes('/v1/workflows/input') && response.request().method() === 'POST' && response.ok(),
				{ timeout: 30000 }
			);
			await page.getByTestId('workflow-input-textarea').fill('Tell me if it will rain tomorrow morning');
			await expect(page.getByTestId('workflow-input-submit')).toBeEnabled();
			await page.getByTestId('workflow-input-submit').click();
			const inputResponse = await createInputResponse;
			const inputData = await inputResponse.json();
			createdWorkflowIds.add(inputData.session.workflow.id);

			await expect(page.getByTestId('workflow-input-status')).toHaveAttribute('data-status', 'executed', { timeout: 30000 });
			await expect(page.getByTestId('workflow-input-status')).toContainText('committed');
			await expect(page.getByTestId('workflow-title-input')).toHaveCount(0);
			await expect(page.getByTestId('workflow-input-undo')).toBeVisible();

			const undoResponse = page.waitForResponse(
				(response) => response.url().includes('/undo') && response.request().method() === 'POST' && response.ok(),
				{ timeout: 30000 }
			);
			await page.getByTestId('workflow-input-undo').click();
			await undoResponse;
			await expect(page.getByTestId('workflow-input-status')).toHaveAttribute('data-status', 'undone', { timeout: 30000 });
			await expect(page.getByTestId('workflow-management')).toHaveCount(0);
			await expect(page.getByText('Manage automations')).toHaveCount(0);
		} finally {
			for (const workflowId of createdWorkflowIds) {
				await page.request.delete(`${apiUrl}/v1/workflows/${encodeURIComponent(workflowId)}`).catch(() => null);
			}
		}
	});
});
