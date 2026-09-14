/* eslint-disable @typescript-eslint/no-require-imports -- Existing browser test helpers. */
/** Focused v1 authoring contract; real persistence, deterministic fixtures for optional paid tests. */
export {};
const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');
function apiUrl(): string {
	const url = new URL(process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org');
	return url.hostname === 'localhost'
		? 'http://localhost:8000'
		: `${url.protocol}//${url.hostname.replace(/^app\./, 'api.')}`;
}

test.describe('Workflows editor', () => {
	// contract-test: supporting surface=gui.web assertions=workflows-ui.template.centered-in-place-editor,workflows-ui.versions.timeline-readonly-restore-new
	test('node Save persists, while testing current inputs leaves the definition unchanged', async ({
		page
	}) => {
		test.setTimeout(180000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:workflows']);
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(
			page,
			() => {},
			async () => {}
		);
		const graph = {
			version: 2,
			trigger_node_id: 'trigger',
			nodes: [
				{
					id: 'trigger',
					type: 'schedule_trigger',
					config: { schedule: { type: 'hourly', minute: 0, timezone: 'Europe/Berlin' } }
				},
				{
					id: 'weather',
					type: 'app_skill_action',
					title: 'Weather forecast',
					config: {
						app_id: 'weather',
						skill_id: 'forecast',
						input: { location: 'Berlin', days: 1 }
					}
				},
				{
					id: 'message',
					type: 'send_chat_message',
					config: {
						title: 'Daily report',
						blocks: [{ id: 'weather', source: '$nodes.weather.output.forecast_day' }]
					}
				}
			],
			edges: [
				{ from: 'trigger', to: 'weather' },
				{ from: 'weather', to: 'message' }
			]
		};
		const response = await page.request.post(`${apiUrl()}/v1/workflows`, {
			data: { title: `Workflow node save ${Date.now()}`, graph, enabled: false }
		});
		expect(response.ok()).toBe(true);
		const { workflow } = await response.json();
		try {
			await page.setViewportSize({ width: 390, height: 844 });
			await page.goto(getE2EDebugUrl('/workflows'), { waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('create-blank-workflow')).toHaveCount(0);
			await expect(page.getByTestId('workflow-input-textarea')).toHaveAttribute(
				'placeholder',
				'Enter a name for a new workflow'
			);
			await page
				.getByTestId('workflow-landing-card')
				.filter({ hasText: workflow.title })
				.first()
				.click();
			await expect(page.getByTestId('workspace-detail-title')).toHaveText(workflow.title);
			await expect(page.getByTestId('workflow-dirty-panel')).toHaveCount(0);
			const node = page.locator('[data-node-id="weather"]');
			await node.getByTestId('workflow-node-summary').click();
			await node.getByTestId('workflow-node-location-input').fill('Hamburg');
			await expect(node.getByTestId('workflow-node-save')).toBeVisible();
			const before = await (
				await page.request.get(`${apiUrl()}/v1/workflows/${workflow.id}`)
			).json();
			expect(
				before.workflow.graph.nodes.find((item: { id: string }) => item.id === 'weather').config
					.input.location
			).toBe('Berlin');
			let testedInput: unknown;
			await page.route(`**/v1/workflows/${workflow.id}/steps/weather/test`, async (route) => {
				testedInput = route.request().postDataJSON();
				await route.fulfill({ json: { run: { id: 'fixture-current-inputs' } } });
			});
			await page.route(`**/v1/workflows/${workflow.id}/runs/fixture-current-inputs`, (route) =>
				route.fulfill({
					json: {
						run: {
							id: 'fixture-current-inputs',
							workflow_id: workflow.id,
							version_id: workflow.current_version_id,
							status: 'completed',
							node_runs: [
								{
									node_id: 'weather',
									status: 'completed',
									output_summary: { rain_probability: 35, rain_periods: [] }
								}
							]
						}
					}
				})
			);
			await node.getByTestId('workflow-test-action').click();
			await expect(node.getByTestId('workflow-output-fields')).toContainText('35');
			expect(
				(testedInput as { node: { config: { input: { location: string } } } }).node.config.input
					.location
			).toBe('Hamburg');
			const afterTest = await (
				await page.request.get(`${apiUrl()}/v1/workflows/${workflow.id}`)
			).json();
			expect(afterTest.workflow.current_version_id).toBe(before.workflow.current_version_id);
			const savedResponse = page.waitForResponse(
				(response) =>
					response.url().endsWith(`/v1/workflows/${workflow.id}`) &&
					response.request().method() === 'PATCH'
			);
			await node.getByTestId('workflow-node-save').click();
			expect((await savedResponse).ok()).toBe(true);
			await expect(node.getByTestId('workflow-node-summary')).toContainText('Hamburg');
			await expect(page.getByTestId('save-workflow')).toHaveCount(0);
			await page.reload();
			await expect(
				page.locator('[data-node-id="weather"]').getByTestId('workflow-node-summary')
			).toContainText('Hamburg');
			await page.getByTestId('workflow-more-options').locator('summary').click();
			await expect(page.getByTestId('workflow-version-history')).toBeVisible();
			await page
				.locator('[data-testid="workflow-version-row"][data-current="false"]')
				.first()
				.click();
			await expect(page.getByTestId('workflow-version-graph')).toHaveAttribute(
				'data-read-only',
				'true'
			);
		} finally {
			await page.request.delete(`${apiUrl()}/v1/workflows/${workflow.id}`);
		}
	});
});
