/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
export {};

/**
 * Tasks and Plans shared workspace coverage.
 *
 * Verifies /tasks and /plans render as sibling shared-workspace surfaces with
 * route-specific composers, boards, and two-axis board scrolling.
 */

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

const TASK_COLUMNS = ['backlog', 'todo', 'in_progress', 'blocked', 'done'];
const PLAN_COLUMNS = ['backlog', 'todo', 'in_progress', 'blocked', 'done'];

async function expectHorizontalBoardScroll(board: any): Promise<void> {
	await expect.poll(async () => board.evaluate((element: HTMLElement) => element.scrollWidth > element.clientWidth)).toBe(true);
}

test.describe('Tasks and Plans workspace transition', () => {
	test('renders route-specific shared workspace shells', async ({ page }) => {
		test.setTimeout(150000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:tasks', 'platform:plans']);

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page);

		await page.goto(getE2EDebugUrl('/tasks'), { waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('tasks-workspace-home')).toBeVisible({ timeout: 30000 });
		await expect(page.getByTestId('tasks-daily-inspiration-area')).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('task-greeting')).toContainText(/what task is next\?/i, { timeout: 15000 });
		await expect(page.getByTestId('task-workspace-composer')).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('tasks-board-workspace')).toBeVisible({ timeout: 15000 });
		for (const column of TASK_COLUMNS) {
			await expect(page.getByTestId(`task-column-${column}`)).toBeVisible({ timeout: 15000 });
		}

		await page.goto(getE2EDebugUrl('/plans'), { waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('plans-workspace-home')).toBeVisible({ timeout: 30000 });
		await expect(page.getByTestId('plans-daily-inspiration-area')).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('plan-greeting')).toContainText(/what is your next plan\?/i, { timeout: 15000 });
		await expect(page.getByTestId('plan-workspace-composer')).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('plans-board-workspace')).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('task-create-form')).toHaveCount(0);
		await expect(page.getByTestId('task-extract-card')).toHaveCount(0);
		for (const column of PLAN_COLUMNS) {
			await expect(page.getByTestId(`plan-column-${column}`)).toBeVisible({ timeout: 15000 });
		}
	});

	test('keeps boards horizontally scrollable on mobile', async ({ page }) => {
		test.setTimeout(150000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:tasks', 'platform:plans']);

		await page.setViewportSize({ width: 390, height: 844 });
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page);

		await page.goto(getE2EDebugUrl('/tasks'), { waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('task-board')).toBeVisible({ timeout: 30000 });
		await expectHorizontalBoardScroll(page.getByTestId('task-board'));

		await page.goto(getE2EDebugUrl('/plans'), { waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('plan-board')).toBeVisible({ timeout: 30000 });
		await expectHorizontalBoardScroll(page.getByTestId('plan-board'));
	});
});
