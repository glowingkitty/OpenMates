/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/** A real Workflow run keeps its projected Tasks detail usable at desktop and phone widths. */
export {};

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

function apiUrl(): string {
	const base = new URL(process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org');
	if (base.hostname === 'localhost') return 'http://localhost:8000';
	return `${base.protocol}//api.${base.hostname.replace(/^app\./, '')}`;
}

function approvalGraph() {
	return {
		version: 1,
		trigger_node_id: 'schedule',
		nodes: [
			{ id: 'schedule', type: 'schedule_trigger', title: 'Daily start', config: { schedule: { type: 'daily', time: '09:00', timezone: 'UTC' } } },
			{ id: 'approval', type: 'ask_user', title: 'Confirm the next step', config: { prompt: 'Continue this Workflow?', timeout_seconds: 600 } },
			{ id: 'notify', type: 'send_notification', title: 'Show result', config: { title: 'Ready', body: 'Ready' } },
			{ id: 'end', type: 'end', title: 'Done', config: {} }
		],
		edges: [{ from: 'schedule', to: 'approval' }, { from: 'approval', to: 'notify' }, { from: 'notify', to: 'end' }]
	};
}

test.describe('Tasks Workflow run detail', () => {
	// contract-test: direct surface=gui.web assertions=workflows.execution.lifecycle-visible,tasks.workflow-projections.read-only,tasks.detail.embed-responsive
	test('opens an exact live run in split and fullscreen views without replacing the board', async ({ page }: { page: any }) => {
		test.setTimeout(120_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:workflows', 'platform:tasks']);
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page);

		let workflowId: string | null = null;
		try {
			const create = await page.request.post(`${apiUrl()}/v1/workflows`, {
				data: { title: `Tasks run detail ${Date.now()}`, graph: approvalGraph(), enabled: true }
			});
			expect(create.ok(), await create.text()).toBe(true);
			workflowId = (await create.json()).workflow.id;
			const runResponse = await page.request.post(`${apiUrl()}/v1/workflows/${workflowId}/run`, {
				data: { mode: 'test', input: {} },
				headers: { 'Idempotency-Key': `${workflowId}-tasks-detail` }
			});
			expect(runResponse.ok(), await runResponse.text()).toBe(true);
			const runId = (await runResponse.json()).run.id;

			for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
				await page.setViewportSize(viewport);
				await page.goto(getE2EDebugUrl('/tasks'), { waitUntil: 'domcontentloaded' });
				const board = page.getByTestId('task-board');
				await expect(board).toBeVisible({ timeout: 30_000 });
				const projection = page.locator(`[data-testid="workflow-run-projection"][data-workflow-run-id="${runId}"]`);
				await expect(projection).toHaveCount(1, { timeout: 30_000 });
				await expect(page.getByTestId('workflow-run-node-task')).toHaveCount(0);
				const boardNode = await board.elementHandle();
				await projection.click();

				const detail = page.getByTestId('workflow-run-projection-detail');
				await expect(detail).toBeVisible();
				await expect(detail).toHaveAttribute('data-presentation', viewport.width === 1440 ? 'split' : 'overlay');
				await expect(page.getByTestId('workflow-run-fullscreen')).toBeVisible();
				await expect(page.getByTestId('workflow-run-detail-id')).toHaveText(runId);
				await expect(page.getByTestId('workflow-run-detail-live-status')).toHaveAttribute('data-status', /^(queued|running|waiting|completed|failed|cancelled)$/);
				await expect(page.getByTestId('workflow-run-detail-node-status').first()).toBeVisible({ timeout: 30_000 });
				await expect(board).toBeVisible();
				if (viewport.width === 1440) {
					const [boardBox, detailBox] = await Promise.all([board.boundingBox(), detail.boundingBox()]);
					expect(boardBox && detailBox).toBeTruthy();
					expect(boardBox!.x + boardBox!.width).toBeLessThanOrEqual(detailBox!.x + 2);
				} else {
					const box = await detail.boundingBox();
					expect(box && box.width >= viewport.width - 2 && box.height >= viewport.height - 2).toBe(true);
				}

				await page.getByTestId('task-detail-close').click();
				await expect(detail).toHaveCount(0);
				await expect(board).toBeVisible();
				expect(await board.evaluate((node: HTMLElement, original: HTMLElement | null) => node === original, boardNode)).toBe(true);
			}
		} finally {
			if (workflowId) await page.request.delete(`${apiUrl()}/v1/workflows/${workflowId}`).catch(() => null);
		}
	});
});
