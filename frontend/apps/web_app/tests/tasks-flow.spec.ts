/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Tasks V1 web flow coverage.
 *
 * Verifies the deployed /tasks workspace can create encrypted user-facing tasks,
 * render them on the shared Kanban board, move them through touch-safe controls,
 * and preserve the task state after reload.
 */

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

test.describe('Tasks V1 flow', () => {
	test('creates a manual task and persists a Kanban status move', async ({ page }) => {
		test.setTimeout(120000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');

		const log = (message: string, metadata: Record<string, unknown> = {}) => {
			console.log(`[TASKS_E2E] ${message} ${JSON.stringify(metadata)}`);
		};
		const screenshot = async () => {};
		const taskTitle = `E2E task ${Date.now()}`;
		const taskDescription = 'Created by the Tasks V1 Playwright flow';

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page, log, screenshot);

		await page.goto(getE2EDebugUrl('/tasks'), { waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('tasks-page')).toBeVisible({ timeout: 30000 });

		await page.getByTestId('task-title-input').fill(taskTitle);
		await page.getByTestId('task-description-input').fill(taskDescription);
		await page.getByTestId('task-create-button').click();

		const todoColumn = page.getByTestId('task-column-todo');
		const createdCard = todoColumn.getByTestId('task-card').filter({ hasText: taskTitle });
		await expect(createdCard).toBeVisible({ timeout: 30000 });
		await expect(createdCard).toContainText(taskDescription);

		await createdCard.getByTestId('task-move-done').click();

		const doneColumn = page.getByTestId('task-column-done');
		await expect(doneColumn.getByTestId('task-card').filter({ hasText: taskTitle })).toBeVisible({ timeout: 30000 });

		await page.reload({ waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('tasks-page')).toBeVisible({ timeout: 30000 });
		await expect(page.getByTestId('task-column-done').getByTestId('task-card').filter({ hasText: taskTitle })).toBeVisible({ timeout: 30000 });
	});
});
