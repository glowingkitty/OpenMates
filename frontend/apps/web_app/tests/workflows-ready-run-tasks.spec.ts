/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * TASK-16 red contract for ready Workflows projected into Tasks.
 *
 * Uses the shared authenticated E2E account against the deployed app and real
 * API state. Each created Workflow is deleted after its viewport flow finishes.
 * The stable test ids deliberately describe the pending product surface.
 */

export {};

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

const IS_PROOF_CAPTURE = Boolean(process.env.PLAYWRIGHT_VIDEO_WIDTH && process.env.PLAYWRIGHT_VIDEO_HEIGHT);
const PROOF_DEVICE = Number.parseInt(process.env.PLAYWRIGHT_VIDEO_WIDTH || '', 10) === 390 ? 'web-phone' : 'web-laptop';
const PROOF_VIEWPORT = PROOF_DEVICE === 'web-phone' ? { width: 390, height: 844 } : { width: 1440, height: 900 };
const VIEWPORTS = IS_PROOF_CAPTURE ? [PROOF_VIEWPORT] : [{ width: 1440, height: 900 }, { width: 390, height: 844 }];
const PRESERVED_BOARD_SCROLL_LEFT = 72;
const TERMINAL_RUN_STATUS = /^(completed|failed|cancelled)$/;
const TERMINAL_NODE_STATUS = /^(completed|failed|skipped)$/;
const VISIBLE_RUN_DETAIL_STATUS = /^(queued|running|completed|failed|cancelled)$/;
const VISIBLE_NODE_STATUS = /^(queued|running|completed|failed|skipped)$/;
const PROOF_CAPTURE_HOLD_MS = 2_000;

const READY_RUN_TASKS_PROOF = defineVideoProof({
	id: 'workflows-ready-run-tasks',
	title: 'Ready Workflow run projected into Tasks',
	surface: 'web',
	devices: ['web-laptop', 'web-phone'],
	domain: 'app.dev.openmates.org',
	transcript: [
		{
			id: 'blank-draft-visible',
			text: 'A title-first Workflow starts disabled with no trigger or steps, so it cannot run until its definition is ready.',
			checkpoint: 'blank-draft-visible',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'ready-run-visible',
			text: 'One time trigger reaches several steps including a qualifying side effect, allowing the saved Workflow to enable and run manually.',
			checkpoint: 'ready-run-visible',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'projection-detail-visible',
			text: 'Tasks shows one read-only projection for this run. Its detail shows the exact run identifier and live node status, even when the run completes quickly.',
			checkpoint: 'projection-detail-visible',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'responsive-close-visible',
			text: 'The run detail is side-by-side on laptop and full-screen on phone. Closing it returns to the unchanged Tasks board.',
			checkpoint: 'responsive-close-visible',
			devices: ['web-laptop', 'web-phone']
		}
	],
	assertions: [
		{
			id: 'blank-draft-visible.assertion',
			checkpoint: 'blank-draft-visible',
			visual: 'The title-first blank Workflow clearly reports zero triggers, zero steps, and disabled activation without clipping.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'ready-run-visible.assertion',
			checkpoint: 'ready-run-visible',
			visual: 'The saved and enabled Workflow shows a reachable qualifying side effect and an explicit manual-run state.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'projection-detail-visible.assertion',
			checkpoint: 'projection-detail-visible',
			visual: 'One active or just-completed projection and its exact run detail are visible without node task cards or raw protocol text.',
			devices: ['web-laptop', 'web-phone']
		},
		{
			id: 'responsive-close-visible.assertion',
			checkpoint: 'responsive-close-visible',
			visual: 'The desktop split or phone overlay is reachable, and closing it preserves the board position and controls.',
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

async function expectExactRunProjection(page: any, runId: string) {
	const projection = page.locator(`[data-testid="workflow-run-projection"][data-workflow-run-id="${runId}"]`);
	await expect(projection).toHaveCount(1);
	await expect(projection).toHaveAttribute('data-status', /^(in_progress|done)$/);
	await expect(page.getByTestId('workflow-run-node-task')).toHaveCount(0);
	return projection;
}

async function expectNotCoveredByTaskComposer(page: any, target: any) {
	const targetBox = await target.boundingBox();
	const composerBox = await page.getByTestId('task-workspace-composer').boundingBox();
	expect(targetBox).not.toBeNull();
	expect(composerBox).not.toBeNull();
	if (!targetBox || !composerBox) return;
	expect(targetBox.y + targetBox.height).toBeLessThanOrEqual(composerBox.y);
}

async function holdProofCheckpoint(page: any) {
	if (IS_PROOF_CAPTURE) await page.waitForTimeout(PROOF_CAPTURE_HOLD_MS);
}

test.describe('Ready Workflow run Tasks projection', () => {
	// contract-test: direct surface=gui.web assertions=workflows.activation.reachable-side-effect,workflows.execution.lifecycle-visible,tasks.workflow-projections.read-only,tasks.detail.embed-responsive
	test('authors a ready Workflow and preserves the live projected run detail at proof viewports', async ({ page }: { page: any }, testInfo: any) => {
		test.setTimeout(300_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:workflows', 'platform:tasks']);

		const apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
		const createdWorkflowIds = new Set<string>();
		const suffix = `${Date.now()}-${testInfo.workerIndex}`;
		const proof = IS_PROOF_CAPTURE
			? createVideoProofRuntime(READY_RUN_TASKS_PROOF, {
				device: PROOF_DEVICE,
				attach: testInfo.attach.bind(testInfo),
				captureFrame: () => page.screenshot({ type: 'png' })
			})
			: null;

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page);

		try {
			for (const viewport of VIEWPORTS) {
				const workflowTitle = `Ready run Tasks contract ${suffix}-${viewport.width}`;
				await page.setViewportSize(viewport);
				await page.goto(getE2EDebugUrl('/workflows'), { waitUntil: 'domcontentloaded' });
				await expect(page.getByTestId('workflows-page')).toBeVisible({ timeout: 30_000 });

				await page.getByTestId('create-blank-workflow').click();
				await page.getByTestId('workflow-blank-title-input').fill(workflowTitle);
				const createResponse = page.waitForResponse(
					(response: any) => new URL(response.url()).pathname === '/v1/workflows' && response.request().method() === 'POST' && response.ok(),
					{ timeout: 30_000 }
				);
				await page.getByTestId('workflow-blank-create').click();
				const workflow = (await (await createResponse).json()).workflow;
				createdWorkflowIds.add(workflow.id);

				await expect(page.getByTestId('workflow-readiness-trigger-count')).toHaveText('0');
				await expect(page.getByTestId('workflow-readiness-step-count')).toHaveText('0');
				await expect(page.getByTestId('toggle-workflow')).toBeDisabled();
				if (proof) {
					await proof.assert('blank-draft-visible.assertion', async () => {
						await expect(page.getByTestId('workflow-blank-draft')).toBeVisible();
						await expect(page.getByTestId('workflow-readiness-trigger-count')).toHaveText('0');
					});
					await proof.checkpoint('blank-draft-visible');
					await holdProofCheckpoint(page);
				}

				await page.getByTestId('workflow-add-time-trigger').click();
				await page.getByTestId('workflow-time-trigger-schedule').selectOption('daily');
				await page.getByTestId('workflow-add-step').click();
				await page.getByTestId('workflow-step-app-skill-action').click();
				await page.getByTestId('workflow-add-step').click();
				await page.getByTestId('workflow-step-create-chat-report').click();
				await expect(page.getByTestId('workflow-readiness-trigger-count')).toHaveText('1');
				await expect(page.getByTestId('workflow-readiness-step-count')).toHaveText('2');
				await expect(page.getByTestId('workflow-reachable-qualifying-side-effect')).toHaveAttribute('data-reachable', 'true');

				await page.getByTestId('save-workflow').click();
				await expect(page.getByTestId('toggle-workflow')).toBeEnabled();
				await page.getByTestId('toggle-workflow').click();
				await expect(page.getByTestId('workflow-enabled-state')).toHaveAttribute('data-enabled', 'true');
				const runResponse = page.waitForResponse(
					(response: any) => response.url().endsWith(`/v1/workflows/${workflow.id}/run`) && response.request().method() === 'POST' && response.ok(),
					{ timeout: 30_000 }
				);
				await page.getByTestId('run-workflow').click();
				const run = (await (await runResponse).json()).run;
				if (proof) {
					await proof.assert('ready-run-visible.assertion', async () => {
						await expect(page.getByTestId('workflow-enabled-state')).toHaveAttribute('data-enabled', 'true');
						await expect(page.getByTestId('workflow-run-started')).toHaveAttribute('data-run-id', run.id);
					});
					await proof.checkpoint('ready-run-visible');
					await holdProofCheckpoint(page);
				}

				await page.goto(getE2EDebugUrl('/tasks'), { waitUntil: 'domcontentloaded' });
				await expect(page.getByTestId('tasks-page')).toBeVisible({ timeout: 30_000 });
				const taskBoard = page.getByTestId('task-board');
				await expect(taskBoard).toBeVisible();
				const preservedBoardScrollLeft = await taskBoard.evaluate((board: HTMLElement, target: number) => {
					board.scrollLeft = Math.min(target, board.scrollWidth - board.clientWidth);
					return board.scrollLeft;
				}, PRESERVED_BOARD_SCROLL_LEFT);
				expect(preservedBoardScrollLeft).toBeGreaterThan(0);
				const boardNode = await taskBoard.elementHandle();
				const boardState = await taskBoard.getAttribute('data-board-state');
				const projection = await expectExactRunProjection(page, run.id);
				await projection.click();
				const detailOpenBoardScrollLeft = await taskBoard.evaluate((board: HTMLElement) => board.scrollLeft);

				const detail = page.getByTestId('workflow-run-projection-detail');
				await expect(detail).toBeVisible();
				await expect(page.getByTestId('workflow-run-detail-id')).toHaveText(run.id);
				const liveStatus = page.getByTestId('workflow-run-detail-live-status');
				await expect(liveStatus).toHaveAttribute('data-live', /^(true|false)$/);
				await expect(liveStatus).toHaveAttribute('data-status', VISIBLE_RUN_DETAIL_STATUS);
				const runNodeStatus = page.getByTestId('workflow-run-detail-node-status').first();
				await expect(runNodeStatus).toHaveAttribute('data-status', VISIBLE_NODE_STATUS, { timeout: 30_000 });
				await expectNotCoveredByTaskComposer(page, runNodeStatus);
				if (viewport.width === 1440) {
					await expect(detail).toHaveAttribute('data-presentation', 'split');
				} else {
					await expect(detail).toHaveAttribute('data-presentation', 'overlay');
				}
				if (proof) {
					await proof.assert('projection-detail-visible.assertion', async () => {
						await expect(page.getByTestId('workflow-run-detail-id')).toHaveText(run.id);
						await expect(runNodeStatus).toBeVisible();
					});
					await proof.checkpoint('projection-detail-visible');
					await holdProofCheckpoint(page);
				}

				const initialStatus = await liveStatus.getAttribute('data-status');
				const initialNodeStatus = await runNodeStatus.getAttribute('data-status');
				if (!TERMINAL_RUN_STATUS.test(initialStatus || '')) {
					await expect.poll(async () => {
						const status = await liveStatus.getAttribute('data-status');
						return status !== initialStatus && TERMINAL_RUN_STATUS.test(status || '');
					}, { timeout: 60_000 }).toBe(true);
				}
				await expect(liveStatus).toHaveAttribute('data-status', 'completed');
				if (!TERMINAL_NODE_STATUS.test(initialNodeStatus || '')) {
					await expect.poll(async () => {
						const status = await runNodeStatus.getAttribute('data-status');
						return status !== initialNodeStatus && TERMINAL_NODE_STATUS.test(status || '');
					}, { timeout: 60_000 }).toBe(true);
				}
				await expect(runNodeStatus).toHaveAttribute('data-status', 'completed');

				await page.getByTestId('task-detail-close').click();
				await expect(detail).toHaveCount(0);
				await expect(taskBoard).toBeVisible();
				expect(await taskBoard.evaluate((node: HTMLElement, original: HTMLElement | null) => node === original, boardNode)).toBe(true);
				expect(await taskBoard.evaluate((board: HTMLElement) => board.scrollLeft)).toBe(detailOpenBoardScrollLeft);
				await expect(taskBoard).toHaveAttribute('data-board-state', boardState);
				await expectNotCoveredByTaskComposer(page, projection);
				if (proof) {
					await proof.assert('responsive-close-visible.assertion', async () => {
						await expect(taskBoard).toBeVisible();
						expect(await taskBoard.evaluate((board: HTMLElement) => board.scrollLeft)).toBe(detailOpenBoardScrollLeft);
					});
					await proof.checkpoint('responsive-close-visible');
					await holdProofCheckpoint(page);
				}
			}

			if (proof) await proof.attach();
		} finally {
			for (const workflowId of createdWorkflowIds) {
				await page.request.delete(`${apiUrl}/v1/workflows/${encodeURIComponent(workflowId)}`).catch(() => null);
			}
		}
	});
});
