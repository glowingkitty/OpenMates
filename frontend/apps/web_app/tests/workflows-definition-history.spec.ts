/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Workflow definition-history deployed red contract for TASK-16.
 *
 * Creates an owner-scoped Workflow through the authenticated dev API, then
 * creates retained definitions through the deployed editor. It requires the
 * approved horizontal, scrollable timeline direction at laptop and phone
 * viewports while keeping a selected historical graph read-only and current
 * history immutable. Cleanup deletes only this run's Workflow.
 */
export {};

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

const IS_PROOF_CAPTURE = Boolean(process.env.PLAYWRIGHT_VIDEO_WIDTH && process.env.PLAYWRIGHT_VIDEO_HEIGHT);
const PROOF_DEVICE = Number.parseInt(process.env.PLAYWRIGHT_VIDEO_WIDTH || '', 10) === 390 ? 'web-phone' : 'web-laptop';
const LAPTOP_VIEWPORT = { width: 1440, height: 900 };
const PHONE_VIEWPORT = { width: 390, height: 844 };
const VERSION_COUNT = 8;

const WORKFLOW_DEFINITION_HISTORY_PROOF = defineVideoProof({
	id: 'workflows-definition-history',
	title: 'Workflow definition history stays readable and immutable',
	surface: 'web',
	devices: ['web-laptop', 'web-phone'],
	domain: 'app.dev.openmates.org',
	transcript: [
		{
			id: 'timeline-visible',
			text: 'Workflow definition history presents multiple retained versions on a scrollable horizontal timeline without clipping the active definition.',
			checkpoint: 'timeline-visible',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'historical-definition-visible',
			text: 'Selecting an earlier definition opens the same graph in read-only mode while the current Active version remains unchanged.',
			checkpoint: 'historical-definition-visible',
			devices: ['web-laptop', 'web-phone']
		}
	],
	assertions: [
		{
			id: 'timeline-visible.assertion',
			checkpoint: 'timeline-visible',
			visual: 'The horizontal definition timeline has an available scroll range, retained version markers, and an untruncated Active marker.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'historical-definition-visible.assertion',
			checkpoint: 'historical-definition-visible',
			visual: 'The selected older definition is visibly read-only and the unchanged current Active version remains visible without horizontal page overflow.',
			devices: ['web-laptop', 'web-phone']
		}
	],
	tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 }
});

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

function weatherGraph(location: string) {
	return {
		version: 1,
		trigger_node_id: 'trigger',
		nodes: [
			{ id: 'trigger', type: 'schedule_trigger', title: 'Every morning', config: { schedule: { type: 'daily', time: '07:00', timezone: 'Europe/Berlin' } } },
			{ id: 'weather', type: 'app_skill_action', title: 'Check weather', config: { app_id: 'weather', skill_id: 'forecast', input: { location, days: 1 } } },
			{ id: 'end', type: 'end', title: 'Done', config: {} }
		],
		edges: [
			{ from: 'trigger', to: 'weather' },
			{ from: 'weather', to: 'end' }
		]
	};
}

async function expectNoPageOverflow(page: any): Promise<void> {
	await expect.poll(async () => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
}

test.describe('Workflow definition history', () => {
	// contract-test: direct surface=gui.web assertions=workflows-ui.versions.timeline-readonly-restore-new,workflows-ui.responsive-accessible-reachable
	test('retains a scrollable immutable definition timeline at laptop and phone sizes', async ({ page }: { page: any }, testInfo: any) => {
		test.setTimeout(300_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:workflows']);

		const apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
		const title = `Definition history ${Date.now()}-${testInfo.workerIndex}`;
		let workflowId: string | null = null;
		const proof = IS_PROOF_CAPTURE
			? createVideoProofRuntime(WORKFLOW_DEFINITION_HISTORY_PROOF, {
				device: PROOF_DEVICE,
				attach: testInfo.attach.bind(testInfo),
				captureFrame: () => page.screenshot({ type: 'png' })
			})
			: null;

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page);

		try {
			const createResponse = await page.request.post(`${apiUrl}/v1/workflows`, {
				data: { title, description: 'TASK-16 definition-history contract.', graph: weatherGraph('Berlin'), enabled: false, run_content_retention: 'last_5' }
			});
			expect(createResponse.ok(), await createResponse.text()).toBe(true);
			workflowId = (await createResponse.json()).workflow.id;

			await page.setViewportSize(LAPTOP_VIEWPORT);
			await page.goto(getE2EDebugUrl(`/workflows#workflow-id=${workflowId}&workflow-tab=details`), { waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('workflow-graph-renderer')).toBeVisible({ timeout: 30_000 });

			const weatherNode = page.getByTestId('workflow-node-card').filter({ hasText: 'Weather' }).first();
			for (let version = 2; version <= VERSION_COUNT; version += 1) {
				const locationInput = weatherNode.getByTestId('workflow-node-location-input');
				if (!(await locationInput.isVisible().catch(() => false))) await weatherNode.getByTestId('workflow-node-summary').click();
				await locationInput.fill(`History city ${version}`);
				const saveResponse = page.waitForResponse(
					(response: any) => response.url().endsWith(`/v1/workflows/${workflowId}`) && response.request().method() === 'PATCH' && response.ok(),
					{ timeout: 30_000 }
				);
				await page.getByTestId('save-workflow').click();
				await saveResponse;
				await expect(page.getByTestId('save-workflow')).toHaveCount(0, { timeout: 30_000 });
			}

			const timeline = page.getByTestId('workflow-version-timeline');
			await expect(timeline).toBeVisible();
			await expect(page.getByTestId('workflow-version-row')).toHaveCount(VERSION_COUNT);
			await expect.poll(async () => timeline.evaluate((element: HTMLElement) => element.scrollWidth > element.clientWidth)).toBe(true);
			const currentVersion = page.locator('[data-testid="workflow-version-row"][data-current="true"]');
			await expect(currentVersion).toHaveCount(1);
			const currentVersionNumber = await currentVersion.getAttribute('data-version-number');
			const timelineBeforeInspection = await timeline.innerText();
			await expectNoPageOverflow(page);

			if (proof && PROOF_DEVICE === 'web-laptop') {
				await proof.assert('timeline-visible.assertion', async () => {
					await expect(timeline).toBeVisible();
					await expect(currentVersion).toContainText('Active');
				});
				await proof.checkpoint('timeline-visible');
			}

			const historicalVersion = page.locator('[data-testid="workflow-version-row"][data-current="false"]').first();
			await historicalVersion.click();
			await expect(page.getByTestId('workflow-version-graph-inspection')).toHaveAttribute('data-read-only', 'true');
			await expect(page.getByTestId('workflow-version-graph')).toBeVisible({ timeout: 30_000 });
			await expect(page.getByTestId('workflow-version-graph').getByTestId('workflow-node-location-input')).toHaveCount(0);
			await expect(currentVersion).toHaveAttribute('data-version-number', currentVersionNumber ?? '');
			await expect(currentVersion).toContainText('Active');
			expect(await timeline.innerText()).toBe(timelineBeforeInspection);
			await expectNoPageOverflow(page);

			if (proof && PROOF_DEVICE === 'web-laptop') {
				await proof.assert('historical-definition-visible.assertion', async () => {
					await expect(page.getByTestId('workflow-version-graph')).toBeVisible();
					await expect(currentVersion).toContainText('Active');
				});
				await proof.checkpoint('historical-definition-visible');
			}

			await page.setViewportSize(PHONE_VIEWPORT);
			await expect(timeline).toBeVisible();
			await expect.poll(async () => timeline.evaluate((element: HTMLElement) => element.scrollWidth > element.clientWidth)).toBe(true);
			await expect(page.getByTestId('workflow-version-graph-inspection')).toHaveAttribute('data-read-only', 'true');
			await expect(currentVersion).toContainText('Active');
			await expectNoPageOverflow(page);

			if (proof && PROOF_DEVICE === 'web-phone') {
				await proof.assert('timeline-visible.assertion', async () => {
					await expect(timeline).toBeVisible();
					await expect(currentVersion).toContainText('Active');
				});
				await proof.checkpoint('timeline-visible');
				await proof.assert('historical-definition-visible.assertion', async () => {
					await expect(page.getByTestId('workflow-version-graph')).toBeVisible();
					await expect(currentVersion).toContainText('Active');
				});
				await proof.checkpoint('historical-definition-visible');
			}

			if (proof) await proof.attach();
		} finally {
			if (workflowId) await page.request.delete(`${apiUrl}/v1/workflows/${encodeURIComponent(workflowId)}`).catch(() => null);
		}
	});
});
