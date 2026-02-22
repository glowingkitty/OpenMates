/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Reminder E2E — Scenario: New-chat reminder
 *
 * Asks the AI to set a 1-minute reminder that fires into a NEW chat.
 * After ~1 minute the backend creates a new chat and delivers the system
 * message there. The browser may or may not auto-navigate.
 *
 * Detection strategy:
 *   1. Record the initial count of sidebar items (.chat-item-wrapper).
 *   2. Poll the URL — if it changes to a different UUID the browser
 *      auto-navigated and we verify the system message there.
 *   3. If the URL does not change, poll the sidebar item count.  When a
 *      new (non-active) item appears, click the first non-active item at
 *      the top of the list (newest chat) to navigate to it.
 *   4. Assert a system message is visible containing "Reminder".
 *
 * NOTE: The sidebar does NOT expose chat IDs in the DOM (no href, no
 * data-chat-id attribute). We rely on item-count delta and position.
 *
 * Runtime: ~5 minutes.
 *
 * REQUIRED ENV VARS:
 *   OPENMATES_TEST_ACCOUNT_EMAIL
 *   OPENMATES_TEST_ACCOUNT_PASSWORD
 *   OPENMATES_TEST_ACCOUNT_OTP_KEY
 */

const { test, expect } = require('@playwright/test');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	generateTotp
} = require('./signup-flow-helpers');

const TEST_EMAIL = process.env.OPENMATES_TEST_ACCOUNT_EMAIL;
const TEST_PASSWORD = process.env.OPENMATES_TEST_ACCOUNT_PASSWORD;
const TEST_OTP_KEY = process.env.OPENMATES_TEST_ACCOUNT_OTP_KEY;

// ---------------------------------------------------------------------------
// Helpers (duplicated per-file so each spec is self-contained)
// ---------------------------------------------------------------------------

async function loginTestAccount(page: any, log: any): Promise<void> {
	await page.goto('/');
	const loginBtn = page.getByRole('button', { name: /login.*sign up|sign up/i });
	await expect(loginBtn).toBeVisible();
	await loginBtn.click();

	const emailInput = page.locator('input[name="username"][type="email"]');
	await expect(emailInput).toBeVisible();
	await emailInput.fill(TEST_EMAIL);
	await page.getByRole('button', { name: /continue/i }).click();

	const pwInput = page.locator('input[type="password"]');
	await expect(pwInput).toBeVisible();
	await pwInput.fill(TEST_PASSWORD);

	const otpInput = page.locator('input[autocomplete="one-time-code"]');
	await expect(otpInput).toBeVisible();
	await otpInput.fill(generateTotp(TEST_OTP_KEY));

	const submitBtn = page.locator('button[type="submit"]', { hasText: /log in|login/i });
	await expect(submitBtn).toBeVisible();
	await submitBtn.click();

	await page.waitForURL(/chat/);
	log('Login successful.');
	await page.waitForTimeout(5000);
}

async function deleteActiveChat(page: any, log: any): Promise<void> {
	const sidebarToggle = page.locator('.sidebar-toggle-button');
	if (await sidebarToggle.isVisible({ timeout: 1000 }).catch(() => false)) {
		await sidebarToggle.click();
		await page.waitForTimeout(500);
	}
	const activeChatItem = page.locator('.chat-item-wrapper.active');
	await expect(activeChatItem).toBeVisible({ timeout: 8000 });
	await activeChatItem.click({ button: 'right' });
	const deleteBtn = page.locator('.menu-item.delete');
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

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	const log = createSignupLogger('REMINDER_NEW_CHAT');
	const screenshot = createStepScreenshotter(log);
	await archiveExistingScreenshots(log);

	await loginTestAccount(page, log);
	await screenshot(page, 'logged-in');

	// Open a fresh source chat
	const newChatBtn = page.locator('.icon_create');
	if (await newChatBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
		await newChatBtn.click();
		await page.waitForTimeout(2000);
	}

	const editor = page.locator('.editor-content.prose');
	await expect(editor).toBeVisible();
	await editor.click();
	await page.keyboard.type(
		'Set a reminder in a new chat for 1 minute from now with the message "new chat reminder test". Just set it, no need to ask questions.'
	);
	await screenshot(page, 'message-typed');

	const sendBtn = page.locator('.send-button');
	await expect(sendBtn).toBeEnabled();
	await sendBtn.click();
	log('Message sent.');

	// Wait for AI confirmation + stable source chat URL
	const assistantMsgs = page.locator('.message-wrapper.assistant');
	await expect(assistantMsgs.first()).toBeVisible({ timeout: 60000 });
	await expect(page).toHaveURL(/chat-id=[a-f0-9-]{36}/, { timeout: 15000 });

	const sourceChatId = (page.url().match(/chat-id=([a-zA-Z0-9-]+)/) || [])[1] || 'unknown';
	log('Source chat ID confirmed.', { sourceChatId });
	await screenshot(page, 'ai-confirmation');

	// Record sidebar item count before the reminder fires — we'll detect the new
	// chat by watching for this count to increase.
	const sidebarItems = page.locator('.chat-item-wrapper');
	const initialItemCount = await sidebarItems.count();
	log(`Sidebar item count before reminder: ${initialItemCount}`);

	// Poll for either: URL changes to a new UUID (auto-navigate), or sidebar
	// gains a new item (new chat appeared but browser stayed on source).
	const POLL_TIMEOUT_MS = 180000; // 3 min
	const pollStart = Date.now();
	let navigatedToNewChat = false;

	log('Polling for new chat (up to 3 min)...');
	while (Date.now() - pollStart < POLL_TIMEOUT_MS) {
		const currentUrl = page.url();
		const currentId = (currentUrl.match(/chat-id=([a-zA-Z0-9-]+)/) || [])[1] || '';

		// Case 1: browser auto-navigated to the new chat
		if (currentId && currentId !== sourceChatId) {
			log('Browser auto-navigated to new chat.', { newChatId: currentId });
			navigatedToNewChat = true;
			break;
		}

		// Case 2: new sidebar item appeared (reminder created a new chat)
		const currentCount = await sidebarItems.count();
		if (currentCount > initialItemCount) {
			log(`New sidebar item detected (was ${initialItemCount}, now ${currentCount}). Clicking it.`);
			// Click the first non-active item — the new chat is at the top of the list
			const allItems = sidebarItems;
			const count = await allItems.count();
			for (let i = 0; i < count; i++) {
				const item = allItems.nth(i);
				const isActive = await item
					.evaluate((el: Element) => el.classList.contains('active'))
					.catch(() => false);
				if (!isActive) {
					await item.click();
					await page.waitForTimeout(2000);
					log('Clicked new (non-active) sidebar item.');
					navigatedToNewChat = true;
					break;
				}
			}
			if (navigatedToNewChat) break;
		}

		const elapsed = Math.round((Date.now() - pollStart) / 1000);
		if (elapsed % 15 === 0) log(`Still waiting... ${elapsed}s elapsed`);
		await page.waitForTimeout(5000);
	}

	await screenshot(page, 'after-poll');

	// Verify a system message is visible in the current view
	const systemMsg = page.locator('.message-wrapper.system');
	const sysCount = await systemMsg.count();
	expect(sysCount, 'At least one system message must be visible in the new chat').toBeGreaterThan(
		0
	);

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

	// Delete the new chat (currently active)
	await deleteActiveChat(page, log);
	log('New chat deleted.');
	await page.waitForTimeout(1000);

	// Delete the source chat if still in sidebar (navigate to it first)
	const currentChatId = (page.url().match(/chat-id=([a-zA-Z0-9-]+)/) || [])[1] || '';
	if (currentChatId === sourceChatId) {
		// Already on source chat
		if (
			await page
				.locator('.chat-item-wrapper.active')
				.isVisible({ timeout: 3000 })
				.catch(() => false)
		) {
			await deleteActiveChat(page, log);
			log('Source chat deleted.');
		}
	} else {
		// Find and click source chat in sidebar, then delete
		// Since there's no data-chat-id, we rely on URL navigation:
		// navigate directly to it via URL then delete.
		const sourceUrl = `${page.url().split('chat-id=')[0]}chat-id=${sourceChatId}`;
		await page.goto(sourceUrl);
		await page.waitForTimeout(2000);
		if (
			await page
				.locator('.chat-item-wrapper.active')
				.isVisible({ timeout: 5000 })
				.catch(() => false)
		) {
			await deleteActiveChat(page, log);
			log('Source chat deleted.');
		} else {
			log('Source chat not found for cleanup — may have been removed already.');
		}
	}

	log('PASSED.');
});
