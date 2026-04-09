/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Reminder E2E — Scenario: Create reminder via top-bar button → settings page
 *
 * Logs in, opens a chat, clicks the reminder bell button in the top bar,
 * verifies the settings reminder creation page opens, fills in the form
 * (date/time 1 minute from now), submits, verifies success message,
 * then waits for the reminder to fire as a system message.
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
	generateTotp,
	getTestAccount,
	getE2EDebugUrl
} = require('./signup-flow-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function loginTestAccount(page: any, log: any): Promise<void> {
	await page.goto(getE2EDebugUrl('/'));

	await page.evaluate(() => {
		localStorage.removeItem('emailLookupRateLimit');
	});

	const loginBtn = page.getByRole('button', { name: /login.*sign up|sign up/i });
	await expect(loginBtn).toBeVisible();
	await loginBtn.click();

	// Click Login tab to switch from signup to login view
	const loginTab = page.getByTestId('tab-login');
	await expect(loginTab).toBeVisible({ timeout: 10000 });
	await loginTab.click();

	const emailInput = page.locator('#login-email-input');
	await expect(emailInput).toBeVisible({ timeout: 15000 });
	await page.waitForTimeout(1000);
	await emailInput.fill(TEST_EMAIL);
	const continueBtn = page.getByRole('button', { name: /continue/i });
	await expect(continueBtn).toBeEnabled({ timeout: 30000 });
	await continueBtn.click();

	const pwInput = page.locator('#login-password-input');
	await expect(pwInput).toBeVisible();
	await pwInput.fill(TEST_PASSWORD);

	const otpInput = page.locator('#login-otp-input');
	await expect(otpInput).toBeVisible({ timeout: 15000 });
	await otpInput.fill(generateTotp(TEST_OTP_KEY));

	const submitBtn = page.locator('button[type="submit"]', { hasText: /log in|login/i });
	await expect(submitBtn).toBeVisible();
	await submitBtn.click();

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
	await deleteBtn.click(); // second click confirms
	await expect(activeChatItem).not.toBeVisible({ timeout: 10000 });
	log('Chat deleted.');
}

/**
 * Get a date/time string ~1 minute from now in the local timezone,
 * suitable for filling date and time input fields.
 */
function getOneMinuteFromNow(): { date: string; time: string } {
	const now = new Date();
	now.setMinutes(now.getMinutes() + 2); // 2 minutes to account for submission delay
	const date = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
	const time = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
	return { date, time };
}

// ---------------------------------------------------------------------------
// Test
// ---------------------------------------------------------------------------

test('reminder — settings page: create reminder via top-bar button and verify it fires', async ({
	page
}: {
	page: any;
}) => {
	test.slow();
	test.setTimeout(600000); // 10 min

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('REMINDER_SETTINGS');
	const screenshot = createStepScreenshotter(log);
	await archiveExistingScreenshots(log);

	await loginTestAccount(page, log);
	await screenshot(page, 'logged-in');

	// ── Step 1: Create a chat so the reminder button appears ──
	log('Creating a new chat...');
	const editor = page.getByTestId('message-editor');
	await expect(editor).toBeVisible({ timeout: 15000 });
	await editor.click();
	await page.keyboard.type('Hello, this is a test chat for the reminder button.');
	const sendBtn = page.locator('[data-action="send-message"]');
	await expect(sendBtn).toBeEnabled();
	await sendBtn.click();
	log('Message sent.');

	// Wait for AI response so the chat is established
	const assistantMsgs = page.getByTestId('message-assistant');
	await expect(assistantMsgs.first()).toBeVisible({ timeout: 60000 });
	log('AI response received.');
	await screenshot(page, 'chat-established');

	// ── Step 2: Click the reminder bell button in the top bar ──
	log('Looking for reminder button in top bar...');
	const reminderBtn = page.locator('[data-testid="chat-reminders-button"]');
	await expect(reminderBtn).toBeVisible({ timeout: 10000 });
	await reminderBtn.click();
	log('Clicked reminder button.');
	await page.waitForTimeout(1000);
	await screenshot(page, 'settings-opened');

	// ── Step 3: Verify the reminder creation form and chat context ──
	log('Verifying reminder creation form...');

	// The settings panel should now show the reminder creation page
	const dateInput = page.locator('#settings-reminder-date');
	await expect(dateInput).toBeVisible({ timeout: 10000 });
	log('Reminder creation form is visible.');

	// Verify chat context is shown (the current chat title should appear)
	const chatContext = page.getByTestId('chat-context');
	await expect(chatContext).toBeVisible({ timeout: 5000 });
	log('Chat context visible in reminder form.');

	// Verify target type dropdown defaults to "This chat"
	const targetDropdown = page.getByTestId('settings-dropdown').first();
	if (await targetDropdown.isVisible({ timeout: 3000 }).catch(() => false)) {
		const selectedValue = await targetDropdown.inputValue();
		log(`Target type: ${selectedValue}`);
	}

	const timeInput = page.locator('#settings-reminder-time');
	await expect(timeInput).toBeVisible({ timeout: 5000 });

	// ── Step 4: Fill in the form ──
	const { date, time } = getOneMinuteFromNow();
	log(`Setting reminder for: ${date} ${time}`);

	// Use Playwright's fill() which sets the value directly on date/time inputs
	// (OS-native date/time pickers are triggered by click on the input in real browsers,
	// but in headless Playwright, fill() is the correct way to set values)
	await dateInput.fill(date);
	await timeInput.fill(time);

	// Fill in a note
	const noteInput = page.getByTestId('settings-input').first();
	if (await noteInput.isVisible({ timeout: 3000 }).catch(() => false)) {
		await noteInput.fill('E2E test reminder - check test results');
		log('Note filled.');
	}

	await screenshot(page, 'form-filled');

	// ── Step 5: Submit the form ──
	const submitBtn2 = page.getByTestId('settings-button-primary');
	await expect(submitBtn2).toBeVisible({ timeout: 5000 });
	await expect(submitBtn2).toBeEnabled();
	await submitBtn2.click();
	log('Form submitted.');
	await page.waitForTimeout(2000);
	await screenshot(page, 'form-submitted');

	// ── Step 6: Verify navigation to reminder app store page ──
	// After creation the settings panel navigates to app_store/reminder which
	// shows ActiveRemindersList with the newly created reminder.
	const reminderItem = page.getByTestId('reminder-item');
	await expect(reminderItem.first()).toBeVisible({ timeout: 15000 });
	log('Navigated to reminder app store page — active reminder visible.');
	await screenshot(page, 'app-store-active-reminders');

	// ── Step 7: Close settings and go back to chat ──
	await page.keyboard.press('Escape');
	await page.waitForTimeout(1000);

	// ── Step 8: Wait for the reminder to fire (3-min window) ──
	log('Waiting for reminder system message (up to 3 min)...');
	const systemMsg = page.getByTestId('message-system');
	const pollStart = Date.now();
	while (Date.now() - pollStart < 180000) {
		if ((await systemMsg.count()) >= 1) break;
		const elapsed = Math.round((Date.now() - pollStart) / 1000);
		if (elapsed % 15 === 0) log(`Polling... ${elapsed}s elapsed`);
		await page.waitForTimeout(5000);
	}
	expect(await systemMsg.count(), 'System message must have appeared').toBeGreaterThanOrEqual(1);
	await screenshot(page, 'reminder-fired');

	// Verify the system message mentions the reminder
	const sysText = await systemMsg.first().textContent();
	log(`System message: "${sysText?.substring(0, 150)}"`);
	expect(sysText?.toLowerCase()).toContain('reminder');

	log('Reminder fired successfully.');
	await screenshot(page, 'test-complete');

	// ── Cleanup ──
	await deleteActiveChat(page, log);
	log('PASSED.');
});
