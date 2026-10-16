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

// contract-test: direct surface=gui.web assertions=chats.surface.semantic-parity
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
		'Do not search the web. Keep each sub-chat task simple. After both finish, summarize their findings in the parent chat ' +
		'and end the final answer with this exact sentence: Oceans and forests summary complete.';

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
	await expect(page.getByTestId('message-assistant').last()).toContainText(
		'Oceans and forests summary complete.',
		{ timeout: 180_000 }
	);
	await screenshot(page, 'parent-synthesis-completed');

	const parentChatHash = new URL(page.url()).hash;
	await subChatCards.first().click();
	await expect(page.getByTestId('return-to-parent-button')).toHaveCount(0);
	await expect(page.getByTestId('chat-close-button')).toBeVisible({ timeout: 30_000 });
	await expect(page.getByTestId('sub-chat-broadcast-toggle')).toBeVisible({ timeout: 30_000 });
	// Generated child metadata must survive hydration independently from the
	// detailed report used by parent synthesis. No model/provider override.
	const childId = new URL(page.url()).hash.match(/chat-id=([^&]+)/)?.[1];
	expect(childId).toBeTruthy();
	await expect.poll(async () => page.evaluate(async (id: string) => {
		const db = await new Promise<IDBDatabase>((resolve, reject) => {
			const request = indexedDB.open('chats_db');
			request.onsuccess = () => resolve(request.result);
			request.onerror = () => reject(request.error);
		});
		try {
			const chat = await new Promise<any>((resolve, reject) => {
				const request = db.transaction('chats', 'readonly').objectStore('chats').get(id);
				request.onsuccess = () => resolve(request.result);
				request.onerror = () => reject(request.error);
			});
			return Boolean(chat?.encrypted_chat_summary && chat?.encrypted_title
				&& chat?.chat_summary?.trim() && chat.chat_summary.length <= 1000 && chat.title_v > 0);
		} finally { db.close(); }
	}, childId), { timeout: 60_000, message: 'Child has generated concise summary and title after hydration' }).toBe(true);
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

	await page.getByTestId('chat-close-button').click();
	await expect.poll(() => new URL(page.url()).hash).toBe(parentChatHash);

	await deleteActiveChat(page, log, screenshot, 'real-sub-chat-cleanup');
	log('Real sub-chat inference pipeline completed successfully.');
});
