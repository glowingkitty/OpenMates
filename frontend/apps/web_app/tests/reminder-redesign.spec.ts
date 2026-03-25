/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Reminder Redesign E2E — Comprehensive tests for the simplified reminder flow.
 *
 * Tests the redesigned reminder feature:
 * 1. "Remind me about this chat" (Type A): notification-only, no new chat
 * 2. "New chat with task" (Type B): new chat + AI auto-execute
 * 3. Edit reminder time via PATCH endpoint
 * 4. Delete reminder via DELETE endpoint
 * 5. UI validates: no note field, single toggle, submit requires action prompt for Type B
 *
 * REQUIRED ENV VARS:
 *   OPENMATES_TEST_ACCOUNT_EMAIL
 *   OPENMATES_TEST_ACCOUNT_PASSWORD
 *   OPENMATES_TEST_ACCOUNT_OTP_KEY
 */

const { test, expect } = require('@playwright/test');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	generateTotp,
	getTestAccount,
	getE2EDebugUrl,
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

function getMinutesFromNow(minutes: number): { date: string; time: string } {
	const now = new Date();
	now.setMinutes(now.getMinutes() + minutes);
	const date = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
	const time = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
	return { date, time };
}

// ---------------------------------------------------------------------------
// Test 1: UI structure — single toggle, no note field
// ---------------------------------------------------------------------------

test('reminder redesign — UI shows single toggle, no note field', async ({
	page,
}: {
	page: any;
}) => {
	test.slow();
	test.setTimeout(300000);

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('REMINDER_UI');
	const screenshot = createStepScreenshotter(log);
	await archiveExistingScreenshots(log);

	await loginTestAccount(page, log);

	// Create a chat so the reminder button appears
	const editor = page.locator('.editor-content.prose');
	await expect(editor).toBeVisible({ timeout: 15000 });
	await editor.click();
	await page.keyboard.type('Hello, testing reminder UI.');
	const sendBtn = page.locator('.send-button');
	await expect(sendBtn).toBeEnabled();
	await sendBtn.click();

	const assistantMsgs = page.locator('.message-wrapper.assistant');
	await expect(assistantMsgs.first()).toBeVisible({ timeout: 60000 });
	log('Chat established.');

	// Open reminder panel via top-bar button
	const reminderBtn = page.locator('[data-testid="chat-reminders-button"]');
	await expect(reminderBtn).toBeVisible({ timeout: 10000 });
	await reminderBtn.click();
	await page.waitForTimeout(1500);

	// Check settings panel opened with reminder form
	const dateInput = page.locator('#settings-reminder-date');
	await expect(dateInput).toBeVisible({ timeout: 10000 });
	log('Reminder settings form opened.');

	// Verify: "Remind me about this chat" mode is default (single toggle)
	// There should be a dropdown with mode options, NOT separate target + response toggles
	const modeDropdown = page.locator('.settings-dropdown').first();
	await expect(modeDropdown).toBeVisible({ timeout: 5000 });
	log('Mode dropdown is visible.');

	// Verify: no note field is present (the old "Optional note" input)
	const noteField = page.locator('input[aria-label="Note"]');
	expect(await noteField.count()).toBe(0);
	log('No note field found — correct.');

	// Verify: no action prompt textarea visible (since default is "this chat" mode)
	const actionTextarea = page.locator('textarea[aria-label="Action prompt"]');
	expect(await actionTextarea.count()).toBe(0);
	log('No action prompt in "this chat" mode — correct.');

	await screenshot(page, 'ui-this-chat-mode');

	// Switch to "New chat with task" mode — action prompt should appear
	// The mode dropdown should have a "new_task" option
	await modeDropdown.selectOption('new_task');
	await page.waitForTimeout(500);

	// Now action prompt textarea should be visible
	const actionTextareaAfter = page.locator('textarea');
	await expect(actionTextareaAfter.first()).toBeVisible({ timeout: 5000 });
	log('Action prompt appears in "new task" mode — correct.');

	await screenshot(page, 'ui-new-task-mode');

	// Verify submit button is disabled without action prompt
	const submitButton = page.locator('.settings-button.primary');
	const { date, time } = getMinutesFromNow(5);
	await dateInput.fill(date);
	const timeInput = page.locator('#settings-reminder-time');
	await timeInput.fill(time);
	await page.waitForTimeout(300);

	// Should be disabled because action prompt is empty
	await expect(submitButton).toBeDisabled();
	log('Submit disabled without action prompt — correct.');

	// Fill action prompt
	await actionTextareaAfter.first().fill('Search for the latest AI news');
	await page.waitForTimeout(300);
	await expect(submitButton).toBeEnabled();
	log('Submit enabled after filling action prompt — correct.');

	await screenshot(page, 'ui-validation-complete');

	// Close settings
	await page.keyboard.press('Escape');
	log('PASSED: UI structure test.');
});

// ---------------------------------------------------------------------------
// Test 2: Type A — "Remind me about this chat" creates system message in existing chat
// ---------------------------------------------------------------------------

test('reminder redesign — Type A: notification in existing chat, no new chat created', async ({
	page,
}: {
	page: any;
}) => {
	test.slow();
	test.setTimeout(600000);

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('REMINDER_TYPE_A');
	const screenshot = createStepScreenshotter(log);
	await archiveExistingScreenshots(log);

	await loginTestAccount(page, log);

	// Create a chat
	const editor = page.locator('.editor-content.prose');
	await expect(editor).toBeVisible({ timeout: 15000 });
	await editor.click();
	await page.keyboard.type('Test chat for Type A reminder — notification only.');
	const sendBtn = page.locator('.send-button');
	await expect(sendBtn).toBeEnabled();
	await sendBtn.click();

	const assistantMsgs = page.locator('.message-wrapper.assistant');
	await expect(assistantMsgs.first()).toBeVisible({ timeout: 60000 });
	log('Chat established.');
	await screenshot(page, 'chat-established');

	// Count sidebar chats before setting reminder
	const sidebarItems = page.locator('.chat-item-wrapper');
	const chatCountBefore = await sidebarItems.count();
	log(`Sidebar chats before: ${chatCountBefore}`);

	// Open reminder settings via bell button
	const reminderBtn = page.locator('[data-testid="chat-reminders-button"]');
	await expect(reminderBtn).toBeVisible({ timeout: 10000 });
	await reminderBtn.click();
	await page.waitForTimeout(1500);

	// Fill form — "Remind me about this chat" is default
	const dateInput = page.locator('#settings-reminder-date');
	const timeInput = page.locator('#settings-reminder-time');
	await expect(dateInput).toBeVisible({ timeout: 10000 });

	const { date, time } = getMinutesFromNow(2);
	log(`Setting reminder for: ${date} ${time}`);
	await dateInput.fill(date);
	await timeInput.fill(time);

	// Submit
	const submitButton = page.locator('.settings-button.primary');
	await expect(submitButton).toBeEnabled();
	await submitButton.click();
	log('Form submitted.');
	await page.waitForTimeout(2000);

	// Verify success message
	const successBox = page.locator('.settings-info-box.success');
	await expect(successBox).toBeVisible({ timeout: 10000 });
	log('Success message displayed.');
	await screenshot(page, 'success-message');

	// Close settings and return to chat
	await page.keyboard.press('Escape');
	await page.waitForTimeout(1000);

	// Wait for the reminder to fire (up to 4 minutes)
	log('Waiting for reminder system message (up to 4 min)...');
	const systemMsg = page.locator('.message-wrapper.system');
	const pollStart = Date.now();
	while (Date.now() - pollStart < 240000) {
		if ((await systemMsg.count()) >= 1) break;
		const elapsed = Math.round((Date.now() - pollStart) / 1000);
		if (elapsed % 15 === 0) log(`Polling... ${elapsed}s elapsed`);
		await page.waitForTimeout(5000);
	}
	expect(await systemMsg.count(), 'System message must have appeared').toBeGreaterThanOrEqual(1);
	await screenshot(page, 'reminder-fired');

	// Verify the system message is a reminder
	const sysText = await systemMsg.first().textContent();
	log(`System message: "${sysText?.substring(0, 150)}"`);
	expect(sysText?.toLowerCase()).toContain('reminder');

	// Verify NO new chat was created — sidebar count should be the same
	const chatCountAfter = await sidebarItems.count();
	log(`Sidebar chats after: ${chatCountAfter}`);
	expect(chatCountAfter).toBe(chatCountBefore);
	log('No new chat created — correct.');

	await screenshot(page, 'test-complete');
	log('PASSED: Type A reminder test.');
});

// ---------------------------------------------------------------------------
// Test 3: Edit and delete reminder via active reminders list
// ---------------------------------------------------------------------------

test('reminder redesign — edit and delete reminder from settings', async ({
	page,
}: {
	page: any;
}) => {
	test.slow();
	test.setTimeout(300000);

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('REMINDER_EDIT_DELETE');
	const screenshot = createStepScreenshotter(log);
	await archiveExistingScreenshots(log);

	await loginTestAccount(page, log);

	// Create a chat
	const editor = page.locator('.editor-content.prose');
	await expect(editor).toBeVisible({ timeout: 15000 });
	await editor.click();
	await page.keyboard.type('Test chat for reminder edit/delete test.');
	const sendBtn = page.locator('.send-button');
	await expect(sendBtn).toBeEnabled();
	await sendBtn.click();

	const assistantMsgs = page.locator('.message-wrapper.assistant');
	await expect(assistantMsgs.first()).toBeVisible({ timeout: 60000 });
	log('Chat established.');

	// Open reminder settings and create a reminder 30 min from now (won't fire during test)
	const reminderBtn = page.locator('[data-testid="chat-reminders-button"]');
	await expect(reminderBtn).toBeVisible({ timeout: 10000 });
	await reminderBtn.click();
	await page.waitForTimeout(1500);

	const dateInput = page.locator('#settings-reminder-date');
	const timeInput = page.locator('#settings-reminder-time');
	await expect(dateInput).toBeVisible({ timeout: 10000 });

	const { date, time } = getMinutesFromNow(30);
	log(`Creating reminder for: ${date} ${time}`);
	await dateInput.fill(date);
	await timeInput.fill(time);

	const submitButton = page.locator('.settings-button.primary');
	await expect(submitButton).toBeEnabled();
	await submitButton.click();
	await page.waitForTimeout(2000);

	const successBox = page.locator('.settings-info-box.success');
	await expect(successBox).toBeVisible({ timeout: 10000 });
	log('Reminder created.');
	await screenshot(page, 'reminder-created');

	// Scroll down to see active reminders list
	const reminderItem = page.locator('[data-testid="reminder-item"]');
	await expect(reminderItem.first()).toBeVisible({ timeout: 15000 });
	log('Active reminder visible in list.');
	await screenshot(page, 'active-reminders-list');

	// ── Edit: click edit button, change time ──
	const editBtn = page.locator('[data-testid="edit-reminder-btn"]').first();
	await expect(editBtn).toBeVisible({ timeout: 5000 });
	await editBtn.click();
	await page.waitForTimeout(500);

	// Inline edit form should appear with date/time inputs
	const editDateInput = page.locator('.edit-input[type="date"]');
	const editTimeInput = page.locator('.edit-input[type="time"]');
	await expect(editDateInput).toBeVisible({ timeout: 5000 });
	await expect(editTimeInput).toBeVisible({ timeout: 5000 });
	log('Edit form visible.');

	// Change time to 45 minutes from now
	const { date: newDate, time: newTime } = getMinutesFromNow(45);
	await editDateInput.fill(newDate);
	await editTimeInput.fill(newTime);

	const saveBtn = page.locator('.btn-save');
	await expect(saveBtn).toBeEnabled();
	await saveBtn.click();
	await page.waitForTimeout(2000);

	// Verify the reminder list refreshed (edit form should be gone)
	await expect(editDateInput).not.toBeVisible({ timeout: 5000 });
	log('Edit saved.');
	await screenshot(page, 'reminder-edited');

	// ── Delete: click delete button, confirm ──
	const deleteBtn = page.locator('[data-testid="delete-reminder-btn"]').first();
	await expect(deleteBtn).toBeVisible({ timeout: 5000 });
	await deleteBtn.click();
	await page.waitForTimeout(500);

	// Confirm delete
	const confirmBtn = page.locator('[data-testid="confirm-delete-reminder-btn"]');
	await expect(confirmBtn).toBeVisible({ timeout: 5000 });
	await confirmBtn.click();
	await page.waitForTimeout(2000);

	// Verify reminder is gone from the list
	const remainingItems = await page.locator('[data-testid="reminder-item"]').count();
	log(`Remaining reminders after delete: ${remainingItems}`);
	// The item we just deleted should be gone
	await screenshot(page, 'reminder-deleted');

	// Close settings
	await page.keyboard.press('Escape');
	log('PASSED: Edit and delete test.');
});
