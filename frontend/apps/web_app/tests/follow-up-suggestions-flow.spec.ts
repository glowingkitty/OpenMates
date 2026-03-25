/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Follow-Up Suggestions Flow Test
 *
 * Tests that after an AI response, follow-up suggestion chips appear
 * (FollowUpSuggestions.svelte), and clicking a chip populates the
 * message editor with the suggestion text, making the send button visible.
 *
 * Architecture:
 * - After an AI response, the FollowUpSuggestions component renders as
 *   `.suggestions-wrapper` with up to 3 `button.suggestion-item` chips.
 * - The chips are AI-generated and non-deterministic in their text, but they
 *   always appear after a successful response when the feature is enabled.
 * - Clicking a chip calls `onSuggestionClick(text)` → fills the TipTap
 *   editor → `.send-button` becomes visible.
 * - The test uses a short factual question to reliably trigger suggestions.
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 */

const { test, expect } = require('@playwright/test');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	generateTotp,
	assertNoMissingTranslations,
	getTestAccount,
	getE2EDebugUrl,
	withMockMarker
} = require('./signup-flow-helpers');

const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const consoleLogs: string[] = [];
const networkActivities: string[] = [];

test.beforeEach(async () => {
	consoleLogs.length = 0;
	networkActivities.length = 0;
});

// eslint-disable-next-line no-empty-pattern
test.afterEach(async ({}, testInfo: any) => {
	if (testInfo.status !== 'passed') {
		console.log('\n--- DEBUG INFO ON FAILURE ---');
		console.log('\n[RECENT CONSOLE LOGS]');
		consoleLogs.slice(-30).forEach((log: string) => console.log(log));
		console.log('\n[RECENT NETWORK ACTIVITIES]');
		networkActivities.slice(-20).forEach((activity: string) => console.log(activity));
		console.log('\n--- END DEBUG INFO ---\n');
	}
});

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

// ---------------------------------------------------------------------------
// Test: Follow-up suggestions appear and clicking one populates editor
// ---------------------------------------------------------------------------

test('shows follow-up suggestion chips after AI response and clicking one fills the editor', async ({
	page
}: {
	page: any;
}) => {
	test.slow();
	test.setTimeout(300000);

	page.on('console', (msg: any) =>
		consoleLogs.push(`[${new Date().toISOString()}] [${msg.type()}] ${msg.text()}`)
	);
	page.on('request', (req: any) =>
		networkActivities.push(`[${new Date().toISOString()}] >> ${req.method()} ${req.url()}`)
	);
	page.on('response', (res: any) =>
		networkActivities.push(`[${new Date().toISOString()}] << ${res.status()} ${res.url()}`)
	);

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('FOLLOW_UP_SUGGESTIONS');
	const screenshot = createStepScreenshotter(log);
	await archiveExistingScreenshots(log);

	await loginToTestAccount(page, log, screenshot);
	await page.waitForTimeout(3000);

	// Start a new chat
	const newChatButton = page.locator('.icon_create');
	if (await newChatButton.isVisible({ timeout: 3000 }).catch(() => false)) {
		await newChatButton.click();
		await page.waitForTimeout(1500);
	}
	await screenshot(page, 'new-chat-ready');

	// Send a short factual question that reliably triggers follow-up suggestions
	const message = 'What is the capital of Japan?';
	log(`Sending: "${message}"`);
	const messageEditor = page.locator('.editor-content.prose');
	await expect(messageEditor).toBeVisible({ timeout: 10000 });
	await messageEditor.click();
	await page.keyboard.type(withMockMarker(message, 'follow_up_suggestions'));

	const sendButton = page.locator('.send-button');
	await expect(sendButton).toBeEnabled();
	await sendButton.click();
	log('Message sent.');

	// Wait for AI response
	const assistantResponse = page.locator('.message-wrapper.assistant');
	await expect(assistantResponse.last()).toBeVisible({ timeout: 45000 });
	await screenshot(page, 'ai-response-received');
	log('AI response received.');

	// Follow-up suggestions only appear when the message input is focused.
	// Click the editor to focus it — this triggers the suggestions to render.
	await messageEditor.click();
	log('Clicked editor to focus it (required for suggestions to appear).');

	// Wait for follow-up suggestions to appear
	// The suggestions wrapper fades in after the response completes and input is focused
	const suggestionsWrapper = page.locator('.suggestions-wrapper');

	await expect(async () => {
		// Re-click editor on each retry in case focus was lost
		await messageEditor.click();
		await expect(suggestionsWrapper).toBeVisible();
	}).toPass({ timeout: 60000 });

	await screenshot(page, 'suggestions-visible');
	log('Follow-up suggestions wrapper visible.');

	// Verify at least one suggestion chip is present
	const suggestionChips = page.locator('button.suggestion-item');
	const chipCount = await suggestionChips.count();
	log(`Number of suggestion chips: ${chipCount}`);
	expect(chipCount).toBeGreaterThan(0);

	// Get the text of the first suggestion
	const firstChip = suggestionChips.first();
	const suggestionText = await firstChip.textContent();
	log(`Clicking suggestion: "${suggestionText}"`);
	await screenshot(page, 'before-chip-click');

	// Click the first suggestion chip
	await firstChip.click();
	log('Clicked suggestion chip.');
	await page.waitForTimeout(500);
	await screenshot(page, 'after-chip-click');

	// Verify the editor was populated with the suggestion text
	// The editor content should now have the suggestion text
	const editorContent = await messageEditor.textContent();
	log(`Editor content after chip click: "${editorContent}"`);
	expect(editorContent).toBeTruthy();
	expect(editorContent!.trim().length).toBeGreaterThan(0);

	// Send button should now be visible (editor has content)
	await expect(sendButton).toBeVisible({ timeout: 5000 });
	log('Send button is visible — editor was populated by suggestion chip.');

	await assertNoMissingTranslations(page);

	// Clean up: delete the chat
	const activeChatItem = page.locator('.chat-item-wrapper.active');
	if (await activeChatItem.isVisible({ timeout: 5000 }).catch(() => false)) {
		await activeChatItem.click({ button: 'right' });
		const deleteButton = page.locator('.menu-item.delete');
		await expect(deleteButton).toBeVisible({ timeout: 5000 });
		await deleteButton.click();
		await deleteButton.click();
		log('Test chat deleted.');
	}

	log('Test complete.');
});
