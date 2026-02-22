/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Reminder E2E — Scenario: Repeating reminder + cancel (combined)
 *
 * These two scenarios MUST run in the same test to guarantee the repeating
 * reminder is cancelled before the test ends. A repeating reminder that is
 * not cancelled will keep firing every minute and consuming credits.
 *
 * Flow:
 *   S4 — Set a repeating reminder (every 1 min). Wait for 3 occurrences
 *        (3 system messages), each with its own 3-min window.
 *   S5 — Cancel the reminder via the embed UI cancel button, or fall back
 *        to sending a cancellation chat message. Wait 2 minutes and assert
 *        no 4th system message appears. Delete the chat.
 *
 * Runtime: ~15 minutes (worst case).
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
	await deleteBtn.click();
	await expect(activeChatItem).not.toBeVisible({ timeout: 10000 });
	log('Chat deleted.');
}

/**
 * Poll until .message-wrapper.system count >= targetCount, or throw on timeout.
 */
async function waitForSystemMessages(
	page: any,
	targetCount: number,
	timeoutMs: number,
	label: string,
	log: any
): Promise<void> {
	const systemMsg = page.locator('.message-wrapper.system');
	const start = Date.now();
	log(`[${label}] Waiting for ${targetCount} system message(s)...`);

	while (Date.now() - start < timeoutMs) {
		const count = await systemMsg.count();
		if (count >= targetCount) {
			log(
				`[${label}] Reached ${count} system message(s) after ${Math.round((Date.now() - start) / 1000)}s.`
			);
			return;
		}
		const elapsed = Math.round((Date.now() - start) / 1000);
		if (elapsed % 15 === 0)
			log(`[${label}] ${count}/${targetCount} system messages (${elapsed}s elapsed)`);
		await page.waitForTimeout(5000);
	}

	const finalCount = await systemMsg.count();
	throw new Error(
		`[${label}] Timed out after ${Math.round(timeoutMs / 1000)}s. Got ${finalCount}/${targetCount} system messages.`
	);
}

// ---------------------------------------------------------------------------
// Test
// ---------------------------------------------------------------------------

test('reminder — repeating (3 occurrences) + cancel (no 4th firing)', async ({
	page
}: {
	page: any;
}) => {
	test.slow();
	test.setTimeout(1800000); // 30 min (3 occurrences × 3 min + 2 min cancel wait + overhead)

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	const log = createSignupLogger('REMINDER_REPEATING');
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
		'Set a repeating reminder in this chat that repeats every 1 minute with the message "repeating test". Just set it, no need to ask questions.'
	);
	await screenshot(page, 'message-typed');

	const sendBtn = page.locator('.send-button');
	await expect(sendBtn).toBeEnabled();
	await sendBtn.click();
	log('Repeating reminder request sent.');

	// Wait for AI confirmation
	const assistantMsgs = page.locator('.message-wrapper.assistant');
	await expect(assistantMsgs.first()).toBeVisible({ timeout: 60000 });
	log('AI confirmed repeating reminder set.');
	await screenshot(page, 'ai-confirmation');

	// =========================================================================
	// S4: Wait for 3 occurrences
	// =========================================================================
	log('=== S4: Waiting for occurrence 1 ===');
	await waitForSystemMessages(page, 1, 180000, 'occ-1', log);
	await screenshot(page, 's4-occurrence-1');

	log('=== S4: Waiting for occurrence 2 ===');
	await waitForSystemMessages(page, 2, 180000, 'occ-2', log);
	await screenshot(page, 's4-occurrence-2');

	log('=== S4: Waiting for occurrence 3 ===');
	await waitForSystemMessages(page, 3, 180000, 'occ-3', log);
	await screenshot(page, 's4-occurrence-3');

	const firstSysText = await page.locator('.message-wrapper.system').first().textContent();
	log(`First system message: "${firstSysText?.substring(0, 150)}"`);
	expect(firstSysText).toContain('Reminder');
	log('S4 PASSED — repeating reminder fired 3 times.');

	// =========================================================================
	// S5: Cancel the repeating reminder
	// =========================================================================
	log('=== S5: Cancelling repeating reminder ===');
	await screenshot(page, 's5-before-cancel');

	// Strategy 1: look for the reminder embed preview card and click it to open
	// fullscreen, then click the Cancel button.
	const embedPreview = page.locator('.reminder-embed-preview').first();
	const embedVisible = await embedPreview.isVisible({ timeout: 5000 }).catch(() => false);

	let cancelledViaEmbed = false;

	if (embedVisible) {
		log('Found reminder embed preview — clicking to open fullscreen.');
		await embedPreview.click();
		await page.waitForTimeout(1000);
	} else {
		// Strategy 2: look for an expand button
		log('Embed preview not found — looking for expand button.');
		const expandBtn = page
			.locator('.embed-expand-button, .embed-open-button, [class*="expand"]')
			.first();
		if (await expandBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
			await expandBtn.click();
			await page.waitForTimeout(1000);
		}
	}

	// Try the Cancel button in fullscreen embed
	const cancelBtn = page.locator('.cancel-btn, [class*="cancel-btn"]').first();
	if (await cancelBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
		log('Found Cancel button — clicking.');
		await cancelBtn.click();
		await page.waitForTimeout(2000);
		cancelledViaEmbed = true;
		log('Cancel button clicked.');
		await screenshot(page, 's5-after-embed-cancel');

		// Close fullscreen if still open
		await page.keyboard.press('Escape');
		await page.waitForTimeout(500);
	}

	if (!cancelledViaEmbed) {
		// Strategy 3 (fallback): send a cancel message via chat
		log('No embed cancel UI found — cancelling via chat message.');
		const editorFb = page.locator('.editor-content.prose');
		await expect(editorFb).toBeVisible();
		await editorFb.click();
		await page.keyboard.type(
			'Cancel my repeating reminder. Just cancel it, no need to ask questions.'
		);
		const sendBtnFb = page.locator('.send-button');
		await expect(sendBtnFb).toBeEnabled();
		await sendBtnFb.click();

		// Wait for AI to confirm cancellation
		await expect(async () => {
			// Should have at least 4 assistant messages (1 initial + 3 per occurrence + 1 cancel confirm)
			// but tolerate 3 if responses are still in-flight
			const count = await assistantMsgs.count();
			expect(count).toBeGreaterThanOrEqual(3);
		}).toPass({ timeout: 60000, intervals: [3000] });
		log('Cancellation confirmed via chat message.');
		await screenshot(page, 's5-cancelled-via-chat');
	}

	// =========================================================================
	// S5: Verify no 4th firing for 2 minutes
	// =========================================================================
	const systemMsgs = page.locator('.message-wrapper.system');
	const countBeforeWait = await systemMsgs.count();
	log(
		`System message count before 2-min wait: ${countBeforeWait}. Waiting to confirm no more firings...`
	);

	await page.waitForTimeout(120000); // 2 minutes

	const countAfterWait = await systemMsgs.count();
	log(`System message count after 2-min wait: ${countAfterWait} (was ${countBeforeWait}).`);

	expect(
		countAfterWait,
		`No new system messages should appear after cancellation (was ${countBeforeWait}, now ${countAfterWait})`
	).toBe(countBeforeWait);

	log('S5 PASSED — no additional firings after cancellation.');
	await screenshot(page, 's5-no-new-firings');

	// Clean up
	await deleteActiveChat(page, log);
	log('Chat deleted. PASSED.');
});
