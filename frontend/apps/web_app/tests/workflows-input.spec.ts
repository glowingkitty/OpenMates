/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Workflows input home coverage.
 *
 * Purpose: verifies the deployed Workflows home keeps its recommendations,
 * recents, and Show all mode while the fixed composer creates manual drafts
 * without using the workflow-input planning endpoint.
 * Security: uses the shared E2E account and deletes only workflows created by
 * this spec run.
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
	test('preserves home content and creates a title-only manual draft', async ({ page }) => {
		test.setTimeout(180000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:workflows']);

		const apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
		const createdWorkflowIds = new Set<string>();
		const log = (message: string, metadata: Record<string, unknown> = {}) => {
			console.log(`[WORKFLOWS_INPUT_E2E] ${message} ${JSON.stringify(metadata)}`);
		};
		const screenshot = async () => {};
		const workflowInputRequests: string[] = [];
		const recordWorkflowInputRequest = (request: { url: () => string }) => {
			if (new URL(request.url()).pathname.startsWith('/v1/workflows/input')) {
				workflowInputRequests.push(request.url());
			}
		};

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page, log, screenshot);

		try {
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
			}

			await page.setViewportSize({ width: 390, height: 844 });
			await page.goto(getE2EDebugUrl('/workflows'), { waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('workflows-page')).toBeVisible({ timeout: 30000 });
			await expect(page.getByTestId('workflows-start-screen')).toBeVisible();
			await expect(page.getByTestId('daily-inspiration-banner')).toBeVisible();
			await expect(page.getByTestId('daily-inspiration-label')).toBeVisible();
			await expect(page.getByTestId('workflow-inspiration-card')).toHaveCount(0);
			await expect(page.getByTestId('workflow-management')).toHaveCount(0);
			await expect(page.getByTestId('workflows-workspace-center')).toContainText('Hey');
			await expect(page.getByTestId('workflows-workspace-center')).toContainText('What do you want to automate next?');
			await expect(page.getByTestId('workflow-recommendations')).toBeVisible();
			await expect(page.getByTestId('recent-workflows')).toBeVisible();
			await expect(page.getByTestId('workflows-show-all')).toBeVisible();
			await expect(page.getByTestId('workflows-search')).toBeDisabled();
			await expect(page.getByTestId('resume-chat-card').first()).toBeVisible();
			await expect(page.getByTestId('workflow-input-composer')).toBeVisible();
			await expect(page.getByTestId('workflow-input-submit')).toBeDisabled();
			await expect(page.getByTestId('message-editor')).toHaveCount(0);

			const startScreenBox = await page.getByTestId('workflows-start-screen').boundingBox();
			const composerBox = await page.getByTestId('workflow-input-composer').boundingBox();
			const centerBox = await page.getByTestId('workflows-workspace-center').boundingBox();
			if (!startScreenBox || !composerBox || !centerBox) throw new Error('Workflows home sections must be measurable.');
			expect(startScreenBox.height).toBeGreaterThan(700);
			expect(composerBox.y + composerBox.height).toBeGreaterThan(760);
			expect(centerBox.y + centerBox.height).toBeLessThan(composerBox.y);

			await page.getByTestId('workflows-show-all').click();
			await expect(page.getByTestId('workflow-recommendations')).toHaveCount(0);
			await expect(page.getByTestId('recent-workflows')).toHaveCount(0);
			await expect(page.getByTestId('all-workflows-grid')).toBeVisible();
			await expect(page.getByTestId('workflow-input-composer')).toBeVisible();

			await page.getByTestId('workflows-show-all').click();
			await expect(page.getByTestId('workflow-recommendations')).toBeVisible();
			await expect(page.getByTestId('recent-workflows')).toBeVisible();
			await expect(page.getByTestId('all-workflows-grid')).toHaveCount(0);

			page.on('request', recordWorkflowInputRequest);
			const createDraftResponse = page.waitForResponse(
				(response) => new URL(response.url()).pathname === '/v1/workflows' && response.request().method() === 'POST' && response.ok(),
				{ timeout: 30000 }
			);
			await page.getByTestId('workflow-input-textarea').fill('Daily school weather');
			await expect(page.getByTestId('workflow-input-submit')).toBeEnabled();
			await page.getByTestId('workflow-input-submit').click();
			const draftData = await createDraftResponse;
			const draft = (await draftData.json()).workflow;
			createdWorkflowIds.add(draft.id);
			await expect(page.getByTestId('workflow-editor')).toBeVisible({ timeout: 30000 });
			await expect(page.getByTestId('workflow-title-input')).toHaveValue('Daily school weather');
			expect(draft.title).toBe('Daily school weather');
			expect(draft.enabled).toBe(false);
			expect(draft.graph.nodes).toHaveLength(1);
			expect(draft.graph.nodes[0].id).toBe('manual');
			expect(draft.graph.nodes[0].type).toBe('manual_trigger');
			expect(draft.graph.edges).toHaveLength(0);
			expect(workflowInputRequests).toEqual([]);
		} finally {
			page.off('request', recordWorkflowInputRequest);
			for (const workflowId of createdWorkflowIds) {
				await page.request.delete(`${apiUrl}/v1/workflows/${encodeURIComponent(workflowId)}`).catch(() => null);
			}
		}
	});
});
