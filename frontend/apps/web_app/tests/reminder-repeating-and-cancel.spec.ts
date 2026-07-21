/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Reminder E2E — Scenario: Daily repeating reminder + cancel (combined)
 *
 * These two scenarios MUST run in the same test to guarantee the repeating
 * reminder is cancelled before the test ends. A repeating reminder that is
 * not cancelled will keep firing over time and consuming credits.
 *
 * Flow:
 *   S4 — Set a daily repeating reminder starting 1 min from now. Wait for
 *        the first occurrence.
 *   S5 — Cancel the reminder via the embed UI cancel button, or fall back
 *        to sending a cancellation chat message. Wait 2 minutes and assert
 *        no duplicate immediate system message appears. Delete the chat.
 *
 * Runtime: ~10 minutes (worst case).
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
const { openSignupInterface, submitPasswordAndHandleOtp, waitForChatReady } = require('./helpers/chat-test-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function loginTestAccount(page: any, log: any): Promise<void> {
	await page.goto(getE2EDebugUrl('/'));

	// Clear any rate-limit localStorage flag from a previous test run
	await page.evaluate(() => {
		localStorage.removeItem('emailLookupRateLimit');
	});

	await openSignupInterface(page, 30000);

	// Click Login tab to switch from signup to login view
	const loginTab = page.getByTestId('tab-login');
	await expect(loginTab).toBeVisible({ timeout: 10000 });
	await loginTab.click();

	const emailInput = page.getByTestId('login-email-input');
	await expect(emailInput).toBeVisible({ timeout: 15000 });
	await page.waitForTimeout(1000);
	await emailInput.fill(TEST_EMAIL);
	// Wait for the continue button to be enabled (async email validation / rate-limit check)
	const continueBtn = page.getByTestId('login-continue-button');
	await expect(continueBtn).toBeEnabled({ timeout: 30000 });
	await continueBtn.click();

	const pwInput = page.getByTestId('login-password-input');
	await expect(pwInput).toBeVisible();
	await pwInput.fill(TEST_PASSWORD);

	await submitPasswordAndHandleOtp(page, TEST_OTP_KEY, log);

	await waitForChatReady(page, log);
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
	const systemMsg = page.getByTestId('message-system');
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

test('reminder — daily repeating first occurrence + cancel', async ({
	page
}: {
	page: any;
}) => {
	test.slow();
	test.setTimeout(900000); // 15 min (first occurrence + 2 min cancel wait + overhead)

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('REMINDER_REPEATING');
	const screenshot = createStepScreenshotter(log);
	await archiveExistingScreenshots(log);

	await loginTestAccount(page, log);
	await screenshot(page, 'logged-in');

	// Open a fresh chat
	const newChatBtn = page.getByTestId('new-chat-button');
	if (await newChatBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
		await newChatBtn.click();
		await page.waitForTimeout(2000);
	}

	const editor = page.getByTestId('message-editor');
	await expect(editor).toBeVisible();
	await editor.click();
	await page.keyboard.type(
		'Set a daily repeating reminder in this chat starting 1 minute from now with the message "repeating test". Just set it, no need to ask questions.'
	);
	await screenshot(page, 'message-typed');

	const sendBtn = page.locator('[data-action="send-message"]');
	await expect(sendBtn).toBeEnabled();
	await sendBtn.click();
	log('Repeating reminder request sent.');

	// Wait for AI confirmation
	const assistantMsgs = page.getByTestId('message-assistant');
	await expect(assistantMsgs.first()).toBeVisible({ timeout: 60000 });
	log('AI confirmed repeating reminder set.');
	await screenshot(page, 'ai-confirmation');

	// =========================================================================
	// S4: Wait for the first occurrence. The product supports daily/weekly/monthly
	// repeats, not minute-level repeats, so the next occurrence is intentionally
	// not awaited in this spec.
	// =========================================================================
	log('=== S4: Waiting for occurrence 1 ===');
	await waitForSystemMessages(page, 1, 180000, 'occ-1', log);
	await screenshot(page, 's4-occurrence-1');

	const firstSysText = await page.getByTestId('message-system').first().textContent();
	log(`First system message: "${firstSysText?.substring(0, 150)}"`);
	expect(firstSysText).toContain('Reminder');
	log('S4 PASSED — daily repeating reminder fired once.');

	// =========================================================================
	// S5: Cancel the repeating reminder
	// =========================================================================
	log('=== S5: Cancelling repeating reminder ===');
	await screenshot(page, 's5-before-cancel');

	// Strategy 1: look for the reminder embed preview card and click it to open
	// fullscreen, then click the Cancel button.
	const embedPreview = page.getByTestId('reminder-embed-preview').first();
	const embedVisible = await embedPreview.isVisible({ timeout: 5000 }).catch(() => false);

	let cancelledViaEmbed = false;

	if (embedVisible) {
		log('Found reminder embed preview — clicking to open fullscreen.');
		await embedPreview.click();
		await page.waitForTimeout(1000);
	} else {
		// Strategy 2: look for an expand button
		log('Embed preview not found — looking for expand button.');
		const expandBtn = page.locator('[data-testid="embed-expand-button"], [data-testid="embed-open-button"]').first();
		if (await expandBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
			await expandBtn.click();
			await page.waitForTimeout(1000);
		}
	}

	// Try the Cancel button in fullscreen embed
	const cancelBtn = page.getByTestId('cancel-btn').first();
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
		const editorFb = page.getByTestId('message-editor');
		await expect(editorFb).toBeVisible();
		await editorFb.click();
		await page.keyboard.type(
			'Cancel my repeating reminder. Just cancel it, no need to ask questions.'
		);
		const sendBtnFb = page.locator('[data-action="send-message"]');
		await expect(sendBtnFb).toBeEnabled();
		await sendBtnFb.click();

		// Wait for AI to confirm cancellation
		await expect(async () => {
			const count = await assistantMsgs.count();
			expect(count).toBeGreaterThanOrEqual(2);
		}).toPass({ timeout: 60000, intervals: [3000] });
		log('Cancellation confirmed via chat message.');
		await screenshot(page, 's5-cancelled-via-chat');
	}

	// =========================================================================
	// S5: Verify no duplicate immediate firing for 2 minutes
	// =========================================================================
	const systemMsgs = page.getByTestId('message-system');
	const countBeforeWait = await systemMsgs.count();
	log(
		`System message count before 2-min wait: ${countBeforeWait}. Waiting to confirm no duplicate immediate firing...`
	);

	await page.waitForTimeout(120000); // 2 minutes

	const countAfterWait = await systemMsgs.count();
	log(`System message count after 2-min wait: ${countAfterWait} (was ${countBeforeWait}).`);

	expect(
		countAfterWait,
		`No duplicate system messages should appear after cancellation (was ${countBeforeWait}, now ${countAfterWait})`
	).toBe(countBeforeWait);

	log('S5 PASSED — no duplicate firings after cancellation.');
	await screenshot(page, 's5-no-new-firings');

	// Clean up
	await deleteActiveChat(page, log);
	log('Chat deleted. PASSED.');
});
