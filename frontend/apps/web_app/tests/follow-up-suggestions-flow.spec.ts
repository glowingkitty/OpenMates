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

const { test, expect } = require('./helpers/cookie-audit');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	assertNoMissingTranslations,
	getTestAccount,
	withMockMarker
} = require('./signup-flow-helpers');

const { loginToTestAccount, waitForAssistantMessage } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { expectNoFollowUpSuggestions } = require('./helpers/llm-eval');

const consoleLogs: string[] = [];
const networkActivities: string[] = [];

const LLM_QUICK_TIP_SLUGS = [
	'search-current-info-next-time',
	'travel-can-add-local-context',
	'use-apps-for-better-results'
];

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

async function navigateToAiSettings(page: any, log: (message: string, metadata?: Record<string, unknown>) => void): Promise<void> {
	const settingsToggle = page.locator('#settings-menu-toggle');
	await expect(settingsToggle).toBeVisible({ timeout: 10000 });
	await settingsToggle.click();

	const settingsMenu = page.locator('[data-testid="settings-menu"].visible');
	await expect(settingsMenu).toBeVisible({ timeout: 10000 });

	const aiMenuItem = settingsMenu.getByRole('menuitem', { name: /^AI$/i }).first();
	await expect(aiMenuItem).toBeVisible({ timeout: 5000 });
	await aiMenuItem.click();

	await expect(page.getByTestId('ai-settings')).toBeVisible({ timeout: 8000 });
	log('AI settings page loaded.');
}

async function closeSettings(page: any, log: (message: string, metadata?: Record<string, unknown>) => void): Promise<void> {
	const closeButton = page.getByTestId('icon-button-close');
	if (await closeButton.isVisible({ timeout: 3000 }).catch(() => false)) {
		await closeButton.click();
		log('Closed settings.');
	}
}

async function setFollowUpSuggestions(
	page: any,
	enabled: boolean,
	log: (message: string, metadata?: Record<string, unknown>) => void,
): Promise<void> {
	const toggleWrapper = page.getByTestId('follow-up-suggestions-toggle');
	await expect(toggleWrapper).toBeVisible({ timeout: 10000 });
	const checkbox = toggleWrapper.locator('input[type="checkbox"]');
	const isChecked = await checkbox.evaluate((el: HTMLInputElement) => el.checked);
	if (isChecked !== enabled) {
		await toggleWrapper.click();
		await expect(async () => {
			const nextChecked = await checkbox.evaluate((el: HTMLInputElement) => el.checked);
			expect(nextChecked).toBe(enabled);
		}).toPass({ timeout: 10000 });
		log(`Set follow-up suggestions ${enabled ? 'on' : 'off'}.`);
	} else {
		log(`Follow-up suggestions already ${enabled ? 'on' : 'off'}.`);
	}
}

async function expectLlmQuickTipCard(
	page: any,
	log: (message: string, metadata?: Record<string, unknown>) => void,
): Promise<void> {
	const quickTipCard = page.getByTestId('quick-tip-card');
	await expect(quickTipCard).toBeVisible({ timeout: 90000 });

	const slug = await quickTipCard.getAttribute('data-quick-tip-slug');
	log(`Quick tip card visible with slug: ${slug}`);
	expect(slug).toBeTruthy();
	expect(LLM_QUICK_TIP_SLUGS).toContain(slug as string);
	await expect(quickTipCard).toContainText(/tip/i);
}

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
	const newChatButton = page.getByTestId('new-chat-button');
	if (await newChatButton.isVisible({ timeout: 3000 }).catch(() => false)) {
		await newChatButton.click();
		await page.waitForTimeout(1500);
	}
	await screenshot(page, 'new-chat-ready');

	// Send a travel-planning prompt that should make the postprocessor LLM choose
	// a quick-tip slug. The chat is only one turn, so this cannot be the hardcoded
	// long-chat quick tip.
	const message = 'I am planning a weekend trip to Kyoto and Osaka with food, transit, and local event questions.';
	log(`Sending: "${message}"`);
	const messageEditor = page.getByTestId('message-editor');
	await expect(messageEditor).toBeVisible({ timeout: 10000 });
	await messageEditor.click();
	await page.keyboard.type(withMockMarker(message, 'quick_tip_travel_planning'));

	const sendButton = page.locator('[data-action="send-message"]');
	await expect(sendButton).toBeEnabled();
	await sendButton.click();
	log('Message sent.');

	// Wait for AI response
	await waitForAssistantMessage(page, { which: 'last', logCheckpoint: log });
	await screenshot(page, 'ai-response-received');
	log('AI response received.');

	await expectLlmQuickTipCard(page, log);
	await screenshot(page, 'quick-tip-visible');

	// Follow-up suggestions only appear when the message input is focused.
	// Click the editor to focus it — this triggers the suggestions to render.
	await messageEditor.click();
	log('Clicked editor to focus it (required for suggestions to appear).');

	// Wait for follow-up suggestions to appear
	// The suggestions wrapper fades in after the response completes and input is focused
	const suggestionsWrapper = page.getByTestId('suggestions-wrapper');

	await expect(async () => {
		// Re-click editor on each retry in case focus was lost
		await messageEditor.click();
		await expect(suggestionsWrapper).toBeVisible();
	}).toPass({ timeout: 60000 });

	await screenshot(page, 'suggestions-visible');
	log('Follow-up suggestions wrapper visible.');

	// Verify at least one suggestion chip is present
	const suggestionChips = page.getByTestId('follow-up-suggestion-item');
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
	const activeChatItem = page.locator('[data-testid="chat-item-wrapper"].active');
	if (await activeChatItem.isVisible({ timeout: 5000 }).catch(() => false)) {
		await activeChatItem.click({ button: 'right' });
		const deleteButton = page.getByTestId('chat-context-delete');
		await expect(deleteButton).toBeVisible({ timeout: 5000 });
		await deleteButton.click();
		await deleteButton.click();
		log('Test chat deleted.');
	}

	log('Test complete.');
});

test('disables follow-up suggestions in settings and avoids proactive follow-up prompts', async ({
	page
}: {
	page: any;
}) => {
	test.slow();
	test.setTimeout(360000);

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

	const log = createSignupLogger('FOLLOW_UP_SUGGESTIONS_DISABLED');
	const screenshot = createStepScreenshotter(log);
	await archiveExistingScreenshots(log);

	await loginToTestAccount(page, log, screenshot);
	await page.waitForTimeout(3000);

	try {
		await navigateToAiSettings(page, log);
		await screenshot(page, 'ai-settings-open');
		await setFollowUpSuggestions(page, false, log);
		await screenshot(page, 'follow-up-suggestions-disabled');
		await closeSettings(page, log);

		const newChatButton = page.getByTestId('new-chat-button');
		if (await newChatButton.isVisible({ timeout: 3000 }).catch(() => false)) {
			await newChatButton.click();
			await page.waitForTimeout(1500);
		}

		const message = 'Explain why Saturn has rings in three concise bullet points.';
		const messageEditor = page.getByTestId('message-editor');
		await expect(messageEditor).toBeVisible({ timeout: 10000 });
		await messageEditor.click();
		await page.keyboard.type(withMockMarker(message, 'follow_up_suggestions_disabled'));

		const sendButton = page.locator('[data-action="send-message"]');
		await expect(sendButton).toBeEnabled();
		await sendButton.click();
		log('Message sent with follow-up suggestions disabled.');

		const assistantMessage = await waitForAssistantMessage(page, { which: 'last', logCheckpoint: log });
		await expect(async () => {
			const msgText = await assistantMessage.textContent();
			expect((msgText || '').trim().length).toBeGreaterThan(20);
		}).toPass({ timeout: 60000, intervals: [2000, 3000, 5000] });
		await screenshot(page, 'ai-response-no-follow-ups');

		await messageEditor.click();
		await expect(page.getByTestId('suggestions-wrapper')).not.toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('follow-up-suggestion-item')).toHaveCount(0, { timeout: 15000 });
		log('Verified follow-up suggestion chips are not visible.');

		const assistantText = (await assistantMessage.textContent()) || '';
		const evaluation = await expectNoFollowUpSuggestions(page, assistantText, log);
		log('Verified assistant text did not include proactive follow-up suggestions.', evaluation);
	} finally {
		await navigateToAiSettings(page, log).catch(() => undefined);
		await setFollowUpSuggestions(page, true, log).catch(() => undefined);
		await closeSettings(page, log).catch(() => undefined);

		const activeChatItem = page.locator('[data-testid="chat-item-wrapper"].active');
		if (await activeChatItem.isVisible({ timeout: 5000 }).catch(() => false)) {
			await activeChatItem.click({ button: 'right' });
			const deleteButton = page.getByTestId('chat-context-delete');
			if (await deleteButton.isVisible({ timeout: 5000 }).catch(() => false)) {
				await deleteButton.click();
				await deleteButton.click();
				log('Test chat deleted.');
			}
		}
	}
});
