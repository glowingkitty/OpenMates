/* eslint-disable @typescript-eslint/no-require-imports -- Existing Playwright helpers expose CommonJS exports. */
import type { Page } from '@playwright/test';
export {};

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { waitForWorkflowWorkspaceReady } = require('./helpers/workspace-navigation');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { deriveApiUrl } = require('./helpers/cli-test-helpers');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

async function createWorkflow(page: Page, apiUrl: string, data: Record<string, unknown>) {
  const response = await page.request.post(`${apiUrl}/v1/workflows`, { data });
  expect(response.ok(), await response.text()).toBe(true);
  return (await response.json()).workflow;
}

test.describe('Workflow templates', () => {
	// contract-test: supporting surface=gui.web assertions=workflows-ui.workspace.owned-library-and-templates,workflows-ui.mvp.authoring
	test('browses templates and creates a disabled owned copy in the editor', async ({ page }: { page: Page }) => {
		test.setTimeout(150_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:workflows']);
		const apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
		let createdId: string | null = null;
		let sendFixtureId: string | null = null;
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page);
		try {
			await page.goto(getE2EDebugUrl('/workflows'), { waitUntil: 'domcontentloaded' });
			await waitForWorkflowWorkspaceReady(page);
			await expect(page.getByTestId('workflows-start-screen')).toBeVisible();
			await expect(page.getByTestId('workflow-mixed-row').getByTestId('workflow-landing-card').filter({ hasText: 'Weekly Berlin AI events' })).toHaveCount(0);
			await page.getByTestId('workflows-show-templates').click();
			await expect(page.getByTestId('all-workflows-view')).toBeVisible();
			await expect(page.getByRole('heading', { name: 'Templates' })).toBeVisible();
			await expect(page.getByTestId('workflows-sort')).toHaveCount(0);
			const templateCard = page.getByTestId('all-workflows-grid').getByTestId('workflow-landing-card').filter({ hasText: 'Weekly Berlin AI events' });
			await expect(templateCard).toBeVisible();
			const createdResponse = page.waitForResponse((response) => new URL(response.url()).pathname === '/v1/workflows' && response.request().method() === 'POST');
			await templateCard.click();
			const response = await createdResponse;
			expect(response.ok(), await response.text()).toBe(true);
			const created = (await response.json()).workflow;
			const workflowId = String(created.id);
			createdId = workflowId;
			expect(created.enabled).toBe(false);
			expect(created.category).toBe('science');
			expect(created.icon).toBe('calendar-days');
			expect(created.graph.version).toBe(2);
			expect(created.graph.nodes.map((node: { type: string }) => node.type)).toEqual(['schedule_trigger', 'app_skill_action', 'send_chat_message']);
			expect(created.graph.nodes[0].config.schedule).toMatchObject({
				type: 'weekly', weekdays: ['monday'], time: '09:00', timezone: 'Europe/Berlin'
			});
			expect(created.graph.nodes[1]).toMatchObject({ id: 'search', config: { app_id: 'events', skill_id: 'search' } });
			expect(created.graph.nodes[2]).toMatchObject({ id: 'message', config: {
				blocks: [{ id: 'results', source: '$nodes.search.output.results', label: 'Berlin AI events' }]
			} });
			await expect(page.getByTestId('workspace-detail-title')).toHaveText('Weekly Berlin AI events');
			await expect(page.getByTestId('workflow-template-panel')).toBeVisible();
			// Dev proves the complete template against real providers. CI checks the
			// cloned Send's typed binding with synthetic upstream data and executes
			// a separate Send-only fixture through the real runtime, without search.
			const syntheticEvent = {
				id: 'synthetic-ci-berlin-event', title: 'Synthetic CI Berlin AI event',
				url: 'https://example.test/events/synthetic-ci-berlin-event'
			};
			const previewResponse = await page.request.post(`${apiUrl}/v1/workflows/${encodeURIComponent(workflowId)}/steps/message/preview`, {
				data: { upstream_outputs: { search: { result_count: 1, results: [syntheticEvent] } } }
			});
			expect(previewResponse.ok(), await previewResponse.text()).toBe(true);
			const preview = (await previewResponse.json()).preview;
			expect(preview.dispatches).toBe(false);
			expect(preview.blocks).toHaveLength(1);
			expect(preview.blocks[0]).toMatchObject({ source: '$nodes.search.output.results', value: [syntheticEvent] });
			expect(preview.text).toContain(syntheticEvent.title);
			expect(preview.text).toContain(syntheticEvent.url);
			const sendFixture = await createWorkflow(page, apiUrl, {
				title: `Synthetic template Send ${workflowId}`, enabled: false,
				category: 'science', icon: 'calendar-days',
				graph: {
					version: 2, trigger_node_id: 'trigger',
					nodes: [
						{ id: 'trigger', type: 'manual_trigger', config: {} },
						{ id: 'message', type: 'send_chat_message', config: {
							title: 'Synthetic CI Berlin AI event', message: `${syntheticEvent.title}\n${syntheticEvent.url}`
						} }
					],
					edges: [{ from: 'trigger', to: 'message' }]
				}
			});
			const runtimeWorkflowId = String(sendFixture.id);
			sendFixtureId = runtimeWorkflowId;
			const runResponse = await page.request.post(`${apiUrl}/v1/workflows/${encodeURIComponent(runtimeWorkflowId)}/run`, {
				data: { mode: 'test', input: {} },
				headers: { 'Idempotency-Key': `template-browse-send-${runtimeWorkflowId}` }
			});
			expect(runResponse.ok(), await runResponse.text()).toBe(true);
			const run = (await runResponse.json()).run;
			await expect.poll(async () => {
				const result = await page.request.get(`${apiUrl}/v1/workflows/${encodeURIComponent(runtimeWorkflowId)}/runs/${encodeURIComponent(run.id)}`);
				if (!result.ok()) return `HTTP ${result.status()}`;
				return (await result.json()).run.status;
			}, { timeout: 45_000 }).toBe('completed');
			await page.getByTestId('workflow-detail-back').click();
			await expect(page.getByTestId('all-workflows-view')).toBeVisible();
			await expect(page.getByRole('heading', { name: 'Templates' })).toBeVisible();
			await page.getByTestId('workflows-back-to-recent').click();
			await expect(page.getByTestId('all-workflows-view')).toHaveCount(0);
			await waitForWorkflowWorkspaceReady(page);
			await page.getByTestId('workflows-show-all').click();
			await expect(page.getByTestId('all-workflows-grid').getByTestId('workflow-landing-card').filter({ hasText: 'Weekly Berlin AI events' })).toBeVisible();
		} finally {
			if (sendFixtureId) await page.request.delete(`${apiUrl}/v1/workflows/${encodeURIComponent(sendFixtureId)}`).catch(() => null);
			if (createdId) await page.request.delete(`${apiUrl}/v1/workflows/${encodeURIComponent(createdId)}`).catch(() => null);
		}
	});

});
