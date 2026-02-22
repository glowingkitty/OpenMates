/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Reminder E2E — Scenario: Same-chat reminder
 *
 * Sets a 1-minute reminder in the current chat, waits for the system message
 * to appear in the SAME chat, verifies content and message ordering
 * (system before the AI follow-up), then deletes the chat.
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
// Helpers
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
	await deleteBtn.click(); // second click confirms
	await expect(activeChatItem).not.toBeVisible({ timeout: 10000 });
	log('Chat deleted.');
}

// ---------------------------------------------------------------------------
// Test
// ---------------------------------------------------------------------------

test('reminder — same-chat: system message fires in the same chat', async ({
	page
}: {
	page: any;
}) => {
	test.slow();
	test.setTimeout(600000); // 10 min

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	const log = createSignupLogger('REMINDER_SAME_CHAT');
	const screenshot = createStepScreenshotter(log);
	await archiveExistingScreenshots(log);

	await loginTestAccount(page, log);
	await screenshot(page, 'logged-in');

	// Open a fresh chat
	const newChatBtn = page.locator('.icon_create');
	if (await newChatBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
		await newChatBtn.click();
		await page.waitForTimeout(2000);
	}

	const editor = page.locator('.editor-content.prose');
	await expect(editor).toBeVisible();
	await editor.click();
	await page.keyboard.type(
		'Set a reminder in this chat for 1 minute from now to check the test results. Just set it, no need to ask questions.'
	);
	await screenshot(page, 'message-typed');

	const sendBtn = page.locator('.send-button');
	await expect(sendBtn).toBeEnabled();
	await sendBtn.click();
	log('Message sent.');

	// Wait for AI confirmation
	const assistantMsgs = page.locator('.message-wrapper.assistant');
	await expect(assistantMsgs.first()).toBeVisible({ timeout: 60000 });

	// Capture stable chat ID after AI response
	await expect(page).toHaveURL(/chat-id=[a-f0-9-]{36}/, { timeout: 15000 });
	const chatId = (page.url().match(/chat-id=([a-zA-Z0-9-]+)/) || [])[1] || 'unknown';
	log('Chat ID confirmed.', { chatId });
	await screenshot(page, 'ai-confirmation');

	// Wait for the reminder system message (3-min window)
	log('Waiting for system message (up to 3 min)...');
	const systemMsg = page.locator('.message-wrapper.system');
	const pollStart = Date.now();
	while (Date.now() - pollStart < 180000) {
		if ((await systemMsg.count()) >= 1) break;
		const elapsed = Math.round((Date.now() - pollStart) / 1000);
		if (elapsed % 15 === 0) log(`Polling... ${elapsed}s elapsed`);
		await page.waitForTimeout(5000);
	}
	expect(await systemMsg.count(), 'System message must have appeared').toBeGreaterThanOrEqual(1);
	await screenshot(page, 'system-message');

	// Verify it fired in the SAME chat
	const chatIdAfter = (page.url().match(/chat-id=([a-zA-Z0-9-]+)/) || [])[1] || '';
	expect(chatIdAfter, 'Reminder must fire in the same chat').toBe(chatId);

	// Verify system message text
	const sysText = await systemMsg.first().textContent();
	log(`System message: "${sysText?.substring(0, 150)}"`);
	expect(sysText).toContain('Reminder');
	expect(sysText?.toLowerCase()).toContain('check the test results');

	// Verify ordering: last system message index < last assistant message index
	log('Verifying message ordering (system before assistant follow-up)...');
	await expect(async () => {
		const all = page.locator('.message-wrapper');
		const count = await all.count();
		let lastSys = -1;
		let lastAsst = -1;
		for (let i = 0; i < count; i++) {
			const cls = await all.nth(i).getAttribute('class');
			if (cls?.includes('system')) lastSys = i;
			if (cls?.includes('assistant')) lastAsst = i;
		}
		expect(lastSys, 'system message must exist').toBeGreaterThan(-1);
		expect(lastAsst, 'assistant message must exist').toBeGreaterThan(-1);
		expect(lastSys, `system (${lastSys}) must precede assistant (${lastAsst})`).toBeLessThan(
			lastAsst
		);
	}).toPass({ timeout: 120000, intervals: [3000] });

	log('Message ordering verified.');
	await screenshot(page, 'ordering-verified');

	await deleteActiveChat(page, log);
	log('PASSED.');
});
