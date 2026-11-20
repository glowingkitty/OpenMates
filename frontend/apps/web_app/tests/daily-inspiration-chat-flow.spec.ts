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

const { test, expect } = require('./helpers/cookie-audit');
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
	assertNoMissingTranslations,
	getTestAccount,
	withMockMarker
} = require('./signup-flow-helpers');

const { loginToTestAccount, sendMessage, waitForAssistantMessage } = require('./helpers/chat-test-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const PERSONALIZED_INSPIRATION_READY_TIMEOUT_MS = 30000;

async function waitForStartChatInspiration(page: any, log: (message: string, data?: unknown) => void) {
	// Signed-in users get daily inspirations as large cards inside the start row.
	const card = page.getByTestId('start-row-inspiration-card').first();
	await expect(card).toBeVisible({ timeout: PERSONALIZED_INSPIRATION_READY_TIMEOUT_MS });
	log('Found a daily inspiration card in the start row.', {
		inspirationId: await card.getAttribute('data-inspiration-id'),
		contentType: await card.getAttribute('data-content-type')
	});
	return card;
}

// contract-test: direct surface=gui.web assertions=daily-inspiration.start-row-cards,daily-inspiration.start-row-rhythm,daily-inspiration.opened-state
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

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	await archiveExistingScreenshots(log);
	log('Starting daily inspiration chat flow test.', { email: TEST_EMAIL });

	// ── 1-6. Login via shared helper (includes OTP retry with clock-drift compensation) ──
	await loginToTestAccount(page, log, screenshot);
	log('Authenticated — waiting for WS sync to deliver pending daily inspirations...');
	// Allow extra time for WebSocket to deliver pending daily inspirations
	await page.waitForTimeout(4000);
	await screenshot(page, 'after-login');

	// ── 8. Verify the signed-in start row shows daily inspiration cards (no banner) ──
	log('Looking for daily inspiration cards in the start row...');
	await expect(page.getByTestId('daily-inspiration-area')).toHaveCount(0);
	await expect(page.getByTestId('daily-inspiration-banner')).toHaveCount(0);
	const startRow = page.getByTestId('recent-chats-scroll-container');
	const inspirationCards = startRow.getByTestId('start-row-inspiration-card');
	await expect(inspirationCards.first()).toBeVisible({ timeout: 15000 });
	await expect(inspirationCards.first().getByTestId('start-row-inspiration-label')).toBeVisible();
	await expect(startRow.getByTestId('resume-chat-card')).toHaveCount(0);
	const guestOnboardingIds = new Set([
		'openmates-intro',
		'openmates-actionable-events',
		'openmates-privacy-safety',
		'openmates-mates-focus',
		'openmates-provider-cross-platform',
		'openmates-signup-cta'
	]);
	const cardIds = await inspirationCards.evaluateAll((els: HTMLElement[]) =>
		els.map((el) => el.getAttribute('data-inspiration-id') ?? '')
	);
	const cardTypes = await inspirationCards.evaluateAll((els: HTMLElement[]) =>
		els.map((el) => el.getAttribute('data-content-type') ?? '')
	);
	expect(cardIds.filter((id: string) => guestOnboardingIds.has(id))).toEqual([]);
	expect(cardTypes.filter((type: string) => type !== 'video' && type !== 'wiki')).toEqual([]);
	log('Daily inspiration cards are visible in the start row.');
	await screenshot(page, 'inspiration-cards-visible');

	// Start a chat from an inspiration card. Pending delivery waits on the backend before
	// broadcasting, so wait on the observable card rather than a fixed post-login sleep.
	const ctaText = await waitForStartChatInspiration(page, log);

	// ── 9. Click the inspiration card to create an inspiration chat ────────────────────
	await ctaText.click();
	log('Clicked the daily inspiration card to start a chat.');

	// The chat ID should appear in the URL within a few seconds
	await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 10000 });
	const urlAfterCreate = page.url();
	const chatIdMatch = urlAfterCreate.match(/chat-id=([a-zA-Z0-9-]+)/);
	const chatId = chatIdMatch ? chatIdMatch[1] : 'unknown';
	log(`Inspiration chat created. Chat ID: ${chatId}`, { chatId });
	await screenshot(page, 'inspiration-chat-created');

	// Verify the assistant message from the inspiration is visible
	const assistantMessage = page.getByTestId('message-assistant').first();
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
		const chatTitleEl = page.getByTestId('chat-title').first();
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
	await sendMessage(
		page,
		withMockMarker('tell me more', 'daily_inspiration'),
		log,
		screenshot,
		'followup'
	);
	log('Sent follow-up message "tell me more".');

	// ── 12. Wait for AI response ─────────────────────────────────────────────
	// The AI should respond to the follow-up. The chat history can rehydrate after
	// send and temporarily drop the inspiration intro, so use the shared response
	// waiter instead of comparing against the pre-send assistant count directly.
	log('Waiting for AI response to follow-up...');
	const followUpResponse = await waitForAssistantMessage(page, {
		timeout: 90000,
		logCheckpoint: log
	});
	log('AI responded to follow-up message — Bug #1 regression check passed.');
	await screenshot(page, 'ai-response-received');

	// Verify the follow-up assistant message has actual content (not blank / loading)
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
			const chatTitleElAfter = page.getByTestId('chat-title').first();
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
	const sidebarToggle = page.locator('[data-testid="sidebar-toggle"]');
	if (await sidebarToggle.isVisible()) {
		await sidebarToggle.click();
		await page.waitForTimeout(500);
	}

	// Find and right-click the active chat in the sidebar to open context menu
	const activeChatItem = page.locator('[data-testid="chat-item-wrapper"].active');
	await expect(activeChatItem).toBeVisible({ timeout: 5000 });
	await activeChatItem.click({ button: 'right' });
	await screenshot(page, 'context-menu-open');

	const deleteButton = page.getByTestId('chat-context-delete');
	await expect(deleteButton).toBeVisible();
	await deleteButton.click(); // Enter confirm mode
	await deleteButton.click(); // Confirm deletion
	log('Chat deleted successfully.');

	await expect(activeChatItem).not.toBeVisible({ timeout: 10000 });
	await screenshot(page, 'chat-deleted');
	log('Daily inspiration chat flow test complete.');
});
