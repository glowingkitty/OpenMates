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
	// contract-test: supporting surface=gui.web assertions=workflows-ui.mvp.authoring
	test('mobile input creates a workflow that loads again in a fresh page', async ({ page }) => {
		test.setTimeout(120000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:workflows']);
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page, () => {}, async () => {});
		await page.setViewportSize({ width: 390, height: 844 });
		await page.goto(getE2EDebugUrl('/workflows'), { waitUntil: 'domcontentloaded' });
		const title = `Workflow input regression ${Date.now()}`;
		let workflow: { id: string; title: string } | undefined;
		// Authoring inference is deterministic here; the created definition still
		// goes through the real authenticated API and both persistence writes.
		await page.route('**/v1/workflows/input/stream', async (route) => {
			const instruction = route.request().postDataJSON();
			expect(instruction.text).toBe(title);
			const saved = await page.request.post(`${apiUrl()}/v1/workflows`, {
				data: {
					title: instruction.text,
					graph: {
						version: 2, trigger_node_id: 'manual',
						nodes: [{ id: 'manual', type: 'manual_trigger', title: 'Manual start', config: {} }],
						edges: []
					},
					enabled: false
				}
			});
			expect(saved.ok(), 'workflow creation must complete both persistence writes').toBe(true);
			workflow = (await saved.json()).workflow;
			await route.fulfill({
				contentType: 'text/event-stream',
				headers: {
					'access-control-allow-origin': new URL(page.url()).origin,
					'access-control-allow-credentials': 'true'
				},
				body: `data: ${JSON.stringify({ type: 'session', session: {
					session_id: 'workflow-editor-create-spec', status: 'executed', workflow,
					mutations: [{ type: 'create_workflow', target_id: workflow!.id }]
				} })}\n\n`
			});
		});
		await page.getByTestId('workflow-input-textarea').fill(title);
		const created = page.waitForResponse((response) =>
			response.url().endsWith('/v1/workflows/input/stream') && response.request().method() === 'POST'
		);
		await page.getByTestId('workflow-input-submit').click();
		const response = await created;
		expect(response.ok()).toBe(true);
		expect(workflow).toBeDefined();
		const savedWorkflow = workflow!;
		try {
			await expect(page.getByTestId('workspace-detail-title')).toHaveText(title);
			const freshPage = await page.context().newPage();
			try {
				await freshPage.goto(page.url(), { waitUntil: 'domcontentloaded' });
				await expect(freshPage.getByTestId('workspace-detail-title')).toHaveText(title);
				const detail = await freshPage.request.get(`${apiUrl()}/v1/workflows/${savedWorkflow.id}`);
				expect(detail.ok()).toBe(true);
				expect((await detail.json()).workflow.title).toBe(title);
			} finally { await freshPage.close(); }
		} finally {
			const removed = await page.request.delete(`${apiUrl()}/v1/workflows/${savedWorkflow.id}`);
			expect(removed.ok()).toBe(true);
		}
	});

	// contract-test: supporting surface=gui.web assertions=workflows-ui.template.centered-in-place-editor,workflows-ui.versions.timeline-readonly-restore-new,workflows.activation.reachable-side-effect,workflows-ui.schedule.preview,workflows-ui.mvp.authoring
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
			trigger_node_id: null,
			nodes: [
				{
					id: 'weather',
					type: 'app_skill_action',
					title: 'Weather forecast',
					config: {
						app_id: 'weather',
						skill_id: 'forecast',
						input: { location: 'Berlin', latitude: 52.52, longitude: 13.405, days: 1 }
					}
				},
				{
					id: 'message',
					type: 'send_chat_message',
					config: {
						title: 'Daily report',
						message: 'Forecast: {{steps.weather.forecast_day}}',
						blocks: [{ id: 'weather', source: '$nodes.weather.output.forecast_day' }]
					}
				}
			],
			edges: [{ from: 'weather', to: 'message' }]
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
				'Describe new workflow.'
			);
			await page
				.getByTestId('workflow-landing-card')
				.filter({ hasText: workflow.title })
				.first()
				.click();
			await expect(page.getByTestId('workspace-detail-title')).toHaveText(workflow.title);
			await expect(page.getByTestId('workflow-dirty-panel')).toHaveCount(0);
			await expect(page.getByTestId('workflow-version-history')).toHaveCount(0);
			await expect(page.getByTestId('workflow-version-selector')).toHaveCount(0);
			await page.getByTestId('workflow-detail-actions').getByRole('button', { name: 'More', exact: true }).click();
			await expect(page.getByTestId('run-workflow')).toBeEnabled();
			await expect(page.getByTestId('toggle-workflow')).toBeDisabled();
			await expect(page.getByTestId('workflow-template-test-now')).toHaveCount(0);

			// Nodes loaded into the route's reactive graph must open and save without
			// passing a Svelte proxy directly to structuredClone.
			const scheduled = await page.request.patch(`${apiUrl()}/v1/workflows/${workflow.id}`, {
				data: {
					graph: {
						...graph,
						trigger_node_id: 'trigger',
						nodes: [
							{
								id: 'trigger',
								type: 'schedule_trigger',
								config: { schedule: { type: 'daily', time: '09:00', timezone: 'Europe/Berlin' } }
							},
							...graph.nodes
						],
						edges: [{ from: 'trigger', to: 'weather' }, ...graph.edges]
					}
				}
			});
			expect(scheduled.ok()).toBe(true);
			await page.reload();
			const trigger = page.locator('[data-node-id="trigger"]');
			await expect(page.getByTestId('workflow-template-test-now')).toBeEnabled();
			await trigger.getByTestId('workflow-node-summary').click();
			await expect(trigger.getByTestId('workflow-time-trigger-schedule')).toHaveValue('daily');
			const triggerSave = page.waitForResponse(
				(response) =>
					response.url().endsWith(`/v1/workflows/${workflow.id}`) &&
					response.request().method() === 'PATCH'
			);
			await trigger.getByTestId('workflow-node-save').click();
			expect((await triggerSave).ok()).toBe(true);
			await expect(trigger.getByTestId('workflow-node-summary')).toBeVisible();

			const node = page.locator('[data-node-id="weather"]');
			const fixtureHeaders = {
				'access-control-allow-origin': new URL(page.url()).origin,
				'access-control-allow-credentials': 'true'
			};
			await page.route('**/v1/geocode/search?**', (route) =>
					route.fulfill({
						headers: fixtureHeaders,
						json: [{
						lat: '53.5511', lon: '9.9937', name: 'Hamburg', display_name: 'Hamburg, Germany',
						class: 'place', type: 'city', namedetails: { name: 'Hamburg' },
						address: { city: 'Hamburg', country: 'Germany' }
					}]
				})
			);
			await node.getByTestId('workflow-node-summary').click();
			await expect(node.getByTestId('workflow-node-expanded')).toBeVisible();
			await node.getByTestId('workflow-node-location-picker').click();
			// Initialization clears the previous map/search state after the opening
			// transition. Enter the query once the actual map is mounted.
			await expect(node.getByTestId('workflow-location-map').locator('.leaflet-container')).toBeVisible();
			const searched = page.waitForResponse(
				response => response.url().includes('/v1/geocode/search?') &&
					new URL(response.url()).searchParams.get('q') === 'Hamburg',
				{ timeout: 10_000 }
			);
			await node.getByTestId('map-location-search-input').fill('Hamburg');
			await expect(node.getByTestId('map-location-search-input')).toHaveValue('Hamburg');
			expect((await searched).ok()).toBe(true);
			await node.getByTestId('map-location-search-result').click();
			await node.getByTestId('map-location-select').click();
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
				await route.fulfill({ headers: fixtureHeaders, json: { run: { id: 'fixture-current-inputs' } } });
			});
			await page.route(`**/v1/workflows/${workflow.id}/runs/fixture-current-inputs`, (route) =>
				route.fulfill({
					headers: fixtureHeaders,
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
			const runPage = await page.context().newPage();
			try {
				await runPage.route(`**/v1/workflows/${workflow.id}/run`, (route) =>
					route.fulfill({ headers: fixtureHeaders, json: { run: {
						id: 'fixture-template-run', workflow_id: workflow.id,
						version_id: workflow.current_version_id, status: 'queued',
						trigger_type: 'test', started_at: Date.now() / 1000
					} } })
				);
				await runPage.goto(page.url(), { waitUntil: 'domcontentloaded' });
				const testNow = runPage.getByTestId('workflow-template-test-now');
				await expect(testNow).toBeVisible();
				await expect(testNow).toHaveText('Test now');
				await expect(testNow).toBeEnabled();
				const runRequest = runPage.waitForRequest((request) =>
					request.url().endsWith(`/v1/workflows/${workflow.id}/run`) &&
					request.method() === 'POST'
				);
				await testNow.click();
				expect((await runRequest).postDataJSON()).toEqual({ mode: 'test', input: {} });
				await expect(runPage).toHaveURL(/workflow-tab=runs/);
			} finally { await runPage.close(); }
			// History is visible in the current editor; the former More options
			// details section no longer owns the version controls.
			await expect(page.getByTestId('workflow-version-history')).toBeVisible();
			await expect(page.getByTestId('workflow-version-selector')).toHaveCSS('font-size', '14px');
			await page.getByTestId('workflow-version-selector').click();
			await page
				.locator('[data-testid="workflow-version-row"][data-current="false"]')
				.first()
				.click();
			await expect(page.getByTestId('workflow-version-graph')).toHaveAttribute(
				'data-read-only',
				'true'
			);
			await page.getByTestId('workflow-version-restore').click();
			await page.getByTestId('workflow-version-restore-confirm').click();
			const restoreNotification = page.getByTestId('notification').filter({
				hasText: /Restored version \d+ as a new current version\./
			});
			await expect(restoreNotification).toBeVisible();
			await expect(page.getByTestId('workflow-version-restored')).toHaveCount(0);
			await expect(restoreNotification).toHaveCount(0, { timeout: 8_000 });
		} finally {
			await page.request.delete(`${apiUrl()}/v1/workflows/${workflow.id}`);
		}
	});
	// contract-test: direct surface=gui.web assertions=workflows-ui.editor.inline-action-variables,workflows-ui.message-and-budget,workflows-ui.responsive-accessible-reachable
	test('mobile Send message filters earlier steps and saves a canonical variable that survives reload', async ({ page }) => {
		test.setTimeout(120000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:workflows']);
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page, () => {}, async () => {});
		const graph = {
			version: 2, trigger_node_id: null,
			nodes: [
				{ id: 'weather', type: 'app_skill_action', config: { app_id: 'weather', skill_id: 'forecast', input: { location: 'Berlin', latitude: 52.52, longitude: 13.405, days: 1 } } },
				{ id: 'events', type: 'app_skill_action', config: { app_id: 'events', skill_id: 'search', input: { requests: [{ query: 'Design events in Berlin' }] } } },
				{ id: 'message', type: 'send_chat_message', config: { title: 'Events report', message: 'Events: {{steps.events.results}}' } }
			],
			edges: [{ from: 'weather', to: 'events' }, { from: 'events', to: 'message' }]
		};
		const response = await page.request.post(`${apiUrl()}/v1/workflows`, { data: { title: `Send picker regression ${Date.now()}`, graph, enabled: false } });
		expect(response.ok()).toBe(true);
		const { workflow } = await response.json();
		try {
			await page.setViewportSize({ width: 390, height: 844 });
			await page.goto(getE2EDebugUrl(`/#workflow-id=${workflow.id}&workflow-tab=details`), { waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('workspace-detail-title')).toHaveText(workflow.title);
			const node = page.locator('[data-node-id="message"]');
			await node.getByTestId('workflow-node-summary').click();
			const body = node.getByTestId('workflow-message-template');
			const sources = node.getByTestId('workflow-variable-sources');
			await expect(node.getByRole('heading', { name: 'What should the message be?', exact: true })).toHaveCount(0);
			await expect(sources.locator('[data-source-node-id]')).toHaveCount(2);
			await body.fill('Here are the events: @events.search.results');
			await expect(body.locator('.workflow-mention-query')).toHaveText('@events.search.results');
			await expect(sources.locator('[data-source-node-id]')).toHaveCount(1);
			await sources.locator('[data-source-node-id="events"]').click();
			await node.getByTestId('workflow-ai-suggestions').locator('[data-variable-reference="$nodes.events.output.results"]').click();
			await expect(body.locator('.generic-mention')).toHaveText('@events.search.results');
			await expect(body.locator('.workflow-mention-icon')).toBeVisible();
			await expect(body.locator('.workflow-mention-query')).toHaveCount(0);
			const savedResponse = page.waitForResponse(response => response.url().endsWith(`/v1/workflows/${workflow.id}`) && response.request().method() === 'PATCH');
			await node.getByTestId('workflow-node-save').click();
			expect((await savedResponse).ok()).toBe(true);
			await expect(node.getByTestId('workflow-node-summary')).toBeVisible();
			const persisted = await page.request.get(`${apiUrl()}/v1/workflows/${workflow.id}`);
			expect(persisted.ok()).toBe(true);
			const saved = (await persisted.json()).workflow.graph.nodes.find((item: { id: string }) => item.id === 'message');
			expect(saved.config.message.trim()).toBe('Here are the events: {{steps.events.results}}');
			await page.reload({ waitUntil: 'domcontentloaded' });
			await node.getByTestId('workflow-node-summary').click();
			await expect(body.locator('.generic-mention')).toHaveText('@events.search.results');
			await expect(body.locator('.workflow-mention-icon')).toBeVisible();
		} finally {
			await page.request.delete(`${apiUrl()}/v1/workflows/${workflow.id}`);
		}
	});

});
