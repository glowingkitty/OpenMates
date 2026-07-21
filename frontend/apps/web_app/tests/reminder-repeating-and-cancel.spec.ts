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
 *   S4 — Set a daily repeating reminder starting 2 min from now.
 *   S5 — Cancel the reminder via chat before it fires. Wait 3 minutes and
 *        assert no system reminder appears. Delete the chat.
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
const BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL ?? 'https://app.dev.openmates.org';
const API_BASE_URL = BASE_URL.replace('://app.dev.', '://api.dev.').replace('://app.', '://api.');

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

// ---------------------------------------------------------------------------
// Test
// ---------------------------------------------------------------------------

test('reminder — daily repeating cancellation prevents firing', async ({
	page
}: {
	page: any;
}) => {
	test.slow();
	test.setTimeout(900000); // 15 min (setup + cancellation + 3 min no-fire wait + overhead)

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
		'Set a daily repeating reminder in this chat starting 2 minutes from now with the message "repeating test". Just set it, no need to ask questions.'
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
	// S4: Cancel the repeating reminder before the first occurrence
	// =========================================================================
	log('=== S4: Cancelling repeating reminder before first occurrence ===');
	await screenshot(page, 's5-before-cancel');

	const reminderPreview = page.getByTestId('reminder-embed-preview').first();
	await expect(reminderPreview).toBeVisible({ timeout: 30000 });
	await expect(reminderPreview).toHaveAttribute('data-reminder-id', /[a-f0-9-]{36}/, { timeout: 30000 });
	const reminderId = await reminderPreview.getAttribute('data-reminder-id');
	expect(reminderId, 'Reminder ID should be available on the reminder preview').toBeTruthy();

	const cancelResult = await page.evaluate(
		async ({ apiBaseUrl, reminderId }: { apiBaseUrl: string; reminderId: string }) => {
			const response = await fetch(`${apiBaseUrl}/v1/apps/reminder/skills/cancel-reminder`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				credentials: 'include',
				body: JSON.stringify({ reminder_id: reminderId })
			});
			let body: any = null;
			try {
				body = await response.json();
			} catch {
				/* ignore non-JSON errors */
			}
			return { ok: response.ok, status: response.status, body };
		},
		{ apiBaseUrl: API_BASE_URL, reminderId: reminderId as string }
	);
	const cancelData = cancelResult.body?.data || cancelResult.body;
	expect(cancelResult.ok, `Cancel request failed: ${JSON.stringify(cancelResult)}`).toBe(true);
	expect(cancelData?.success, `Cancel skill failed: ${JSON.stringify(cancelResult)}`).toBe(true);
	log('Cancellation confirmed via REST skill.', { reminderId });
	await screenshot(page, 's5-cancelled-via-chat');

	// =========================================================================
	// S5: Verify no first firing after cancellation
	// =========================================================================
	const systemMsgs = page.getByTestId('message-system');
	const countBeforeWait = await systemMsgs.count();
	expect(countBeforeWait, 'Reminder should be cancelled before any system message fires').toBe(0);
	log(`System message count before 3-min wait: ${countBeforeWait}. Waiting to confirm cancellation.`);

	await page.waitForTimeout(180000); // 3 minutes

	const countAfterWait = await systemMsgs.count();
	log(`System message count after 3-min wait: ${countAfterWait} (was ${countBeforeWait}).`);

	expect(
		countAfterWait,
		`No system reminder should appear after cancellation (was ${countBeforeWait}, now ${countAfterWait})`
	).toBe(0);

	log('S5 PASSED — reminder did not fire after cancellation.');
	await screenshot(page, 's5-no-new-firings');

	// Clean up
	await deleteActiveChat(page, log);
	log('Chat deleted. PASSED.');
});
