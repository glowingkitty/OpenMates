/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Real sub-chat inference regression test.
 *
 * Exercises the live LLM + tool pipeline without route mocks or IndexedDB
 * injection: parent chat spawn, server-created sub-chat sync, sub-chat send,
 * and assistant response rendering inside the sub-chat.
 */
export {};

const { test, expect } = require('./console-monitor');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getTestAccount
} = require('./signup-flow-helpers');
const {
	loginToTestAccount,
	startNewChat,
	sendMessage,
	deleteActiveChat,
	waitForAssistantMessage
} = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

test('real LLM sub-chat pipeline supports sending inside a synced sub-chat', async ({ page }: { page: any }) => {
	test.slow();
	test.setTimeout(420_000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('sub-chats-real-inference');
	await archiveExistingScreenshots(log);
	const screenshot = createStepScreenshotter(log);

	await loginToTestAccount(page, log, screenshot);
	await startNewChat(page, log);

	const spawnPrompt =
		'Use the start-sub-chats tool to create exactly two short research sub-chats: one for oceans and one for forests. ' +
		'Do not search the web. Keep each sub-chat task simple and answer briefly in the parent chat after starting them.';

	await sendMessage(page, spawnPrompt, log, screenshot, 'spawn-sub-chats');
	await waitForAssistantMessage(page, { timeout: 180_000, logCheckpoint: log });
	await screenshot(page, 'parent-response-after-spawn');

	const carousel = page.getByTestId('sub-chats-carousel');
	await expect(carousel).toBeVisible({ timeout: 180_000 });
	const subChatCards = page.getByTestId('sub-chat-card');
	await expect(subChatCards.first()).toBeVisible({ timeout: 30_000 });
	const cardCount = await subChatCards.count();
	expect(cardCount, 'Real LLM/tool pipeline should create at least one sub-chat card.').toBeGreaterThan(0);
	log(`Sub-chat cards visible: ${cardCount}`);
	await screenshot(page, 'sub-chat-cards-visible');

	await subChatCards.first().click();
	await expect(page.getByTestId('return-to-parent-button')).toBeVisible({ timeout: 30_000 });
	await expect(page.getByTestId('sub-chat-broadcast-toggle')).toBeVisible({ timeout: 30_000 });
	await screenshot(page, 'real-sub-chat-opened');

	const subChatUrl = page.url();
	expect(subChatUrl, 'Clicking a real sub-chat card should navigate to a chat hash.').toMatch(/chat-id=/);
	log(`Opened sub-chat URL: ${subChatUrl}`);

	await sendMessage(
		page,
		'Reply with one short sentence confirming this sub-chat can receive messages.',
		log,
		screenshot,
		'send-inside-sub-chat'
	);
	const subChatAssistant = await waitForAssistantMessage(page, { timeout: 180_000, logCheckpoint: log });
	await expect(subChatAssistant).not.toBeEmpty({ timeout: 60_000 });
	await screenshot(page, 'sub-chat-message-completed');

	const returnButton = page.getByTestId('return-to-parent-button');
	if (await returnButton.isVisible({ timeout: 5000 }).catch(() => false)) {
		await returnButton.click({ timeout: 5000 }).catch(async () => returnButton.click({ force: true }));
		await page.waitForTimeout(1000);
	}

	await deleteActiveChat(page, log, screenshot, 'real-sub-chat-cleanup');
	log('Real sub-chat inference pipeline completed successfully.');
});
