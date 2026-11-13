/**
 * Chat orchestration E2E (TASK-2269): any chat starts and coordinates other main chats.
 * Real stack, real AI, no mocks; dev server only, run through
 * scripts/chat_orchestration_web_real_test.py (personal dev test account, leases). Plan: docs/plans/chat-orchestration-main-chats/plan.yml
 * Spec: specifications/features/chat-orchestration/specification.yml
 *
 * 1. Ask a new chat to start a second chat with a brief and report back.
 * 2. The creator chat shows a "Started chat" event; clicking it opens the spawned chat,
 *    whose first message is the brief and which links back to its creator.
 * 3. The spawned chat answers; via the creator link the creator shows a report and/or finished event.
 *
 * REQUIRED ENV VARS: OPENMATES_TEST_ACCOUNT_EMAIL / _PASSWORD / _OTP_KEY, PLAYWRIGHT_TEST_BASE_URL
 */

import { test, expect, attachConsoleListeners, attachNetworkListeners } from './console-monitor';
import {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getTestAccount
} from './signup-flow-helpers';
import {
	loginToTestAccount,
	startNewChat,
	sendMessage,
	waitForAssistantMessage,
	deleteActiveChat
} from './helpers/chat-test-helpers';
import { skipWithoutCredentials } from './helpers/env-guard';

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount(1);

const PROMPT =
	"Start a new chat titled 'Kitchen tile quotes' with the brief: list three kinds of kitchen floor tiles " +
	'in one short sentence each, then report back to me.';

// contract-test: direct surface=gui.web assertions=chat-orchestration.spawn.main-chat-is-normal,chat-orchestration.events.creator-system-events,chat-orchestration.report.creator-skill,chat-orchestration.status.automatic
test('a chat starts another main chat, follows its work and receives its report', async ({
	page
}: {
	page: any;
}) => {
	attachConsoleListeners(page);
	attachNetworkListeners(page);
	test.slow();
	test.setTimeout(600000);

	const log = createSignupLogger('CHAT_ORCHESTRATION');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'chat-orchestration' });
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	await archiveExistingScreenshots(log);

	await loginToTestAccount(page, log, screenshot);
	await startNewChat(page, log);
	await sendMessage(page, PROMPT, log, screenshot, 'creator-request');
	await expect(page).toHaveURL(/chat-id=[0-9a-f]{8}-/, { timeout: 30000 });
	const chatIdOf = (url: string) => url.match(/chat-id=([0-9a-f-]{36})/)?.[1];
	const creatorChatId = chatIdOf(page.url());
	expect(creatorChatId).toBeTruthy();

	// The creator chat shows the "Started chat" event once the device spawned the chat.
	const startedEvent = page
		.getByTestId('chat-orchestration-event')
		.filter({ hasText: /Started chat/ })
		.first();
	await expect(startedEvent).toBeVisible({ timeout: 240000 });
	await screenshot(page, 'creator-started-event');

	// Open the spawned chat: the brief is its first user message and it links back to the creator.
	await startedEvent.click();
	await expect(page.getByTestId('chat-creator-link')).toBeVisible({ timeout: 60000 });
	await expect(page.getByTestId('message-user').first()).toContainText(/kitchen floor tiles/i, {
		timeout: 60000
	});
	const spawnedChatId = chatIdOf(page.url());
	expect(spawnedChatId).toBeTruthy();
	expect(spawnedChatId).not.toBe(creatorChatId);
	await screenshot(page, 'spawned-chat-opened');

	await waitForAssistantMessage(page, { which: 'last', logCheckpoint: log });
	await expect(page.getByTestId('stop-processing-button')).not.toBeVisible({ timeout: 180000 });
	await screenshot(page, 'spawned-chat-answer');

	// Back to the creator via the link: a report and/or finished event follows.
	await page.getByTestId('chat-creator-link').click();
	await expect(page).toHaveURL(new RegExp(`chat-id=${creatorChatId}`), { timeout: 30000 });
	const followUp = page
		.getByTestId('chat-orchestration-event')
		.filter({ hasText: /Report from|finished/ })
		.first();
	await expect(followUp).toBeVisible({ timeout: 240000 });
	await screenshot(page, 'creator-report-or-finished');

	// Cleanup: delete the creator chat, then the spawned chat.
	await deleteActiveChat(page, log, screenshot);
	await page.goto(`/#chat-id=${spawnedChatId}`);
	await expect(page.getByTestId('chat-creator-link')).toBeVisible({ timeout: 60000 });
	await deleteActiveChat(page, log, screenshot);
	await screenshot(page, 'done');
});
