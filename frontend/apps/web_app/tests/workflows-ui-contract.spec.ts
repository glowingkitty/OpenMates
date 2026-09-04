/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Workflows web UI product-contract coverage.
 *
 * Seeds owner-scoped Workflow records through the real dev API, then verifies
 * the deployed workspace, guarded Template editor, immutable versions, and
 * cancellable run detail at the required laptop and phone proof viewports.
 * Every created Workflow is deleted during cleanup.
 */
export {};

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { captureTestThumbnail, defineTestThumbnail } = require('./helpers/test-thumbnail');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

const IS_PROOF_CAPTURE = Boolean(process.env.PLAYWRIGHT_VIDEO_WIDTH && process.env.PLAYWRIGHT_VIDEO_HEIGHT);
const PROOF_DEVICE = Number.parseInt(process.env.PLAYWRIGHT_VIDEO_WIDTH || '', 10) === 390 ? 'web-phone' : 'web-laptop';
const PROOF_STATE_SETTLE_MS = 750;
const PROOF_TEMPLATE_HOLD_MS = 2500;
const WORKFLOW_TITLE_PREFIX = 'Workflow UI contract';
const WORKFLOWS_UI_THUMBNAIL = defineTestThumbnail({
	id: 'workflows-workspace',
	focus: [{ testId: 'daily-inspiration-banner' }],
	context: [
		{ testId: 'workflows-show-all' },
		{ testId: 'workflow-input-composer' }
	]
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
			text: 'Editing a node reveals explicit Save and Undo controls, while navigation asks whether to Save, Discard, or Stay.',
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
			visual: 'The recommendation, centered Workflow identity, category cards, Show all, Search, and composer are visible without clipping.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'template-visible.assertion',
			checkpoint: 'template-visible',
			visual: 'The category header, shared tab pill, and centered Template graph form one stable detail composition.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'guard-visible.assertion',
			checkpoint: 'guard-visible',
			visual: 'The unsaved panel and Save, Discard, and Stay navigation decision remain reachable.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'version-visible.assertion',
			checkpoint: 'version-visible',
			visual: 'The selected historical version, Active current marker, timeline, and read-only graph are visible.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'runs-visible.assertion',
			checkpoint: 'runs-visible',
			visual: 'The waiting run, execution graph, node statuses, and cancel action are visible without raw protocol text.',
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

function rainGraph(location: string) {
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

function waitingGraph() {
	return {
		version: 1,
		trigger_node_id: 'manual',
		nodes: [
			{ id: 'manual', type: 'manual_trigger', title: 'Manual start', config: {} },
			{ id: 'approval', type: 'ask_user', title: 'Confirm the next step', config: { prompt: 'Continue this Workflow?', timeout_seconds: 600 } },
			{ id: 'end', type: 'end', title: 'Done', config: {} }
		],
		edges: [
			{ from: 'manual', to: 'approval' },
			{ from: 'approval', to: 'end' }
		]
	};
}

function workflowDetailsHashUrlPattern(workflowId: string): RegExp {
	return new RegExp(`/workflows#(?:[^#]*&)?workflow-id=${workflowId}&workflow-tab=details(?:&|$)`);
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
	await expect.poll(async () => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
}

test.describe('Workflows web UI contract', () => {
	// contract-test: direct surface=gui.web assertions=workflows-ui.workspace.recommendation-led-composition,workflows-ui.workspace.title-first-draft,workflows-ui.detail.stable-visual-header,workflows-ui.detail.shared-template-runs-tabs,workflows-ui.template.centered-in-place-editor,workflows-ui.template.explicit-guarded-save,workflows-ui.versions.timeline-readonly-restore-new,workflows-ui.runs.timeline-execution-detail,workflows-ui.responsive-accessible-reachable
	test('preserves identity while editing versions and inspecting a cancellable run', async ({ page }: { page: any }, testInfo: any) => {
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

			const versionResponse = await page.request.patch(`${apiUrl}/v1/workflows/${encodeURIComponent(editorWorkflow.id)}`, {
				data: { graph: rainGraph('Hamburg') }
			});
			expect(versionResponse.ok(), await versionResponse.text()).toBe(true);

			const runnerWorkflow = await createWorkflow(page, apiUrl, {
				title: runnerTitle,
				description: 'A manual approval Workflow.',
				graph: waitingGraph(),
				enabled: true,
				run_content_retention: 'last_5',
				category: 'general_knowledge',
				icon: 'help-circle'
			});
			createdWorkflowIds.add(runnerWorkflow.id);

			const runResponse = await page.request.post(`${apiUrl}/v1/workflows/${encodeURIComponent(runnerWorkflow.id)}/run`, {
				data: { mode: 'test', input: {} },
				headers: { 'Idempotency-Key': `${runnerWorkflow.id}-ui-contract` }
			});
			expect(runResponse.ok(), await runResponse.text()).toBe(true);
			const run = (await runResponse.json()).run;

			await page.goto(getE2EDebugUrl('/workflows'), { waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('workflows-start-screen')).toBeVisible({ timeout: 30_000 });
			await expect(page.getByTestId('daily-inspiration-banner')).toBeVisible();
			await expect(page.getByTestId('workflows-workspace-background-icon')).toBeVisible();
			await expect(page.getByTestId('workflows-show-all')).toBeVisible();
			await expect(page.getByTestId('workflows-search')).toBeVisible();
			await expect(page.getByTestId('workflow-input-composer')).toBeVisible();
			const editorCard = page.getByTestId('workflow-landing-card').filter({ hasText: editorTitle }).first();
			await expect(editorCard).toHaveAttribute('data-card-source', 'recent');
			await expect(editorCard).toHaveAttribute('data-category', 'science');
			await expect(editorCard).toHaveAttribute('data-icon', 'cloud-rain');
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
			const detailHeader = page.getByTestId('workspace-detail-header');
			await expect(detailHeader).toHaveAttribute('data-category', 'science');
			await expect(detailHeader).toHaveAttribute('data-icon', 'cloud-rain');
			await expect(page.getByTestId('workflow-identity-icon')).toBeVisible();
			await expect(page.getByTestId('workflow-tab-template')).toHaveAttribute('aria-selected', 'true');
			await expect(page.getByTestId('workflow-tab-runs')).toHaveAttribute('aria-selected', 'false');
			await expect(page.getByTestId('workflow-template-panel')).toBeVisible();
			await expect(page.getByTestId('workflow-graph-renderer')).toHaveAttribute('data-read-only', 'false');
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

			const weatherNode = page.getByTestId('workflow-node-card').filter({ hasText: 'Weather' }).first();
			await weatherNode.getByTestId('workflow-node-summary').click();
			await weatherNode.getByTestId('workflow-node-location-input').fill('Paris');
			await expect(page.getByTestId('workflow-dirty-panel')).toBeVisible();
			await page.getByTestId('workflow-tab-runs').click();
			await expect(page.getByTestId('workflow-unsaved-guard')).toBeVisible();
			await expect(page.getByTestId('workflow-guard-save')).toBeVisible();
			await expect(page.getByTestId('workflow-guard-discard')).toBeVisible();
			await expect(page.getByTestId('workflow-guard-stay')).toBeVisible();
			await expect.poll(async () => page.evaluate(() => Boolean(document.activeElement?.closest('[data-testid="workflow-unsaved-guard"]')))).toBe(true);
			if (proof) {
				await settleProofState(page);
				await proof.assert('guard-visible.assertion', async () => {
					await expect(page.getByTestId('workflow-unsaved-guard')).toBeVisible();
				});
				await proof.checkpoint('guard-visible');
				await settleProofState(page);
			}
			await page.keyboard.press('Escape');
			await expect(page.getByTestId('workflow-unsaved-guard')).toHaveCount(0);
			await page.getByTestId('workflow-tab-runs').click();
			await expect(page.getByTestId('workflow-unsaved-guard')).toBeVisible();
			await page.getByTestId('workflow-guard-stay').click();
			await expect(page).toHaveURL(workflowDetailsHashUrlPattern(editorWorkflow.id));
			await page.getByTestId('save-workflow').click();
			await expect(page.getByTestId('workflow-dirty-panel')).toHaveCount(0, { timeout: 30_000 });
			await expect(page.getByTestId('save-workflow')).toHaveCount(0);
			await expect(page.getByTestId('workflow-graph-renderer').getByTestId('workflow-node-stack')).toContainText('Paris');

			await expect(page.getByTestId('workflow-version-selector')).toBeVisible();
			await expect(page.getByTestId('workflow-version-timeline')).toBeVisible();
			const historicalVersion = page.locator('[data-testid="workflow-version-row"][data-current="false"]').first();
			await historicalVersion.click();
			await expect(page.getByTestId('workflow-version-graph-inspection')).toBeVisible();
			await expect(page.getByTestId('workflow-version-graph-inspection')).toHaveAttribute('data-read-only', 'true');
			await expect(page.getByTestId('workflow-version-graph')).toBeVisible({ timeout: 30_000 });
			await expect(page.getByTestId('workflow-version-graph-inspection')).not.toContainText('app_id');
			await expect(page.locator('[data-testid="workflow-version-row"][data-current="true"]')).toContainText('Active');
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
			await page.getByTestId('workflow-landing-card').filter({ hasText: runnerTitle }).first().click();
			await expect(page).toHaveURL(workflowDetailsHashUrlPattern(runnerWorkflow.id));
			await page.getByTestId('workflow-tab-runs').click();
			await expect(page).toHaveURL(new RegExp(`workflow-id=${runnerWorkflow.id}&workflow-tab=runs`));
			await expect(page.getByTestId('workflow-run-selector')).toBeVisible();
			await expect(page.getByTestId('workflow-run-timeline')).toBeVisible();
			const selectedRun = page.locator(`[data-testid="workflow-run-marker"][data-run-id="${run.id}"]`);
			await expect(selectedRun).toContainText(/waiting/i);
			await expect.poll(async () => selectedRun.evaluate((element: HTMLElement) => {
				const marker = element.getBoundingClientRect();
				const status = element.querySelector('strong')?.getBoundingClientRect();
				return Boolean(status && status.top >= marker.top && status.bottom <= marker.bottom);
			})).toBe(true);
			await selectedRun.click();
			await expect(page.getByTestId('workflow-run-detail')).toBeVisible();
			await expect(page.getByTestId('workflow-run-graph')).toHaveAttribute('data-read-only', 'true');
			await expect(page.getByTestId('workflow-run-node-status').first()).toContainText(/queued|running|completed|skipped|failed/i);
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
			await expect.poll(async () => page.evaluate(() => Boolean(document.activeElement?.closest('[data-testid="workflow-run-cancel-confirmation"]')))).toBe(true);
			const cancelResponse = page.waitForResponse(
				(response: any) => response.url().endsWith(`/runs/${run.id}/cancel`) && response.request().method() === 'POST' && response.ok(),
				{ timeout: 30_000 }
			);
			await page.getByTestId('workflow-run-cancel-confirm').click();
			await cancelResponse;
			await expect(selectedRun).toContainText(/cancellation requested|cancelled/i, { timeout: 30_000 });
			await expectNoPageOverflow(page);

			if (proof) await proof.attach();
		} finally {
			for (const workflowId of createdWorkflowIds) {
				await page.request.delete(`${apiUrl}/v1/workflows/${encodeURIComponent(workflowId)}`).catch(() => null);
			}
		}
	});
});
