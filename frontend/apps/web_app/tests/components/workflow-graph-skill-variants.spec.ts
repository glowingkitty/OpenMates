// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Existing Playwright helpers expose CommonJS exports. */
export {};

import type { Page, Route } from '@playwright/test';

import { waitForComponentPreview } from '../helpers/component-preview';

const { expect, test } = require('../helpers/cookie-audit');

const EVENTS_PREVIEW =
	'/dev/preview/workflows/WorkflowGraphRenderer?variant=eventsSearch&theme=light&background=%23dbeafe&width=900&chrome=0';

const VARIABLE_INPUT_GRAPH = {
	version: 2,
	trigger_node_id: 'trigger',
	nodes: [
		{
			id: 'trigger',
			type: 'schedule_trigger',
			config: { schedule: { type: 'weekly', weekdays: ['sunday'], time: '09:00', timezone: 'Europe/Berlin' } }
		},
		{
			id: 'source',
			type: 'app_skill_action',
			title: 'Example place lookup',
			config: { app_id: 'fixture', skill_id: 'places', input: { query: 'Berlin' } }
		},
		{
			id: 'events',
			type: 'app_skill_action',
			title: 'Search events',
			config: { app_id: 'events', skill_id: 'search', input: { requests: [{ query: '$nodes.source.output.title', location: 'Berlin' }] } }
		}
	],
	edges: [
		{ from: 'trigger', to: 'source' },
		{ from: 'source', to: 'events' }
	]
};

const VARIABLE_INPUT_CAPABILITY = {
	id: 'events.search',
	type: 'app_skill',
	enabled: true,
	title: 'Search',
	metadata: {
		app_id: 'events',
		skill_id: 'search',
		cost: { per_unit: { credits: 30 } },
		input_schema: {
			type: 'object',
			properties: {
				requests: {
					type: 'array',
					items: {
						type: 'object',
						properties: {
							query: { type: 'string', 'x-ui': { basic: true } },
							location: { type: 'string', 'x-ui': { basic: true } },
							event_type: { type: 'string', enum: ['PHYSICAL', 'ONLINE'], 'x-ui': { basic: false } }
						},
						required: ['query']
					}
				}
			},
			required: ['requests']
		},
		output_schema: { type: 'object', properties: { results: { type: 'array' } } }
	}
};

const VARIABLE_SOURCE_CAPABILITY = {
	id: 'fixture.places',
	type: 'app_skill',
	enabled: true,
	title: 'Places',
	metadata: {
		app_id: 'fixture',
		skill_id: 'places',
		input_schema: { type: 'object', properties: { query: { type: 'string' } } },
		output_schema: {
			type: 'object',
			properties: {
				provider: { type: 'string', 'x-ui': { basic: true } },
				city: { type: 'string', 'x-ui': { basic: true } },
				title: { type: 'string', 'x-ui': { basic: false } },
				address: { type: 'string', 'x-ui': { basic: false } }
			}
		}
	}
};

test.describe('WorkflowGraphRenderer real skill variants', () => {
	// contract-test: direct surface=gui.web assertions=workflows-ui.template.centered-in-place-editor,workflows-ui.responsive-accessible-reachable
	test('joins an expanded Events Search summary to its details at desktop and phone widths', async ({ page }: { page: Page }) => {
		for (const width of [1280, 390]) {
			await page.setViewportSize({ width, height: 900 });
			const query = new URLSearchParams({
				variant: 'eventsSearch', theme: 'light', background: '#dbeafe', width: String(width), chrome: '0',
				props: JSON.stringify({ readOnly: true, onSave: null })
			});
			await page.goto(`/dev/preview/workflows/WorkflowGraphRenderer?${query}`, { waitUntil: 'domcontentloaded' });
			await waitForComponentPreview(page);
			const node = page.locator('[data-node-id="events"]');
			const summary = node.getByTestId('workflow-node-summary');
			await expect(summary).toContainText('Events | Search');
			await summary.click();
			await expect(summary).toHaveAttribute('aria-expanded', 'true');
			const details = node.getByTestId('workflow-node-expanded');
			await expect(details).toBeVisible();
			await expect.poll(async () => {
				const [headerBox, bodyBox] = await Promise.all([summary.boundingBox(), details.boundingBox()]);
				const style = await summary.evaluate(element => ({
					width: getComputedStyle(element).width,
					marginRight: getComputedStyle(element).marginRight,
					scale: getComputedStyle(element).scale
				}));
				return {
					aligned: Boolean(headerBox && bodyBox && Math.abs(headerBox.x - bodyBox.x) <= 1 && Math.abs(headerBox.width - bodyBox.width) <= 1),
					headerBox, bodyBox, style
				};
			}).toMatchObject({ aligned: true });
			const [summaryBox, detailsBox, canvasBox] = await Promise.all([
				summary.boundingBox(), details.boundingBox(), page.locator('.graph-canvas').boundingBox()
			]);
			expect(summaryBox && detailsBox && canvasBox).not.toBeNull();
			if (!summaryBox || !detailsBox || !canvasBox) return;
			expect(Math.abs(summaryBox.x - detailsBox.x)).toBeLessThanOrEqual(1);
			expect(Math.abs(summaryBox.width - detailsBox.width)).toBeLessThanOrEqual(1);
			expect(Math.abs(summaryBox.y + summaryBox.height - detailsBox.y)).toBeLessThanOrEqual(1);
			expect(summaryBox.x).toBeGreaterThanOrEqual(canvasBox.x - 1);
			expect(detailsBox.x + detailsBox.width).toBeLessThanOrEqual(canvasBox.x + canvasBox.width + 1);
			if (width === 1280) expect(summaryBox.width).toBeGreaterThan(700);
		}
	});

	// contract-test: direct surface=gui.web assertions=workflows-ui.responsive-accessible-reachable,workflows-ui.mvp.authoring
	test('app skill tests show exactly one Processing indicator in the output container', async ({ page }: { page: Page }) => {
		let release = () => {};
		const held = new Promise<void>(resolve => { release = resolve; });
		await page.route('**/v1/workflows/preview-workflow/steps/events/test', async (route: Route) => {
			const headers = { 'Access-Control-Allow-Origin': new URL(page.url()).origin, 'Access-Control-Allow-Credentials': 'true', 'Access-Control-Allow-Methods': 'POST,OPTIONS', 'Access-Control-Allow-Headers': 'Content-Type' };
			if (route.request().method() === 'OPTIONS') { await route.fulfill({ status: 204, headers }); return; }
			await held;
			await route.fulfill({ headers, json: { run: { id: 'events-test', status: 'completed', node_runs: [{ node_id: 'events', output_summary: { results: [{ title: 'Test art class', url: 'https://example.com/art' }] } }] } } });
		});
		try {
			await page.goto(EVENTS_PREVIEW + '&props=' + encodeURIComponent(JSON.stringify({ workflowId: 'preview-workflow' })), { waitUntil: 'domcontentloaded' });
			await waitForComponentPreview(page);
			const node = page.locator('[data-node-id="events"]');
			await node.getByTestId('workflow-node-summary').click();
			await node.getByTestId('workflow-test-action').click();
			await expect(node.getByTestId('workflow-test-output-loading')).toHaveText('Processing…');
			await expect(node.getByText('Processing…', { exact: true })).toHaveCount(1);
			await expect(node.locator('.test-control')).not.toContainText('Processing...');
			await expect(node.getByTestId('workflow-test-action')).toBeDisabled();
			await node.screenshot({ path: test.info().outputPath('app-skill-single-processing.png') });
			release();
			await expect(node.getByTestId('workflow-test-output-loading')).toHaveCount(0);
			await expect(node.getByTestId('workflow-output-fields')).toContainText('Test art class');
		} finally { release(); }
	});
	// contract-test: direct surface=gui.web assertions=workflows-ui.mvp.authoring
	test('opens and inspects the Events Search capability schema', async ({
		page
	}: {
		page: Page;
	}) => {
		await page.goto(EVENTS_PREVIEW, { waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('component-preview-canvas')).toHaveAttribute(
			'data-preview-ready',
			'true',
			{ timeout: 30000 }
		);

		const eventsNode = page.locator('[data-node-id="events"]');
		await expect(eventsNode.getByTestId('workflow-node-title-label')).toHaveText('Events | Search');
		await expect(eventsNode.getByTestId('workflow-node-input-summary')).toHaveText('AI in Berlin');
		await expect(page.locator('[data-node-id="message"]').getByTestId('workflow-node-summary')).toContainText('New chat');
		await expect(page.locator('[data-node-id="message"]').getByTestId('workflow-node-summary')).not.toContainText('for each run');

		await eventsNode.getByTestId('workflow-node-summary').click();
		const editor = eventsNode.getByTestId('workflow-node-expanded');
		await expect(editor).toBeVisible();
		await expect(editor.locator('.title strong')).toHaveText('Events | Search');
		await expect(editor.getByTestId('workflow-input-heading')).toContainText('Input');
		await expect(editor.getByText('Requests *', { exact: true })).toHaveCount(0);
		await expect(editor.getByRole('button', { name: 'Add item' })).toHaveCount(0);
		await expect(editor.getByLabel('Query', { exact: true })).toHaveValue('AI');
		await expect(editor.locator('.schema-field .field-name svg').first()).toBeVisible();
		await expect(editor.getByTestId('workflow-node-location-picker')).toContainText('Berlin');
		await expect(editor.getByTestId('workflow-test-action').locator('.credits-coin-icon')).toHaveCSS('mask-image', /url\(/);
		await expect(editor.getByTestId('workflow-test-action')).toContainText('30');
		await expect(editor.getByTestId('workflow-test-action')).not.toContainText('Variable cost');
		await expect(editor.getByTestId('workflow-schema-field-date-range')).toHaveCount(0);
		await expect(editor.getByLabel('Event Type')).toHaveCount(0);

		const showAll = editor.getByTestId('workflow-show-all-fields');
		await expect(showAll).toHaveAttribute('aria-expanded', 'false');
		await showAll.click();
		await expect(showAll).toHaveAttribute('aria-expanded', 'true');
		await expect(editor.getByTestId('workflow-schema-field-date-range')).toBeVisible();
		await expect(editor.getByRole('combobox', { name: 'Event Type', exact: true })).toBeVisible();

		const outputToggle = editor.getByTestId('workflow-show-output-fields');
		await expect(outputToggle).toHaveAttribute('aria-expanded', 'false');
		await expect(editor.getByTestId('workflow-output-heading')).toHaveCount(0);
		await outputToggle.click();
		await expect(outputToggle).toHaveAttribute('aria-expanded', 'true');
		await expect(editor.getByTestId('workflow-output-heading')).toContainText('Output');
		await expect(editor.getByTestId('workflow-output-field')).toHaveCount(1);
		await expect(editor.getByTestId('workflow-output-fields').locator('.output-name svg')).toHaveCount(1);
		await expect(editor.getByTestId('workflow-output-fields')).not.toContainText('Summary');
		const listDisclosure = editor.getByTestId('workflow-output-list-disclosure');
		await expect(listDisclosure).toHaveAttribute('aria-expanded', 'false');
		await listDisclosure.click();
		const listDetails = editor.getByTestId('workflow-output-list-details');
		await expect(listDetails).toContainText('AI community meetup');
		await expect(listDetails).toContainText('Date Start');
		await expect(listDetails).not.toContainText('Description');
		await listDetails.getByTestId('workflow-output-list-show-all').click();
		await expect(listDetails).toContainText('Description');
		const eventUrl = listDetails.getByRole('link', {
			name: 'https://example.invalid/events/ai'
		});
		await expect(eventUrl).toHaveAttribute('href', 'https://example.invalid/events/ai');
		await editor.getByTestId('workflow-output-show-all').click();
		await expect(editor.getByTestId('workflow-output-field')).toHaveCount(3);
		await expect(editor.getByTestId('workflow-output-fields')).toContainText('Provider');

		await editor.locator('.close-button').click();
		const messageNode = page.locator('[data-node-id="message"]');
		await messageNode.getByTestId('workflow-node-summary').click();
		const messageEditor = messageNode.getByTestId('workflow-node-expanded');
		const sources = messageEditor.getByTestId('workflow-variable-sources');
		await expect(sources).toBeVisible();
		const sourceScroll = messageEditor.getByTestId('workflow-variable-source-scroll');
		await expect(sourceScroll).toHaveCSS('flex-wrap', 'nowrap');
		await expect(sourceScroll).toHaveCSS('overflow-x', 'auto');
		await sources.locator('[data-source-node-id="events"]').click();
		const variables = messageEditor.getByTestId('workflow-ai-suggestions');
		const basicCount = await variables.locator('[data-variable-reference]').count();
		expect(basicCount).toBeGreaterThan(0);
		await variables.getByRole('button', { name: 'Show all', exact: true }).click();
		expect(await variables.locator('[data-variable-reference]').count()).toBeGreaterThan(basicCount);
	});

	// contract-test: direct surface=gui.web assertions=workflows-ui.mvp.authoring
	test('inserts previous outputs from variable chips into app skill scalar inputs', async ({
		page
	}: {
		page: Page;
	}) => {
		const props = encodeURIComponent(JSON.stringify({ graph: VARIABLE_INPUT_GRAPH, capabilityFixtures: [VARIABLE_INPUT_CAPABILITY, VARIABLE_SOURCE_CAPABILITY] }));
		await page.goto(`${EVENTS_PREVIEW}&props=${props}`, { waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('component-preview-canvas')).toHaveAttribute(
			'data-preview-ready',
			'true',
			{ timeout: 30000 }
		);

		const eventsNode = page.locator('[data-node-id="events"]');
		await eventsNode.getByTestId('workflow-node-summary').click();
		const editor = eventsNode.getByTestId('workflow-node-expanded');
		const query = editor.getByTestId('workflow-input-template-events-request-0-query');
		const chips = editor.getByTestId('workflow-input-variable-chips-events-request-0-query');
		await expect(query).toHaveAttribute('aria-multiline', 'false');
		await expect(query.locator('.generic-mention')).toHaveText('@fixture.places.title');
		await expect(query.locator('.generic-mention')).toHaveAttribute('title', 'Example place lookup · Title');
		await expect(query.locator('.workflow-mention-icon')).toBeVisible();
		await expect(query).not.toContainText('$nodes');
		await expect(query).not.toContainText('{{steps');
		await expect(chips).toBeVisible();
		await expect(chips).toHaveCSS('flex-wrap', 'nowrap');
		await expect(chips).toHaveCSS('overflow-x', 'auto');
		await expect(editor.locator('select[aria-label="Use previous output Query"]')).toHaveCount(0);

		await query.press('Home');
		await chips.getByRole('button', { name: '+ Example place lookup · Provider', exact: true }).click();
		await expect(query.locator('.generic-mention')).toHaveCount(2);
		await expect(query.locator('.generic-mention').first()).toHaveText('@fixture.places.provider');
		await expect(query.locator('.generic-mention').last()).toHaveText('@fixture.places.title');

		const basicCount = await chips.getByRole('button').count();
		const variableToggle = chips.locator('..').locator('.variable-toggle');
		await variableToggle.click();
		await expect(variableToggle).toHaveAttribute('aria-expanded', 'true');
		expect(await chips.getByRole('button').count()).toBeGreaterThan(basicCount);
		await expect(query.locator('.generic-mention')).toHaveCount(2);
		await expect(query).not.toContainText('{{steps');

		const locationChips = editor.getByTestId('workflow-input-variable-chips-events-request-0-location');
		await expect(locationChips.getByRole('button', { name: '+ Example place lookup · City', exact: true })).toBeVisible();
		await expect(locationChips.getByRole('button', { name: /Provider|Title/ })).toHaveCount(0);
		const locationToggle = locationChips.locator('..').getByRole('button', { name: 'Show all variables' });
		await locationToggle.click();
		await expect(locationChips.getByRole('button', { name: '+ Example place lookup · Address', exact: true })).toBeVisible();
		await expect(locationChips.getByRole('button', { name: /Provider|Title/ })).toHaveCount(0);

		await editor.getByTestId('workflow-show-all-fields').click();
		await expect(editor.getByRole('combobox', { name: 'Event Type', exact: true })).toBeVisible();
		await expect(editor.getByTestId('workflow-input-variable-chips-events-request-0-event_type')).toHaveCount(0);
	});
});
