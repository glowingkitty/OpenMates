/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Workflows web UI product-contract coverage.
 *
 * Seeds owner-scoped Workflow records through the real dev API, then verifies
 * the deployed workspace, guarded Template editor, immutable versions, and
 * cancellable run detail at the required laptop and phone proof viewports.
 * Every created Workflow is deleted during cleanup.
 */
import type { Page } from '@playwright/test';
export {};

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { captureTestThumbnail, defineTestThumbnail } = require('./helpers/test-thumbnail');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

const IS_PROOF_CAPTURE = Boolean(
	process.env.PLAYWRIGHT_VIDEO_WIDTH && process.env.PLAYWRIGHT_VIDEO_HEIGHT
);
const PROOF_DEVICE =
	Number.parseInt(process.env.PLAYWRIGHT_VIDEO_WIDTH || '', 10) === 390
		? 'web-phone'
		: 'web-laptop';
const PROOF_STATE_SETTLE_MS = 750;
const PROOF_TEMPLATE_HOLD_MS = 2500;
const WORKFLOW_TITLE_PREFIX = 'Workflow UI contract';
const WORKFLOWS_UI_THUMBNAIL = defineTestThumbnail({
	id: 'workflows-workspace',
	focus: [{ testId: 'daily-inspiration-banner' }],
	context: [{ testId: 'workflows-show-all' }, { testId: 'workflow-input-composer' }]
});

const WORKFLOWS_UI_PROOF = defineVideoProof({
	id: 'workflows-ui-contract',
	title: 'Workflows workspace, Template, versions, and Runs',
	surface: 'web',
	devices: ['web-laptop', 'web-phone'],
	domain: 'app.dev.openmates.org',
	transcript: [
		{
			id: 'workspace-visible',
			text: 'The Workflows screen presents recommendation-led creation, category-styled cards, browse controls, and a bottom composer.',
			checkpoint: 'workspace-visible',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'template-visible',
			text: 'The selected Workflow keeps its category identity above shared Template and Runs tabs and a centered editable graph.',
			checkpoint: 'template-visible',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'guard-visible',
			text: 'Editing a node reveals its own Save control. Saving persists the workflow immediately.',
			checkpoint: 'guard-visible',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'version-visible',
			text: 'Immutable versions appear on a horizontal timeline and historical definitions reuse the same read-only graph.',
			checkpoint: 'version-visible',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'runs-visible',
			text: 'Runs presents a status timeline and the selected execution graph with retained node detail and contextual cancellation.',
			checkpoint: 'runs-visible',
			devices: ['web-laptop', 'web-phone']
		}
	],
	assertions: [
		{
			id: 'workspace-visible.assertion',
			checkpoint: 'workspace-visible',
			visual:
				'The recommendation, centered Workflow identity, category cards, Show all, Search, and composer are visible without clipping.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'template-visible.assertion',
			checkpoint: 'template-visible',
			visual:
				'The category header, shared tab pill, and centered Template graph form one stable detail composition.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'guard-visible.assertion',
			checkpoint: 'guard-visible',
			visual:
				'The expanded node and its Save control remain reachable without a workflow-wide save banner.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'version-visible.assertion',
			checkpoint: 'version-visible',
			visual:
				'The selected historical version, Active current marker, timeline, and read-only graph are visible.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'runs-visible.assertion',
			checkpoint: 'runs-visible',
			visual:
				'The waiting run, execution graph, node statuses, and cancel action are visible without raw protocol text.',
			devices: ['web-laptop', 'web-phone']
		}
	],
	tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 }
});

function deriveApiUrl(baseUrl: string): string {
	try {
		const url = new URL(baseUrl);
		if (url.hostname === 'openmates.org' || url.hostname === 'www.openmates.org')
			return 'https://api.openmates.org';
		if (url.hostname.startsWith('app.')) return `${url.protocol}//api.${url.hostname.slice(4)}`;
		if (url.hostname === 'localhost') return 'http://localhost:8000';
	} catch {
		// Fall through to the production API default.
	}
	return 'https://api.openmates.org';
}

function rainGraph(location: string) {
	return {
		version: 1,
		trigger_node_id: 'trigger',
		nodes: [
			{
				id: 'trigger',
				type: 'schedule_trigger',
				title: 'Every morning',
				config: { schedule: { type: 'daily', time: '07:00', timezone: 'Europe/Berlin' } }
			},
			{
				id: 'weather',
				type: 'app_skill_action',
				title: 'Check weather',
				config: { app_id: 'weather', skill_id: 'forecast', input: { location, days: 1 } }
			},
			{ id: 'end', type: 'end', title: 'Done', config: {} }
		],
		edges: [
			{ from: 'trigger', to: 'weather' },
			{ from: 'weather', to: 'end' }
		]
	};
}

function waitingGraph() {
	return {
		version: 1,
		trigger_node_id: 'manual',
		nodes: [
			{ id: 'manual', type: 'manual_trigger', title: 'Manual start', config: {} },
			{
				id: 'approval',
				type: 'ask_user',
				title: 'Confirm the next step',
				config: { prompt: 'Continue this Workflow?', timeout_seconds: 600 }
			},
			{ id: 'notify', type: 'send_notification', title: 'Show result', config: { title: 'Ready', body: 'Ready' } },
			{ id: 'end', type: 'end', title: 'Done', config: {} }
		],
		edges: [
			{ from: 'manual', to: 'approval' },
			{ from: 'approval', to: 'notify' },
			{ from: 'notify', to: 'end' }
		]
	};
}

function workflowDetailsHashUrlPattern(workflowId: string): RegExp {
	return new RegExp(`/#(?:[^#]*&)?workflow-id=${workflowId}&workflow-tab=details(?:&|$)`);
}

async function settleProofState(page: any, durationMs = PROOF_STATE_SETTLE_MS): Promise<void> {
	if (IS_PROOF_CAPTURE) await page.waitForTimeout(durationMs);
}

async function createWorkflow(page: any, apiUrl: string, data: Record<string, unknown>) {
	const response = await page.request.post(`${apiUrl}/v1/workflows`, { data });
	expect(response.ok(), await response.text()).toBe(true);
	return (await response.json()).workflow;
}

async function expectNoPageOverflow(page: any): Promise<void> {
	await expect
		.poll(async () =>
			page.evaluate(
				() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1
			)
		)
		.toBe(true);
}

test.describe('Workflows web UI contract', () => {
	// contract-test: supporting surface=gui.web assertions=workflows-ui.workspace.recommendation-led-composition,workflows-ui.detail.shared-template-runs-tabs
	test('opens an externally created workflow from a fresh cached empty list', async ({ page }: { page: any }, testInfo: any) => {
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:workflows']);
		const apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
		const title = `${WORKFLOW_TITLE_PREFIX} external ${Date.now()}-${testInfo.workerIndex}`;
		let workflowId: string | null = null;
		let listReads = 0;

		await page.route('**/v1/workflows', (route: any) => {
			if (route.request().method() !== 'GET') return route.continue();
			listReads += 1;
			return listReads === 1
				? route.fulfill({ json: { workflows: [] } })
				: route.continue();
		});
		const initialList = page.waitForResponse((response: any) =>
			response.url().endsWith('/v1/workflows') && response.request().method() === 'GET'
		);
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page);

		try {
			await page.goto(getE2EDebugUrl('/#workflows'), { waitUntil: 'domcontentloaded' });
			expect((await initialList).ok()).toBe(true);
			await expect(page.getByTestId('workflows-start-screen')).toBeVisible();
			expect(listReads).toBe(1);

			const workflow = await createWorkflow(page, apiUrl, {
				title,
				graph: rainGraph('Berlin'),
				enabled: false,
				run_content_retention: 'last_5'
			});
			workflowId = workflow.id;
			await page.evaluate((id: string) => {
				window.location.hash = `#workflow-id=${id}&workflow-tab=details`;
			}, workflow.id);
			await expect(page).toHaveURL(workflowDetailsHashUrlPattern(workflow.id));
			await expect(page.getByTestId('workflow-template-panel')).toBeVisible();
			await expect(page.getByTestId('workspace-detail-title')).toHaveText(title);
			expect(listReads).toBeGreaterThanOrEqual(2);
		} finally {
			if (workflowId) await page.request.delete(`${apiUrl}/v1/workflows/${encodeURIComponent(workflowId)}`).catch(() => null);
		}
	});

	// contract-test: supporting surface=gui.web assertions=workflows-ui.detail.shared-template-runs-tabs,workflows-ui.template.explicit-guarded-save,workflows-ui.runs.timeline-execution-detail
	test('opens Template before slow Runs and keeps an unsaved draft through refresh', async ({ page }: { page: any }, testInfo: any) => {
		test.setTimeout(120_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:workflows']);
		const apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
		const title = `${WORKFLOW_TITLE_PREFIX} refresh ${Date.now()}-${testInfo.workerIndex}`;
		let workflowId: string | null = null;
		let releaseRuns!: () => void;
		let releaseDraftDetail!: () => void;
		let releaseDetail!: () => void;
		const runsGate = new Promise<void>(resolve => { releaseRuns = resolve; });
		const draftDetailGate = new Promise<void>(resolve => { releaseDraftDetail = resolve; });
		const detailGate = new Promise<void>(resolve => { releaseDetail = resolve; });

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page);
		try {
			const workflow = await createWorkflow(page, apiUrl, {
				title,
				graph: rainGraph('Berlin'),
				enabled: false,
				run_content_retention: 'last_5'
			});
			workflowId = workflow.id;
			const runsPath = `/v1/workflows/${encodeURIComponent(workflow.id)}/runs`;
			const detailPath = `/v1/workflows/${encodeURIComponent(workflow.id)}`;
			await page.route(`**${runsPath}`, async (route: any) => {
				await runsGate;
				await route.continue();
			});

			await page.goto(getE2EDebugUrl('/workflows'), { waitUntil: 'domcontentloaded' });
			const runsRequest = page.waitForRequest((request: any) => request.url().endsWith(runsPath));
			await page.getByTestId('workflow-landing-card').filter({ hasText: title }).first().click();
			await runsRequest;
			await expect(page.getByTestId('workflow-template-panel')).toBeVisible();
			await expect(page.getByTestId('workflow-graph-renderer')).toBeVisible();
			releaseRuns();
			const externalUpdate = await page.request.patch(`${apiUrl}${detailPath}`, {
				data: { graph: rainGraph('Hamburg') }
			});
			expect(externalUpdate.ok(), await externalUpdate.text()).toBe(true);
			const cleanRefresh = page.waitForResponse((response: any) =>
				response.url().endsWith(detailPath) && response.request().method() === 'GET'
			);
			await page.evaluate(() => {
				const originalNow = Date.now.bind(Date);
				Date.now = () => originalNow() + 61_000;
				window.dispatchEvent(new Event('focus'));
			});
			expect((await cleanRefresh).ok()).toBe(true);
			await expect(page.getByTestId('workflow-node-input-summary')).toHaveText('Hamburg');
			await expect(page.getByTestId('workflow-version-selector')).toContainText('Version 2');

			await page.route(`**${detailPath}`, async (route: any) => {
				await draftDetailGate;
				await route.continue();
			});
			const draftRefreshRequest = page.waitForRequest((request: any) => request.url().endsWith(detailPath));
			await page.evaluate(() => {
				const originalNow = Date.now.bind(Date);
				Date.now = () => originalNow() + 61_000;
				window.dispatchEvent(new Event('focus'));
			});
			await draftRefreshRequest;
			await page.getByTestId('workflow-node-summary').filter({ hasText: 'Hamburg' }).click();
			const nodeDraft = page.getByTestId('workflow-node-expanded');
			await expect(nodeDraft).toBeVisible();
			const secondExternalUpdate = await page.request.patch(`${apiUrl}${detailPath}`, {
				data: { graph: rainGraph('Paris') }
			});
			expect(secondExternalUpdate.ok(), await secondExternalUpdate.text()).toBe(true);
			const draftRefreshResponse = page.waitForResponse((response: any) =>
				response.url().endsWith(detailPath) && response.request().method() === 'GET'
			);
			releaseDraftDetail();
			expect((await draftRefreshResponse).ok()).toBe(true);
			await expect(nodeDraft).toBeVisible();
			await nodeDraft.locator('button.close-button').click();
			await expect(page.getByTestId('workflow-node-input-summary')).toHaveText('Paris');
			await expect(page.getByTestId('workflow-version-selector')).toContainText('Version 3');

			await page.route(`**${detailPath}`, async (route: any) => {
				await detailGate;
				await route.continue();
			});
			const refreshRequest = page.waitForRequest((request: any) => request.url().endsWith(detailPath));
			await page.evaluate(() => {
				const originalNow = Date.now.bind(Date);
				Date.now = () => originalNow() + 61_000;
				window.dispatchEvent(new Event('focus'));
			});
			await refreshRequest;
			await page.getByTestId('workspace-detail-title').click();
			const draftTitle = `${title} unsaved`;
			const titleInput = page.locator('.workflow-detail-header form input').first();
			await titleInput.fill(draftTitle);
			releaseDetail();
			await expect(titleInput).toHaveValue(draftTitle);
			await page.getByTestId('workflow-detail-back').click();
			await expect(page.getByTestId('workflow-unsaved-guard')).toBeVisible();
		} finally {
			releaseRuns();
			releaseDraftDetail();
			releaseDetail();
			if (workflowId) await page.request.delete(`${apiUrl}/v1/workflows/${encodeURIComponent(workflowId)}`).catch(() => null);
		}
	});

	// contract-test: direct surface=gui.web assertions=workflows-ui.workspace.recommendation-led-composition,workflows-ui.workspace.title-first-draft,workflows-ui.detail.stable-visual-header,workflows-ui.detail.shared-template-runs-tabs,workflows-ui.template.centered-in-place-editor,workflows-ui.template.explicit-guarded-save,workflows-ui.versions.timeline-readonly-restore-new,workflows-ui.runs.timeline-execution-detail,workflows-ui.responsive-accessible-reachable
	test('preserves identity while editing versions and inspecting a cancellable run', async ({
		page
	}: { page: any }, testInfo: any) => {
		test.setTimeout(300_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:workflows']);

		const apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
		const createdWorkflowIds = new Set<string>();
		const suffix = `${Date.now()}-${testInfo.workerIndex}`;
		const editorTitle = `${WORKFLOW_TITLE_PREFIX} weather ${suffix}`;
		const runnerTitle = `${WORKFLOW_TITLE_PREFIX} approval ${suffix}`;
		const proof = IS_PROOF_CAPTURE
			? createVideoProofRuntime(WORKFLOWS_UI_PROOF, {
					device: PROOF_DEVICE,
					attach: testInfo.attach.bind(testInfo),
					captureFrame: () => page.screenshot({ type: 'png' })
				})
			: null;

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page);

		try {
			const editorWorkflow = await createWorkflow(page, apiUrl, {
				title: editorTitle,
				description: 'A daily weather check for the commute.',
				graph: rainGraph('Berlin'),
				enabled: false,
				run_content_retention: 'last_5'
			});
			createdWorkflowIds.add(editorWorkflow.id);
			expect(editorWorkflow.category).toBe('science');
			expect(editorWorkflow.icon).toBe('cloud-rain');

			const versionResponse = await page.request.patch(
				`${apiUrl}/v1/workflows/${encodeURIComponent(editorWorkflow.id)}`,
				{
					data: { graph: rainGraph('Hamburg') }
				}
			);
			expect(versionResponse.ok(), await versionResponse.text()).toBe(true);

			const runnerWorkflow = await createWorkflow(page, apiUrl, {
				title: runnerTitle,
				description: 'A manual approval Workflow.',
				graph: waitingGraph(),
				enabled: false,
				run_content_retention: 'last_5',
				category: 'general_knowledge',
				icon: 'help-circle'
			});
			createdWorkflowIds.add(runnerWorkflow.id);

			const runResponse = await page.request.post(
				`${apiUrl}/v1/workflows/${encodeURIComponent(runnerWorkflow.id)}/run`,
				{
					data: { mode: 'test', input: {} },
					headers: { 'Idempotency-Key': `${runnerWorkflow.id}-ui-contract` }
				}
			);
			expect(runResponse.ok(), await runResponse.text()).toBe(true);
			const run = (await runResponse.json()).run;

			await page.goto(getE2EDebugUrl('/workflows'), { waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('workflows-start-screen')).toBeVisible({ timeout: 30_000 });
			await expect(page.getByTestId('daily-inspiration-banner')).toBeVisible();
			const workflowInspiration = page.getByTestId('daily-inspiration-banner');
			await expect(workflowInspiration.getByTestId('daily-inspiration-cta-text')).toHaveCount(0);
			await expect(workflowInspiration).not.toHaveAttribute('role', 'button');
			await expect(workflowInspiration).not.toHaveAttribute('tabindex', '0');
			await workflowInspiration.click();
			await workflowInspiration.dispatchEvent('keydown', { key: 'Enter', bubbles: true });
			await expect(page.getByTestId('workflow-input-textarea')).toHaveValue('');
			await expect(page.getByTestId('workflows-workspace-background-icon')).toBeVisible();
			await expect(page.getByTestId('workflows-show-all')).toHaveText('Show my workflows');
			await expect(page.getByTestId('workflows-show-templates')).toHaveText('Show templates');
			await expect(page.getByTestId('workflows-search')).toBeVisible();
			await expect(page.getByTestId('workflow-input-composer')).toBeVisible();
			const editorCard = page
				.getByTestId('workflow-landing-card')
				.filter({ hasText: editorTitle })
				.first();
			await expect(editorCard).toHaveAttribute('data-card-source', 'recent');
			await expect(editorCard).toHaveAttribute('data-category', 'science');
			await expect(editorCard).toHaveAttribute('data-icon', 'cloud-rain');
			const startScreenBox = await page.getByTestId('workflows-start-screen').boundingBox();
			if (!startScreenBox) throw new Error('Workflow start screen must be measurable.');
			const [bannerBox, composerBox] = await Promise.all([
				page.getByTestId('workflows-daily-inspiration-area').boundingBox(),
				page.getByTestId('workflow-input-composer').boundingBox()
			]);
			if (!bannerBox || !composerBox) throw new Error('Workflow banner and composer must be measurable.');
			const availableCardHeight = composerBox.y - (bannerBox.y + bannerBox.height);
			const shouldUseCompactCards = startScreenBox.width < 550 || availableCardHeight < 420;
			if (shouldUseCompactCards) {
				await expect(editorCard).toHaveClass(/resume-chat-card/);
				await expect(editorCard.locator('.resume-chat-kind-badge')).toHaveCount(0);
				await expect(editorCard.locator('.resume-chat-summary')).toHaveCount(0);
				await expect(editorCard.getByTestId('resume-chat-title')).toHaveCSS('white-space', 'nowrap');
			} else {
				await expect(editorCard).toHaveClass(/workspace-continue-card/);
				await expect(editorCard).toHaveAttribute('style', /#CE5B06.*#8F220E/);
			}
			const bannerBox = await page.getByTestId('daily-inspiration-banner').boundingBox();
			const centerBox = await page.getByTestId('workflows-workspace-center').boundingBox();
			if (!bannerBox || !centerBox) throw new Error('Workflow banner and start content must be measurable.');
			expect(centerBox.y).toBeGreaterThanOrEqual(bannerBox.y + bannerBox.height);
			await expectNoPageOverflow(page);
			await captureTestThumbnail(page, testInfo, WORKFLOWS_UI_THUMBNAIL);
			if (proof) {
				await settleProofState(page);
				await proof.assert('workspace-visible.assertion', async () => {
					await expect(editorCard).toBeVisible();
					await expect(page.getByTestId('workflows-search')).toBeVisible();
					await expect(page.getByTestId('workflow-input-composer')).toBeVisible();
				});
				await proof.checkpoint('workspace-visible');
				await settleProofState(page);
			}

			await editorCard.click();
			await expect(page).toHaveURL(workflowDetailsHashUrlPattern(editorWorkflow.id));
			const workflowManagement = page.getByTestId('workflow-management');
			await expect(workflowManagement).toHaveCSS('will-change', 'auto');
			await expect(workflowManagement).toHaveCSS('transform', 'none');
			const settingsMenu = page.getByTestId('settings-menu');
			const settingsHeader = settingsMenu.locator('.settings-main-header');
			const settingsHeaderOrbs = settingsHeader.locator('.orb');
			await expect(settingsHeader).toHaveAttribute('data-animation-state', 'paused');
			await expect(settingsHeaderOrbs).toHaveCount(3);
			for (let index = 0; index < 3; index += 1) {
				await expect(settingsHeaderOrbs.nth(index)).toHaveCSS('animation-play-state', 'paused');
				await expect(settingsHeaderOrbs.nth(index)).toHaveCSS('will-change', 'auto');
			}
			const detailHeader = page.getByTestId('workspace-detail-header');
			await expect(detailHeader).toHaveAttribute('data-category', 'science');
			await expect(detailHeader).toHaveAttribute('data-icon', 'cloud-rain');
			await expect(page.getByTestId('workflow-detail-actions')).toHaveCSS('position', 'sticky');
			await expect(page.getByTestId('workflow-identity-icon')).toBeVisible();
			await expect(page.getByTestId('workflow-tab-template')).toHaveAttribute(
				'aria-selected',
				'true'
			);
			await expect(page.getByTestId('workflow-tab-runs')).toHaveAttribute('aria-selected', 'false');
			await expect(page.getByTestId('workflow-template-panel')).toBeVisible();
			await expect(page.getByTestId('workflow-graph-renderer')).toHaveAttribute(
				'data-read-only',
				'false'
			);
			await expectNoPageOverflow(page);
			if (proof) {
				await settleProofState(page);
				await proof.assert('template-visible.assertion', async () => {
					await expect(detailHeader).toBeVisible();
					await expect(page.getByTestId('workflow-template-panel')).toBeVisible();
				});
				await proof.checkpoint('template-visible');
				await settleProofState(page, PROOF_TEMPLATE_HOLD_MS);
			}

			const weatherNode = page
				.getByTestId('workflow-node-card')
				.filter({ hasText: 'Weather' })
				.first();
			const primaryNodeIcons = page.getByTestId('workflow-node-primary-icon').locator('.workflow-icon');
			await expect.poll(async () => primaryNodeIcons.count()).toBeGreaterThan(1);
			for (let index = 0; index < (await primaryNodeIcons.count()); index += 1) {
				await expect(primaryNodeIcons.nth(index)).toHaveCSS('width', '33px');
				await expect(primaryNodeIcons.nth(index)).toHaveCSS('height', '33px');
			}
			await page.route('**/v1/geocode/search?**', (route) => {
				const query = new URL(route.request().url()).searchParams.get('q');
				const location = query === 'Hamburg'
					? {
						lat: '53.5511', lon: '9.9937', name: 'Hamburg', display_name: 'Hamburg, Germany',
						class: 'place', type: 'city', namedetails: { name: 'Hamburg' },
						address: { city: 'Hamburg', country: 'Germany' }
					}
					: query === 'Paris'
						? {
							lat: '48.8566', lon: '2.3522', name: 'Paris', display_name: 'Paris, France',
							class: 'place', type: 'city', namedetails: { name: 'Paris' },
							address: { city: 'Paris', country: 'France' }
						}
						: null;
				return route.fulfill({ status: location ? 200 : 400, json: location ? [location] : [] });
			});
			await weatherNode.getByTestId('workflow-node-summary').click();
			await expect(page.getByTestId('workflow-editor-primary-icon')).toHaveCSS('width', '40px');
			await expect(page.getByTestId('workflow-editor-primary-icon')).toHaveCSS('height', '40px');
			const initialSearch = page.waitForResponse(
				(response: any) => response.url().includes('/v1/geocode/search?') &&
					new URL(response.url()).searchParams.get('q') === 'Hamburg',
				{ timeout: 10_000 }
			);
			await weatherNode.getByTestId('workflow-node-location-picker').click();
			const initialResponse = await initialSearch;
			expect(initialResponse.ok()).toBe(true);
			await initialResponse.finished();
			const locationMap = weatherNode.getByTestId('workflow-location-map');
			const locationInput = locationMap.getByTestId('map-location-search-input');
			await expect(locationMap.getByTestId('map-location-select')).toBeVisible();
			await expect(locationInput).toHaveValue('');
			const parisSearch = page.waitForResponse(
				(response: any) => response.url().includes('/v1/geocode/search?') &&
					new URL(response.url()).searchParams.get('q') === 'Paris',
				{ timeout: 10_000 }
			);
			await locationInput.fill('Paris');
			const parisResponse = await parisSearch;
			expect(parisResponse.ok()).toBe(true);
			await parisResponse.finished();
			const parisResult = locationMap.getByTestId('map-location-search-result');
			await expect(parisResult).toContainText('Paris');
			await parisResult.click();
			await weatherNode.getByTestId('map-location-select').click();
			await expect(page.getByTestId('workflow-dirty-panel')).toHaveCount(0);
			await expect(page.getByTestId('workflow-node-save')).toBeVisible();
			if (proof) {
				await settleProofState(page);
				await proof.assert('guard-visible.assertion', async () => {
					await expect(page.getByTestId('workflow-node-save')).toBeVisible();
				});
				await proof.checkpoint('guard-visible');
			}
			await page.getByTestId('workflow-node-save').click();
			await expect(weatherNode.getByTestId('workflow-node-expanded')).toHaveCount(0);
			await expect(
				page.getByTestId('workflow-graph-renderer').getByTestId('workflow-node-stack')
			).toContainText('Paris');
			await expect(page.getByTestId('save-workflow')).toHaveCount(0);
			await expect(page.getByTestId('workflow-more-options')).toHaveCount(0);
			await page.getByTestId('workflow-version-selector').click();

			await expect(page.getByTestId('workflow-version-selector')).toBeVisible();
			await expect(page.getByTestId('workflow-version-timeline')).toBeVisible();
			const versionPanel = page.getByTestId('workflow-template-panel');
			await expect(versionPanel.getByTestId('workflow-version-timeline')).toBeVisible();
			const tabBounds = await page.getByTestId('workflow-view-tabs').boundingBox();
			const selectorBounds = await page.getByTestId('workflow-version-selector').boundingBox();
			expect(selectorBounds.y).toBeGreaterThanOrEqual(tabBounds.y + tabBounds.height);
			expect(await page.getByTestId('workflow-version-row').evaluateAll(rows =>
				rows.every(row => [...row.children].every(label =>
					label.getBoundingClientRect().bottom <= row.getBoundingClientRect().bottom + 1
				))
			)).toBe(true);
			const historicalVersion = page
				.locator('[data-testid="workflow-version-row"][data-current="false"]')
				.first();
			await historicalVersion.click();
			await expect(page.getByTestId('workflow-version-graph-inspection')).toBeVisible();
			await expect(page.getByTestId('workflow-version-graph-inspection')).toHaveAttribute(
				'data-read-only',
				'true'
			);
			await expect(page.getByTestId('workflow-version-graph')).toBeVisible({ timeout: 30_000 });
			await expect(page.getByTestId('workflow-version-graph-inspection')).not.toContainText(
				'app_id'
			);
			await expect(
				page.locator('[data-testid="workflow-version-row"][data-current="true"]')
			).toContainText(/current|active/i);
			if (proof) {
				await settleProofState(page);
				await proof.assert('version-visible.assertion', async () => {
					await expect(page.getByTestId('workflow-version-timeline')).toBeVisible();
					await expect(page.getByTestId('workflow-version-graph')).toBeVisible();
				});
				await proof.checkpoint('version-visible');
				await settleProofState(page);
			}

			await page.getByTestId('workflow-detail-back').click();
			await expect(page.getByTestId('workflows-start-screen')).toBeVisible();
			await page
				.getByTestId('workflow-landing-card')
				.filter({ hasText: runnerTitle })
				.first()
				.click();
			await expect(page).toHaveURL(workflowDetailsHashUrlPattern(runnerWorkflow.id));
			await expect(page.getByTestId('workflow-detail-actions').getByRole('toolbar')).toBeVisible();
			await page.getByTestId('workflow-detail-actions').getByRole('button', { name: 'More', exact: true }).click();
			await expect(page.getByTestId('run-workflow')).toBeVisible();
			await page.getByTestId('workflow-tab-runs').click();
			await expect(page).toHaveURL(
				new RegExp(`workflow-id=${runnerWorkflow.id}&workflow-tab=runs`)
			);
			await expect(page.getByTestId('workflow-run-selector')).toBeVisible();
			await expect(page.getByTestId('workflow-run-selector').locator('select')).toHaveValue(run.id);
			await expect(page.getByTestId('workflow-delete-run')).toHaveAttribute('title', /Delete run/);
			await expect(page.getByTestId('workflow-run-timeline')).toBeVisible();
			const selectedRun = page.locator(
				`[data-testid="workflow-run-marker"][data-run-id="${run.id}"]`
			);
			await expect(selectedRun).toContainText(/waiting/i);
			await expect
				.poll(async () =>
					selectedRun.evaluate((element: HTMLElement) => {
						const marker = element.getBoundingClientRect();
						const status = element.querySelector('strong')?.getBoundingClientRect();
						return Boolean(status && status.top >= marker.top && status.bottom <= marker.bottom);
					})
				)
				.toBe(true);
			await selectedRun.click();
			await expect(page.getByTestId('workflow-run-detail')).toBeVisible();
			await expect(page.getByTestId('workflow-run-graph')).toHaveAttribute(
				'data-read-only',
				'true'
			);
			await expect(page.getByTestId('workflow-run-node-status').first()).toHaveAttribute(
				'aria-label',
				/^(queued|running|completed|waiting|skipped|failed)$/i
			);
			await expect(page.getByTestId('workflow-run-cancel')).toBeVisible();
			if (proof) {
				await settleProofState(page);
				await proof.assert('runs-visible.assertion', async () => {
					await expect(page.getByTestId('workflow-run-timeline')).toBeVisible();
					await expect(page.getByTestId('workflow-run-detail')).toBeVisible();
					await expect(page.getByTestId('workflow-run-cancel')).toBeVisible();
				});
				await proof.checkpoint('runs-visible');
				await settleProofState(page);
			}

			await page.getByTestId('workflow-run-cancel').click();
			await expect(page.getByTestId('workflow-run-cancel-confirmation')).toBeVisible();
			await expect
				.poll(async () =>
					page.evaluate(() =>
						Boolean(
							document.activeElement?.closest('[data-testid="workflow-run-cancel-confirmation"]')
						)
					)
				)
				.toBe(true);
			const cancelResponse = page.waitForResponse(
				(response: any) =>
					response.url().endsWith(`/runs/${run.id}/cancel`) &&
					response.request().method() === 'POST' &&
					response.ok(),
				{ timeout: 30_000 }
			);
			await page.getByTestId('workflow-run-cancel-confirm').click();
			await cancelResponse;
			await expect(selectedRun).toContainText(/cancellation requested|cancelled/i, {
				timeout: 30_000
			});
			await expectNoPageOverflow(page);

			// Sharing stays in the header but only shows the v1 coming-soon notice.
			if (!(await page.getByTestId('workflow-share').isVisible())) {
				await page.getByTestId('workflow-detail-actions').getByRole('button', { name: 'More', exact: true }).click();
			}
			const sharingOriginUrl = page.url();
			await page.getByTestId('workflow-share').click();
			await expect(page).toHaveURL(sharingOriginUrl);
			await expect(page.getByText('Workflow sharing is coming soon.', { exact: true })).toBeVisible();
			await expect(page.getByTestId('workflow-template-share')).toHaveCount(0);

			if (proof) await proof.attach();
		} finally {
			for (const workflowId of createdWorkflowIds) {
				await page.request
					.delete(`${apiUrl}/v1/workflows/${encodeURIComponent(workflowId)}`)
					.catch(() => null);
			}
		}
	});
});

test.describe('Workflow templates', () => {
	// contract-test: supporting surface=gui.web assertions=workflows-ui.workspace.owned-library-and-templates,workflows-ui.mvp.authoring
	test('browses templates and creates a disabled owned copy in the editor', async ({ page }: { page: Page }) => {
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:workflows']);
		const apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
		let createdId: string | null = null;
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page);
		try {
			await page.goto(getE2EDebugUrl('/workflows'), { waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('workflows-start-screen')).toBeVisible();
			await expect(page.getByTestId('workflow-mixed-row').getByTestId('workflow-landing-card').filter({ hasText: 'Daily planning reminder' })).toHaveCount(0);
			await page.getByTestId('workflows-show-templates').click();
			await expect(page.getByTestId('all-workflows-view')).toBeVisible();
			await expect(page.getByRole('heading', { name: 'Templates' })).toBeVisible();
			await expect(page.getByTestId('workflows-sort')).toHaveCount(0);
			const templateCard = page.getByTestId('all-workflows-grid').getByTestId('workflow-landing-card').filter({ hasText: 'Daily planning reminder' });
			await expect(templateCard).toBeVisible();
			const createdResponse = page.waitForResponse((response) => response.url().endsWith('/v1/workflows') && response.request().method() === 'POST');
			await templateCard.click();
			const response = await createdResponse;
			expect(response.ok(), await response.text()).toBe(true);
			const created = (await response.json()).workflow;
			const workflowId = String(created.id);
			createdId = workflowId;
			expect(created.enabled).toBe(false);
			expect(created.graph.version).toBe(2);
			expect(created.graph.nodes.map((node: { type: string }) => node.type)).toEqual(['schedule_trigger', 'send_chat_message']);
			expect(created.graph.nodes[0].config.schedule.timezone).toBe(await page.evaluate(() => Intl.DateTimeFormat().resolvedOptions().timeZone));
			await expect(page.getByTestId('workspace-detail-title')).toHaveText('Daily planning reminder');
			await expect(page.getByTestId('workflow-template-panel')).toBeVisible();
			const runResponse = await page.request.post(`${apiUrl}/v1/workflows/${encodeURIComponent(workflowId)}/run`, {
				data: { mode: 'test', input: {} },
				headers: { 'Idempotency-Key': `template-browse-${workflowId}` }
			});
			expect(runResponse.ok(), await runResponse.text()).toBe(true);
			const run = (await runResponse.json()).run;
			await expect.poll(async () => {
				const result = await page.request.get(`${apiUrl}/v1/workflows/${encodeURIComponent(workflowId)}/runs/${encodeURIComponent(run.id)}`);
				if (!result.ok()) return `HTTP ${result.status()}`;
				return (await result.json()).run.status;
			}, { timeout: 45_000 }).toBe('completed');
			await page.getByTestId('workflow-detail-back').click();
			await page.getByTestId('workflows-show-all').click();
			await expect(page.getByTestId('all-workflows-grid').getByTestId('workflow-landing-card').filter({ hasText: 'Daily planning reminder' })).toBeVisible();
		} finally {
			if (createdId) await page.request.delete(`${apiUrl}/v1/workflows/${encodeURIComponent(createdId)}`).catch(() => null);
		}
	});

});

function apiUrl(): string {
  const url = new URL(process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org');
  return url.hostname === 'localhost' ? 'http://localhost:8000' : `${url.protocol}//${url.hostname.replace(/^app\./, 'api.')}`;
}

test.describe('Workflow Send message delivery', () => {
  // contract-test: direct surface=gui.web assertions=workflows-ui.runs.timeline-execution-detail,workflows.chat-delivery.sync-projection,workflows.chat-delivery.client-encrypted
  test('stays pending until encrypted chat persistence, then notifies and opens the delivered chat', async ({ page }: { page: import('@playwright/test').Page }) => {
    test.setTimeout(150_000);
    test.skip(!getTestAccount().email, 'Test account credentials required.');
    await skipIfFeaturesDisabled(test, page, ['platform:workflows']);
    await page.addInitScript(() => {
      const nativeSend = WebSocket.prototype.send;
      const held: Array<{ socket: WebSocket; data: string | ArrayBufferLike | Blob | ArrayBufferView }> = [];
      WebSocket.prototype.send = function (data) {
        if (typeof data === 'string') {
          try {
            if (JSON.parse(data).type === 'workflow_chat_delivery_claim') {
              held.push({ socket: this, data });
              return;
            }
          } catch { /* Non-JSON frames use normal transport. */ }
        }
        nativeSend.call(this, data);
      };
      (window as typeof window & { __releaseWorkflowClaims?: () => void; __heldWorkflowClaims?: () => number }).__releaseWorkflowClaims = () => {
        for (const claim of held.splice(0)) nativeSend.call(claim.socket, claim.data);
      };
      (window as typeof window & { __heldWorkflowClaims?: () => number }).__heldWorkflowClaims = () => held.length;
    });

    await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
    await loginToTestAccount(page);
    const title = `Workflow delivery ${Date.now()}`;
    const chatTitle = `Workflow message ${Date.now()}`;
    const created = await page.request.post(`${apiUrl()}/v1/workflows`, { data: {
      title, enabled: false,
      graph: {
        version: 2, trigger_node_id: 'trigger',
        nodes: [
          { id: 'trigger', type: 'manual_trigger', title: 'Start', config: {} },
          { id: 'send', type: 'send_chat_message', title: 'Send message', config: { title: chatTitle, message: 'Delivery is ready' } },
        ],
        edges: [{ from: 'trigger', to: 'send' }],
      },
    } });
    expect(created.ok(), await created.text()).toBe(true);
    const workflowId = (await created.json()).workflow.id;
    try {
      await page.goto(getE2EDebugUrl('/workflows'), { waitUntil: 'domcontentloaded' });
      await page.getByTestId('workflow-landing-card').filter({ hasText: title }).first().click();
      const accepted = await page.request.post(`${apiUrl()}/v1/workflows/${workflowId}/run`, {
        data: { mode: 'test', input: {} },
        headers: { 'Idempotency-Key': `workflow-delivery-${workflowId}` },
      });
      expect(accepted.ok(), await accepted.text()).toBe(true);
      const runId = (await accepted.json()).run.id;
      const runUrl = `${apiUrl()}/v1/workflows/${workflowId}/runs/${runId}`;
      await expect.poll(async () => {
        const response = await page.request.get(runUrl);
        if (!response.ok()) return `HTTP ${response.status()}`;
        return (await response.json()).run.output_summary?.deliveries?.send?.status;
      }, { timeout: 45_000 }).toBe('delivery_pending');
      await expect.poll(() => page.evaluate(() => (window as typeof window & { __heldWorkflowClaims?: () => number }).__heldWorkflowClaims?.() ?? 0)).toBeGreaterThan(0);

      let browserDetailRequests = 0;
      await page.route(`**/v1/workflows/${workflowId}/runs/${runId}`, async route => {
        browserDetailRequests += 1;
        if (browserDetailRequests === 1) {
          await route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"Temporary failure"}' });
        } else {
          await route.continue();
        }
      });
      await page.getByTestId('workflow-tab-runs').click();
      await expect.poll(() => browserDetailRequests, { timeout: 15_000 }).toBeGreaterThan(1);
      const marker = page.locator(`[data-testid="workflow-run-marker"][data-run-id="${runId}"]`);
      await expect(marker).toHaveAttribute('data-run-status', 'delivery_pending');
      const sendNode = page.locator('[data-testid="workflow-run-graph"] [data-node-id="send"]');
      await expect(sendNode.getByTestId('workflow-run-node-status')).toHaveAttribute('data-node-status', 'delivery_pending');
      await expect(sendNode.getByTestId('workflow-run-node-status')).toHaveAttribute('aria-label', /waiting/i);
      await expect(sendNode.getByTestId('workflow-run-open-chat')).toHaveCount(0);
      await expect(page.getByTestId('chat-notification').filter({ hasText: chatTitle })).toHaveCount(0);

      await page.evaluate(() => (window as typeof window & { __releaseWorkflowClaims?: () => void }).__releaseWorkflowClaims?.());
      const notification = page.getByTestId('chat-notification').filter({ hasText: chatTitle });
      await expect(notification).toBeVisible({ timeout: 45_000 });
      await notification.hover();
      await expect.poll(async () => {
        const response = await page.request.get(runUrl);
        if (!response.ok()) return null;
        return (await response.json()).run.output_summary?.deliveries?.send?.status;
      }, { timeout: 45_000 }).toBe('acknowledged');
      await expect(sendNode.getByTestId('workflow-run-node-status')).toHaveAttribute('data-node-status', 'acknowledged', { timeout: 45_000 });
      await expect(marker).toHaveAttribute('data-run-status', 'completed');
      const openChat = sendNode.getByTestId('workflow-run-open-chat');
      await expect(openChat).toBeVisible();
      const chatId = await notification.getAttribute('data-chat-id');
      expect(chatId).toBeTruthy();
      await expect(openChat).toHaveAttribute('href', new RegExp(`chat-id=${chatId}$`));
      await notification.click();
      await expect(page).toHaveURL(new RegExp(`chat-id=${chatId}`));
      await expect(page.getByText('Delivery is ready', { exact: false }).first()).toBeVisible();
    } finally {
      await page.request.delete(`${apiUrl()}/v1/workflows/${workflowId}`).catch(() => null);
    }
  });
});
