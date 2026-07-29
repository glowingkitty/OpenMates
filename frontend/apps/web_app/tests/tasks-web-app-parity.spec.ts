/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Tasks web app parity coverage.
 *
 * Proves the browser Tasks workspace follows the existing CLI/API contract:
 * encrypted task creation, the shared daily inspiration header, fixed Kanban
 * columns, status/action parity, and touch-safe explicit controls.
 */

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { createSignupLogger, createStepScreenshotter, getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

const TASK_STATUSES = ['backlog', 'todo', 'in_progress', 'blocked', 'done'];

function taskCardIn(column: any, title: string): any {
	return column.getByTestId('task-card').filter({ hasText: title }).first();
}

test.describe('Tasks web app parity', () => {
	test('renders daily task tips and manages encrypted tasks through Kanban actions', async ({ page }) => {
		test.slow();
		test.setTimeout(180_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:tasks']);

		const log = createSignupLogger('TASKS_WEB_PARITY');
		const screenshot = createStepScreenshotter(log, { filenamePrefix: 'tasks-web-parity' });
		const suffix = Date.now();
		const taskTitle = `Web parity task ${suffix}`;
		const taskDescription = 'Created by the Tasks web parity spec';

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page, log, screenshot);
		await page.goto(getE2EDebugUrl('/tasks'), { waitUntil: 'domcontentloaded' });

		await expect(page.getByTestId('tasks-page')).toBeVisible({ timeout: 30_000 });
		await expect(page.getByTestId('tasks-daily-inspiration-area')).toBeVisible({ timeout: 15_000 });
		await expect(page.getByTestId('daily-inspiration-banner')).toBeVisible({ timeout: 15_000 });
		await expect(page.getByTestId('daily-inspiration-phrase')).toContainText(/task|next action|todo|checklist|status/i, { timeout: 15_000 });

		for (const status of TASK_STATUSES) {
			await expect(page.getByTestId(`task-column-${status}`)).toBeVisible({ timeout: 15_000 });
		}

		let createRequestPayload = '';
		const createResponse = page.waitForResponse((response) => {
			if (!response.url().includes('/v1/user-tasks') || response.request().method() !== 'POST') return false;
			createRequestPayload = response.request().postData() ?? '';
			return response.ok();
		});
		await page.getByTestId('task-title-input').fill(taskTitle);
		await page.getByTestId('task-description-input').fill(taskDescription);
		await page.getByTestId('task-create-button').click();
		await createResponse;

		expect(createRequestPayload).not.toContain(taskTitle);
		expect(createRequestPayload).not.toContain(taskDescription);

		const todoCard = taskCardIn(page.getByTestId('task-column-todo'), taskTitle);
		await expect(todoCard).toBeVisible({ timeout: 30_000 });
		await expect(todoCard).toContainText(taskDescription);

		await Promise.all([
			page.waitForResponse((response) => response.request().method() === 'POST' && response.url().includes('/v1/user-tasks/reorder') && response.ok()),
			todoCard.getByTestId('task-move-in_progress').click(),
		]);
		const inProgressCard = taskCardIn(page.getByTestId('task-column-in_progress'), taskTitle);
		await expect(inProgressCard).toBeVisible({ timeout: 30_000 });

		await Promise.all([
			page.waitForResponse((response) => response.request().method() === 'POST' && response.url().includes('/block') && response.ok()),
			inProgressCard.getByTestId('task-block-button').click(),
		]);
		const blockedCard = taskCardIn(page.getByTestId('task-column-blocked'), taskTitle);
		await expect(blockedCard).toBeVisible({ timeout: 30_000 });

		await Promise.all([
			page.waitForResponse((response) => response.request().method() === 'POST' && response.url().includes('/unblock') && response.ok()),
			blockedCard.getByTestId('task-unblock-button').click(),
		]);
		await expect(taskCardIn(page.getByTestId('task-column-todo'), taskTitle)).toBeVisible({ timeout: 30_000 });

		const reboundTodoCard = taskCardIn(page.getByTestId('task-column-todo'), taskTitle);
		await Promise.all([
			page.waitForResponse((response) => response.request().method() === 'POST' && response.url().includes('/complete') && response.ok()),
			reboundTodoCard.getByTestId('task-done-toggle').click(),
		]);
		const doneCard = taskCardIn(page.getByTestId('task-column-done'), taskTitle);
		await expect(doneCard).toBeVisible({ timeout: 30_000 });

		await page.reload({ waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('tasks-page')).toBeVisible({ timeout: 30_000 });
		const persistedDoneCard = taskCardIn(page.getByTestId('task-column-done'), taskTitle);
		await expect(persistedDoneCard).toBeVisible({ timeout: 30_000 });

		await Promise.all([
			page.waitForResponse((response) => response.request().method() === 'DELETE' && response.url().includes('/v1/user-tasks/') && response.ok()),
			persistedDoneCard.getByTestId('task-delete-button').click(),
		]);
		await expect(page.getByTestId('task-board')).not.toContainText(taskTitle, { timeout: 30_000 });
	});

	test('keeps task actions reachable on a mobile viewport', async ({ page }) => {
		test.slow();
		test.setTimeout(150_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:tasks']);

		const log = createSignupLogger('TASKS_WEB_MOBILE_PARITY');
		const screenshot = createStepScreenshotter(log, { filenamePrefix: 'tasks-web-mobile-parity' });
		const taskTitle = `Mobile task ${Date.now()}`;

		await page.setViewportSize({ width: 390, height: 844 });
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page, log, screenshot);
		await page.goto(getE2EDebugUrl('/tasks'), { waitUntil: 'domcontentloaded' });

		await expect(page.getByTestId('tasks-daily-inspiration-area')).toBeVisible({ timeout: 15_000 });
		await expect(page.getByTestId('task-board')).toBeVisible({ timeout: 30_000 });
		await page.getByTestId('task-title-input').fill(taskTitle);
		await page.getByTestId('task-create-button').click();

		const todoCard = taskCardIn(page.getByTestId('task-column-todo'), taskTitle);
		await expect(todoCard).toBeVisible({ timeout: 30_000 });
		await expect(todoCard.getByTestId('task-move-done')).toBeVisible({ timeout: 10_000 });
		await Promise.all([
			page.waitForResponse((response) => response.request().method() === 'POST' && response.url().includes('/complete') && response.ok()),
			todoCard.getByTestId('task-done-toggle').click(),
		]);
		await expect(taskCardIn(page.getByTestId('task-column-done'), taskTitle)).toBeVisible({ timeout: 30_000 });
	});
});
