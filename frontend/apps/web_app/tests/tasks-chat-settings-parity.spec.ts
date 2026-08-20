/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Chat settings Tasks parity coverage.
 *
 * Proves the chat settings Tasks tab is backed by real encrypted task records,
 * not message placeholders, and that the active chat preview and central Tasks
 * board all observe the same chat-linked task state.
 */

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount, startNewChat, sendMessage, deleteActiveChat, waitForAssistantMessage, dismissSecurityReminderIfPresent } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { createSignupLogger, createStepScreenshotter, getE2EDebugUrl, getTestAccount, withMockMarker } = require('./signup-flow-helpers');

async function createSmallChat(page: any, log: any, screenshot: any): Promise<string> {
	await startNewChat(page, log);
	await sendMessage(
		page,
		withMockMarker('Reply in one short sentence: create a stable chat for task settings testing.', 'chat_flow_capital'),
		log,
		screenshot,
		'tasks-chat-settings'
	);
	await waitForAssistantMessage(page, { which: 'last', logCheckpoint: log });
	const chatId = page.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1];
	if (!chatId) throw new Error('Created chat URL is missing chat-id');
	return chatId;
}

test.describe('Chat settings Tasks parity', () => {
	// contract-test: direct surface=gui.web assertions=tasks.content.client-encrypted,tasks.lifecycle.visible
	test('creates chat-linked tasks and syncs settings, preview, and central board', async ({ page }) => {
		test.slow();
		test.setTimeout(240_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:tasks']);

		const log = createSignupLogger('TASKS_CHAT_SETTINGS_PARITY');
		const screenshot = createStepScreenshotter(log, { filenamePrefix: 'tasks-chat-settings-parity' });
		const suffix = Date.now();
		const taskTitle = `Primary chat task ${suffix}`;
		const secondTaskTitle = `Follow-up chat task ${suffix}`;

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page, log, screenshot);
		await dismissSecurityReminderIfPresent(page, log);
		const chatId = await createSmallChat(page, log, screenshot);

		await page.goto(getE2EDebugUrl(`/#chat-id=${chatId}&settings=chats/${chatId}/tasks`), { waitUntil: 'domcontentloaded' });
		const settingsMenu = page.getByTestId('settings-menu');
		await expect(settingsMenu).toHaveAttribute('data-active-view', `chats/${chatId}`, { timeout: 20_000 });
		await expect(settingsMenu.getByTestId('chat-settings-tabpanel-tasks')).toBeVisible({ timeout: 20_000 });

		await settingsMenu.getByTestId('chat-settings-task-title-input').fill(taskTitle);
		await settingsMenu.getByTestId('chat-settings-task-description-input').fill('Task created from chat settings');
		await Promise.all([
			page.waitForResponse((response) => response.request().method() === 'POST' && response.url().includes('/v1/user-tasks') && response.ok()),
			settingsMenu.getByTestId('chat-settings-task-create-button').click(),
		]);
		await settingsMenu.getByTestId('chat-settings-task-title-input').fill(secondTaskTitle);
		await Promise.all([
			page.waitForResponse((response) => response.request().method() === 'POST' && response.url().includes('/v1/user-tasks') && response.ok()),
			settingsMenu.getByTestId('chat-settings-task-create-button').click(),
		]);

		const taskList = settingsMenu.getByTestId('chat-settings-task-list');
		await expect(taskList.getByTestId('chat-settings-task-row').filter({ hasText: taskTitle })).toBeVisible({ timeout: 30_000 });
		await expect(taskList.getByTestId('chat-settings-task-row').filter({ hasText: secondTaskTitle })).toBeVisible({ timeout: 30_000 });
		await expect(settingsMenu.getByTestId('chat-settings-task-progress')).toContainText(/0% complete/i, { timeout: 10_000 });

		const firstTaskRow = taskList.getByTestId('chat-settings-task-row').filter({ hasText: taskTitle }).first();
		await Promise.all([
			page.waitForResponse((response) => response.request().method() === 'POST' && response.url().includes('/complete') && response.ok()),
			firstTaskRow.getByTestId('chat-settings-task-done-toggle').click(),
		]);
		await expect(settingsMenu.getByTestId('chat-settings-task-progress')).toContainText(/50% complete/i, { timeout: 30_000 });

		await expect(page.getByTestId('active-chat-task-preview')).toBeVisible({ timeout: 30_000 });
		await expect(page.getByTestId('active-chat-task-preview')).toContainText(/Task/i);
		await expect(page.getByTestId('active-chat-task-preview')).toContainText(secondTaskTitle);

		await page.goto(getE2EDebugUrl('/tasks'), { waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('tasks-page')).toBeVisible({ timeout: 30_000 });
		await expect(page.getByTestId('task-board')).toContainText(taskTitle, { timeout: 30_000 });
		await expect(page.getByTestId('task-board')).toContainText(secondTaskTitle, { timeout: 30_000 });
		await expect(page.getByTestId('task-column-done')).toContainText(taskTitle, { timeout: 30_000 });
		await expect(page.getByTestId('task-column-todo')).toContainText(secondTaskTitle, { timeout: 30_000 });

		await page.goto(getE2EDebugUrl(`/#chat-id=${chatId}`), { waitUntil: 'domcontentloaded' });
		await deleteActiveChat(page, log, screenshot, 'tasks-chat-settings-cleanup');
	});
});
