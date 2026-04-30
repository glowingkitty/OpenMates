/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Reminder E2E — Scenario: New-chat reminder
 *
 * Asks the AI to set a 1-minute reminder that fires into a NEW chat.
 * After ~1 minute the backend creates a new chat and delivers the system
 * message there via the reminder_fired WebSocket event.
 *
 * Detection strategy:
 *   1. Inject a window-level listener via page.evaluate() BEFORE sending
 *      the message — this catches the "reminderFiredInChat" CustomEvent
 *      that the chatSyncService dispatches the moment a new-chat reminder
 *      fires.  The handler stores the new chat_id in window.__newReminderChatId.
 *   2. Poll page.evaluate(() => window.__newReminderChatId) every 5 s for up
 *      to 5 minutes.  When it is set, navigate directly to the new chat via
 *      URL (/<base>?chat-id=<id>) and assert the system message is visible.
 *   3. Fallback: also watch for sidebar item count increase (in case the
 *      custom event fires before the listener is wired but the chat still
 *      appears in the sidebar).
 *
 * Runtime: ~5 minutes.
 *
 * REQUIRED ENV VARS:
 *   OPENMATES_TEST_ACCOUNT_EMAIL
 *   OPENMATES_TEST_ACCOUNT_PASSWORD
 *   OPENMATES_TEST_ACCOUNT_OTP_KEY
 */

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getTestAccount,
	getE2EDebugUrl
} = require('./signup-flow-helpers');
const { submitPasswordAndHandleOtp } = require('./helpers/chat-test-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

// ---------------------------------------------------------------------------
// Helpers (duplicated per-file so each spec is self-contained)
// ---------------------------------------------------------------------------

async function loginTestAccount(page: any, log: any): Promise<void> {
	await page.goto(getE2EDebugUrl('/'));

	// Clear any rate-limit localStorage flag from a previous test run
	await page.evaluate(() => {
		localStorage.removeItem('emailLookupRateLimit');
	});

	const loginBtn = page.getByTestId('header-login-signup-btn');
	await expect(loginBtn).toBeVisible();
	await loginBtn.click();

	// Click Login tab to switch from signup to login view
	const loginTab = page.getByTestId('tab-login');
	await expect(loginTab).toBeVisible({ timeout: 10000 });
	await loginTab.click();

	const emailInput = page.locator('#login-email-input');
	await expect(emailInput).toBeVisible({ timeout: 15000 });
	// Small delay before filling to allow the page to fully stabilize
	await page.waitForTimeout(1000);
	await emailInput.fill(TEST_EMAIL);
	// Wait for the continue button to become enabled (async email validation may disable it briefly)
	const continueBtn = page.getByRole('button', { name: /continue/i });
	await expect(continueBtn).toBeEnabled({ timeout: 30000 });
	await continueBtn.click();

	const pwInput = page.locator('#login-password-input');
	await expect(pwInput).toBeVisible();
	await pwInput.fill(TEST_PASSWORD);

	await submitPasswordAndHandleOtp(page, TEST_OTP_KEY, log);

	await page.waitForURL(/chat/);
	log('Login successful.');
	await page.waitForTimeout(5000);
}

async function deleteActiveChat(page: any, log: any): Promise<void> {
	const sidebarToggle = page.locator('[data-testid="sidebar-toggle"]');
	if (await sidebarToggle.isVisible({ timeout: 1000 }).catch(() => false)) {
		await sidebarToggle.click();
		await page.waitForTimeout(500);
	}
	const activeChatItem = page.locator('[data-testid="chat-item-wrapper"].active');
	await expect(activeChatItem).toBeVisible({ timeout: 8000 });
	await activeChatItem.click({ button: 'right' });
	const deleteBtn = page.getByTestId('chat-context-delete');
	await expect(deleteBtn).toBeVisible({ timeout: 5000 });
	await deleteBtn.click();
	await deleteBtn.click();
	await expect(activeChatItem).not.toBeVisible({ timeout: 10000 });
	log('Chat deleted.');
}

// ---------------------------------------------------------------------------
// Test
// ---------------------------------------------------------------------------

test('reminder — new-chat: reminder fires into a newly created chat', async ({
	page
}: {
	page: any;
}) => {
	test.slow();
	test.setTimeout(600000); // 10 min

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('REMINDER_NEW_CHAT');
	const screenshot = createStepScreenshotter(log);
	await archiveExistingScreenshots(log);

	await loginTestAccount(page, log);
	await screenshot(page, 'logged-in');

	// Open a fresh source chat
	const newChatBtn = page.getByTestId('new-chat-button');
	if (await newChatBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
		await newChatBtn.click();
		await page.waitForTimeout(2000);
	}

	// Inject the event listener BEFORE sending the message so we capture
	// the reminderFiredInChat event even if it fires quickly.
	// The chatSyncService dispatches this CustomEvent on itself (an EventTarget),
	// but we need to intercept it at the window level. The handler in
	// chatSyncServiceHandlersAppSettings.ts dispatches on the serviceInstance
	// which is NOT window — so we intercept it via the notificationStore
	// toast click navigation OR via the custom event re-dispatched on window.
	//
	// Simpler approach: also patch the existing CustomEvent dispatch so it bubbles
	// to window. We do this by wrapping EventTarget.prototype.dispatchEvent.
	await page.evaluate(() => {
		(window as any).__newReminderChatId = null;
		(window as any).__newReminderTargetType = null;

		// Wrap EventTarget.dispatchEvent so any reminderFiredInChat event is
		// also visible at window level regardless of which object fires it.
		const _original = EventTarget.prototype.dispatchEvent;
		(EventTarget.prototype as any).dispatchEvent = function (event: Event) {
			if (event.type === 'reminderFiredInChat') {
				const detail = (event as CustomEvent).detail;
				if (detail && detail.target_type === 'new_chat' && detail.chat_id) {
					(window as any).__newReminderChatId = detail.chat_id;
					(window as any).__newReminderTargetType = detail.target_type;
					console.info('[TEST] Captured reminderFiredInChat (new_chat):', detail.chat_id);
				}
			}
			return _original.call(this, event);
		};
	});

	const editor = page.getByTestId('message-editor');
	await expect(editor).toBeVisible();
	await editor.click();
	await page.keyboard.type(
		'Set a reminder for exactly 1 minute from now. The reminder should fire in a NEW chat (target_type: new_chat). Title the new chat "Reminder Test". The reminder message should be "new chat reminder test". Do NOT ask questions, just set it immediately.'
	);
	await screenshot(page, 'message-typed');

	const sendBtn = page.locator('[data-action="send-message"]');
	await expect(sendBtn).toBeEnabled();
	await sendBtn.click();
	log('Message sent.');

	// Wait for AI confirmation + stable source chat URL
	const assistantMsgs = page.getByTestId('message-assistant');
	await expect(assistantMsgs.first()).toBeVisible({ timeout: 60000 });
	await expect(page).toHaveURL(/chat-id=[a-f0-9-]{36}/, { timeout: 15000 });

	const sourceChatId = (page.url().match(/chat-id=([a-zA-Z0-9-]+)/) || [])[1] || 'unknown';
	log('Source chat ID confirmed.', { sourceChatId });
	await screenshot(page, 'ai-confirmation');

	// Record sidebar item count before the reminder fires — used as fallback
	const sidebarItems = page.getByTestId('chat-item-wrapper');
	const initialItemCount = await sidebarItems.count();
	log(`Sidebar item count before reminder: ${initialItemCount}`);

	// Poll for the new chat — primary method is the intercepted window event,
	// fallback is sidebar count increase or URL change.
	const POLL_TIMEOUT_MS = 300000; // 5 min — AI may set reminder at +1 min which
	// takes up to 2 min to process; give generous headroom
	const pollStart = Date.now();
	let newChatId: string | null = null;

	log('Polling for new chat via event + sidebar (up to 5 min)...');
	while (Date.now() - pollStart < POLL_TIMEOUT_MS) {
		// Primary: check if the intercepted event gave us a chat_id
		const capturedId = await page
			.evaluate(() => (window as any).__newReminderChatId)
			.catch(() => null);
		if (capturedId) {
			log(`reminderFiredInChat event captured new chat ID: ${capturedId}`);
			newChatId = capturedId;
			break;
		}

		// Secondary: browser auto-navigated to the new chat
		const currentUrl = page.url();
		const currentId = (currentUrl.match(/chat-id=([a-zA-Z0-9-]+)/) || [])[1] || '';
		if (currentId && currentId !== sourceChatId) {
			log('Browser auto-navigated to new chat.', { newChatId: currentId });
			newChatId = currentId;
			break;
		}

		// Tertiary: new sidebar item appeared
		const currentCount = await sidebarItems.count();
		if (currentCount > initialItemCount) {
			log(`New sidebar item detected (was ${initialItemCount}, now ${currentCount}).`);
			// Walk items to find the first non-active one (newest at top)
			const count = await sidebarItems.count();
			for (let i = 0; i < count; i++) {
				const item = sidebarItems.nth(i);
				const isActive = await item
					.evaluate((el: Element) => el.classList.contains('active'))
					.catch(() => false);
				if (!isActive) {
					await item.click();
					await page.waitForTimeout(2000);
					const newUrl = page.url();
					newChatId = (newUrl.match(/chat-id=([a-zA-Z0-9-]+)/) || [])[1] || null;
					log('Clicked new sidebar item.', { newChatId });
					break;
				}
			}
			if (newChatId) break;
		}

		const elapsed = Math.round((Date.now() - pollStart) / 1000);
		if (elapsed % 15 === 0) log(`Still waiting... ${elapsed}s elapsed`);
		await page.waitForTimeout(5000);
	}

	await screenshot(page, 'after-poll');

	if (!newChatId) {
		throw new Error('Timed out waiting for new-chat reminder (5 min). No new chat detected.');
	}

	// Navigate to the new chat (direct URL — most reliable approach)
	// URL format is /#chat-id=<uuid> (hash-based routing)
	const currentFullUrl = page.url();
	const originAndPath = currentFullUrl.split('#')[0]; // everything before the hash
	const newChatUrl = `${originAndPath}#chat-id=${newChatId}`;
	log(`Navigating to new chat: ${newChatUrl}`);
	await page.goto(newChatUrl);
	await page.waitForTimeout(3000);
	await screenshot(page, 'new-chat-navigated');

	// Assert system message is visible
	const systemMsg = page.getByTestId('message-system');
	// Give the UI time to decrypt and render the message
	await expect(async () => {
		expect(await systemMsg.count()).toBeGreaterThan(0);
	}).toPass({ timeout: 30000, intervals: [2000] });

	const sysText = await systemMsg.first().textContent();
	log(`System message: "${sysText?.substring(0, 150)}"`);
	expect(sysText).toContain('Reminder');
	log('New-chat reminder verified.');
	await screenshot(page, 'system-message-verified');

	// Wait for AI follow-up in new chat
	await expect(async () => {
		expect(await assistantMsgs.count()).toBeGreaterThanOrEqual(1);
	}).toPass({ timeout: 90000, intervals: [3000] });
	log('AI follow-up confirmed.');
	await screenshot(page, 'complete');

	// Clean up: delete the new chat (currently active)
	await deleteActiveChat(page, log);
	log('New chat deleted.');
	await page.waitForTimeout(1000);

	// Clean up: delete the source chat
	const afterCleanupUrl = page.url().split('#')[0];
	const sourceUrl = `${afterCleanupUrl}#chat-id=${sourceChatId}`;
	await page.goto(sourceUrl);
	await page.waitForTimeout(2000);
	if (
		await page
			.locator('[data-testid="chat-item-wrapper"].active')
			.isVisible({ timeout: 5000 })
			.catch(() => false)
	) {
		await deleteActiveChat(page, log);
		log('Source chat deleted.');
	} else {
		log('Source chat not found for cleanup — may have been removed already.');
	}

	log('PASSED.');
});
