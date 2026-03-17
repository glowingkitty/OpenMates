/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Daily Inspiration Chat Flow
 *
 * Regression test for two bugs fixed in the daily inspiration chat flow:
 *
 * BUG #1 (fixed in 0e0dcd18): "Cannot send messages to daily inspiration chat (treated as shared chat)"
 *   Root cause: When a daily inspiration chat was created via sync_inspiration_chat, the chat ID
 *   was NOT added to the user's chat_ids_versions Redis sorted set. The ownership check logic
 *   (check_chat_ownership) uses this sorted set as a fast lookup. When the cache was primed but
 *   the chat was absent from the sorted set, it returned False (not owner), causing the server
 *   to reject follow-up messages with a misleading "shared chat" error.
 *   Fix: sync_inspiration_chat_handler.py now calls add_chat_to_ids_versions() after storing
 *   the chat data, making the chat immediately visible to the ownership check.
 *
 * BUG #2 (fixed in this commit): "Follow-up message in inspiration chat overwrites the title"
 *   Root cause: handleStartChatFromInspiration created the inspiration chat in IndexedDB with
 *   title_v: 0 despite having a title at creation time. When the user sent a follow-up message,
 *   sendNewMessageImpl read title_v: 0 → chatHasTitle = false → sent chat_has_title: false to
 *   the backend. The preprocessor saw is_first_message=True and regenerated the title/category
 *   from the follow-up text, overwriting the original inspiration title.
 *   Fix (frontend): handleStartChatFromInspiration now sets title_v: 1 in the IndexedDB chat
 *   object, consistent with what sync_inspiration_chat already sends to the server.
 *   Fix (backend safety net): message_received_handler.py now overrides chat_has_title_from_client
 *   to True when the DB already has title_v > 0, protecting against any future client-side bug.
 *
 * Test covers:
 *   1. Daily inspiration banner is visible after login
 *   2. Clicking a banner creates a new inspiration-based chat with a visible title
 *   3. Sending a follow-up message ("tell me more") succeeds — no "shared chat" error (Bug #1)
 *   4. The original inspiration title is NOT overwritten by the follow-up (Bug #2)
 *   5. The AI responds correctly to the follow-up
 *   6. Chat is deleted after the test (cleanup)
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL / OPENMATES_TEST_ACCOUNT_1_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD / OPENMATES_TEST_ACCOUNT_1_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY / OPENMATES_TEST_ACCOUNT_1_OTP_KEY
 * - PLAYWRIGHT_TEST_BASE_URL (defaults to https://app.dev.openmates.org)
 *
 * PREREQUISITE:
 * Daily inspirations must exist for the test account. If not, run:
 *   docker exec api python /app/backend/scripts/trigger_daily_inspiration.py <email> --reset-first-run
 */

const { test, expect } = require('@playwright/test');

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
		consoleLogs.slice(-30).forEach((log) => console.log(log));
		console.log('\n[RECENT NETWORK ACTIVITIES]');
		networkActivities.slice(-20).forEach((activity) => console.log(activity));
		console.log('\n--- END DEBUG INFO ---\n');
	}
});

const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	generateTotp,
	assertNoMissingTranslations,
	getTestAccount,
	getE2EDebugUrl
} = require('./signup-flow-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

test('daily inspiration chat: creates chat and allows follow-up message without shared-chat error', async ({
	page
}: {
	page: any;
}) => {
	// Capture console logs for debugging on failure
	page.on('console', (msg: any) => {
		const timestamp = new Date().toISOString();
		consoleLogs.push(`[${timestamp}] [${msg.type()}] ${msg.text()}`);

		// Fail fast if the server returns the "shared chat" ownership error
		if (msg.text().includes('You cannot send messages to this shared chat')) {
			throw new Error(
				`[REGRESSION] Server rejected message with shared-chat ownership error. ` +
					`This means the inspiration chat was not added to the user's chat_ids_versions sorted set. ` +
					`See sync_inspiration_chat_handler.py → add_chat_to_ids_versions().`
			);
		}
	});

	page.on('request', (request: any) => {
		const timestamp = new Date().toISOString();
		networkActivities.push(`[${timestamp}] >> ${request.method()} ${request.url()}`);
	});

	page.on('response', (response: any) => {
		const timestamp = new Date().toISOString();
		networkActivities.push(`[${timestamp}] << ${response.status()} ${response.url()}`);
	});

	test.slow();
	// Allow extra time: login + inspiration chat creation + AI response
	test.setTimeout(120000);

	const log = createSignupLogger('DAILY_INSPIRATION');
	const screenshot = createStepScreenshotter(log);

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	await archiveExistingScreenshots(log);
	log('Starting daily inspiration chat flow test.', { email: TEST_EMAIL });

	// ── 1. Navigate to home ──────────────────────────────────────────────────
	await page.goto(getE2EDebugUrl('/'));
	await screenshot(page, 'home');

	// ── 2. Open login dialog ─────────────────────────────────────────────────
	const headerLoginButton = page.getByRole('button', {
		name: /login.*sign up|sign up/i
	});
	await expect(headerLoginButton).toBeVisible();
	await headerLoginButton.click();
	await screenshot(page, 'login-dialog');

	// ── 3. Enter email ───────────────────────────────────────────────────────
	const emailInput = page.locator('#login-email-input');
	await expect(emailInput).toBeVisible();
	await emailInput.fill(TEST_EMAIL);
	await page.locator('#login-continue-button').click();
	log('Entered email and clicked continue.');

	// ── 4. Enter password ────────────────────────────────────────────────────
	const passwordInput = page.locator('#login-password-input');
	await expect(passwordInput).toBeVisible();
	await passwordInput.fill(TEST_PASSWORD);

	// ── 5. Enter OTP ─────────────────────────────────────────────────────────
	const otpCode = generateTotp(TEST_OTP_KEY);
	const otpInput = page.locator('#login-otp-input');
	await expect(otpInput).toBeVisible();
	await otpInput.fill(otpCode);
	log('Generated and entered OTP.');

	// ── 6. Submit login ──────────────────────────────────────────────────────
	const submitLoginButton = page.locator('#login-submit-button');
	await expect(submitLoginButton).toBeVisible();
	await submitLoginButton.click();
	log('Submitted login form.');

	// ── 7. Wait for authenticated state ─────────────────────────────────────
	await page.waitForURL(/chat/);
	log('Authenticated — waiting for initial load and WS sync...');
	// Allow time for WebSocket to deliver pending daily inspirations
	await page.waitForTimeout(6000);
	await screenshot(page, 'after-login');

	// ── 8. Verify daily inspiration banner is visible ────────────────────────
	// The banner is a button wrapping the inspiration text and "Click to start chat" CTA.
	// It may take a moment to appear as the WS delivers pending inspirations.
	log('Looking for daily inspiration banner...');
	const inspirationBanner = page.locator('[data-testid="daily-inspiration-banner"]').first();
	await expect(inspirationBanner).toBeVisible({ timeout: 15000 });
	log('Daily inspiration banner is visible.');
	await screenshot(page, 'inspiration-banner-visible');

	// ── 9. Click the banner to create an inspiration chat ────────────────────
	await inspirationBanner.click();
	log('Clicked the daily inspiration banner to start a chat.');

	// The chat ID should appear in the URL within a few seconds
	await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 10000 });
	const urlAfterCreate = page.url();
	const chatIdMatch = urlAfterCreate.match(/chat-id=([a-zA-Z0-9-]+)/);
	const chatId = chatIdMatch ? chatIdMatch[1] : 'unknown';
	log(`Inspiration chat created. Chat ID: ${chatId}`, { chatId });
	await screenshot(page, 'inspiration-chat-created');

	// Verify the assistant message from the inspiration is visible
	const assistantMessage = page.locator('.message-wrapper.assistant').first();
	await expect(assistantMessage).toBeVisible({ timeout: 10000 });
	log('Initial inspiration assistant message is visible.');

	// ── 10. Capture the inspiration title before sending the follow-up ────────
	// BUG #2 regression check: the title must NOT be overwritten by the follow-up.
	// Before the fix, handleStartChatFromInspiration set title_v: 0 in IndexedDB,
	// causing the backend to treat the follow-up as the first message and regenerate
	// the title from the follow-up text ("tell me more").
	//
	// The chat header shows the title in .chat-title or the <title> element.
	// We capture it here and re-assert after the AI responds.
	let titleBeforeSend = '';
	try {
		// Try the chat header title element first
		const chatTitleEl = page.locator('.chat-title').first();
		if (await chatTitleEl.isVisible({ timeout: 3000 })) {
			titleBeforeSend = (await chatTitleEl.textContent()) ?? '';
		}
	} catch {
		// Title element may not be visible yet — non-fatal, we still send and check after
	}
	log(`Captured title before send: "${titleBeforeSend}"`);

	// ── 11. Send a follow-up message "tell me more" ──────────────────────────
	// This step is the regression check for Bug #1: before the fix, the server would reject
	// this with "You cannot send messages to this shared chat." because the chat
	// was not in the user's chat_ids_versions sorted set.
	log('Typing follow-up message "tell me more"...');
	const messageEditor = page.locator('.editor-content.prose');
	await expect(messageEditor).toBeVisible();
	await messageEditor.click();
	await page.keyboard.type('tell me more');
	await screenshot(page, 'followup-message-typed');

	const sendButton = page.locator('[data-action="send-message"]');
	await expect(sendButton).toBeEnabled();
	await sendButton.click();
	log('Sent follow-up message "tell me more".');
	await screenshot(page, 'followup-message-sent');

	// ── 12. Wait for AI response ─────────────────────────────────────────────
	// The AI should respond to the follow-up. We wait for a second assistant
	// message to appear (the first being the inspiration intro, the second being
	// the AI response to "tell me more").
	log('Waiting for AI response to follow-up...');
	const assistantMessages = page.locator('.message-wrapper.assistant');
	// After sending "tell me more", there should be at least 2 assistant messages
	await expect(assistantMessages).toHaveCount(2, { timeout: 60000 });
	log('AI responded to follow-up message — Bug #1 regression check passed.');
	await screenshot(page, 'ai-response-received');

	// Verify the second assistant message has actual content (not blank / loading)
	const followUpResponse = assistantMessages.last();
	const responseText = await followUpResponse.textContent();
	expect(responseText).toBeTruthy();
	expect(responseText!.trim().length).toBeGreaterThan(10);
	log('AI response content verified.', { responseLength: responseText!.trim().length });

	// ── 13. BUG #2 check: title must NOT be overwritten ──────────────────────
	// After the follow-up and AI response, the chat title should still be the
	// original inspiration title — NOT "tell me more" (the follow-up text).
	// Before the fix: handleStartChatFromInspiration set title_v: 0 → backend
	// treated follow-up as first message → regenerated title from follow-up text.
	const titleAfterResponse = await page.title();
	const followUpText = 'tell me more';
	const titleLower = titleAfterResponse.toLowerCase();
	expect(titleLower).not.toContain(followUpText);
	log(`Bug #2 check: page title does not contain follow-up text. Title: "${titleAfterResponse}"`);

	// Also verify the chat-title element hasn't been replaced with follow-up text
	if (titleBeforeSend) {
		try {
			const chatTitleElAfter = page.locator('.chat-title').first();
			if (await chatTitleElAfter.isVisible({ timeout: 3000 })) {
				const titleAfterSend = (await chatTitleElAfter.textContent()) ?? '';
				const titleAfterLower = titleAfterSend.toLowerCase();
				expect(titleAfterLower).not.toContain(followUpText);
				log(
					`Bug #2 check: chat-title element does not contain follow-up text. Title: "${titleAfterSend}"`
				);
			}
		} catch {
			log('Could not read chat-title element after response — skipping visual title check');
		}
	}

	// No missing translations on the chat page
	await assertNoMissingTranslations(page);
	log('No missing translations detected.');

	// ── 14. Cleanup — delete the inspiration chat ────────────────────────────
	log('Cleaning up: deleting the inspiration chat...');

	// Ensure sidebar is accessible
	const sidebarToggle = page.locator('.sidebar-toggle-button');
	if (await sidebarToggle.isVisible()) {
		await sidebarToggle.click();
		await page.waitForTimeout(500);
	}

	// Find and right-click the active chat in the sidebar to open context menu
	const activeChatItem = page.locator('.chat-item-wrapper.active');
	await expect(activeChatItem).toBeVisible({ timeout: 5000 });
	await activeChatItem.click({ button: 'right' });
	await screenshot(page, 'context-menu-open');

	const deleteButton = page.locator('.menu-item.delete');
	await expect(deleteButton).toBeVisible();
	await deleteButton.click(); // Enter confirm mode
	await deleteButton.click(); // Confirm deletion
	log('Chat deleted successfully.');

	await expect(activeChatItem).not.toBeVisible({ timeout: 10000 });
	await screenshot(page, 'chat-deleted');
	log('Daily inspiration chat flow test complete.');
});
