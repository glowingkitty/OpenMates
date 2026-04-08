/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Reminder Redesign E2E — Tests for the simplified reminder creation flow.
 *
 * Tests the redesigned reminder feature:
 * 1. UI structure: SettingsPageHeader, Reminder type dropdown (always both options),
 *    explainer text, conditional Task textarea, Day/Time/Repeat fields, SettingsButton
 * 2. "Chat reminder" (Type A): notification-only, no new chat
 *
 * Bug history this test suite guards against:
 * - f8b6e6b12: Redesigned reminder feature — single toggle, remove note field
 * - 7b6a98a: Redesigned settings UI to match Figma (OPE-30)
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
	getE2EDebugUrl,
} = require('./signup-flow-helpers');

const { loginToTestAccount } = require('./helpers/chat-test-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function loginTestAccount(page: any, log: any): Promise<void> {
	await loginToTestAccount(page, log);
	log('Login successful.');
}

function getMinutesFromNow(minutes: number): { date: string; time: string } {
	const now = new Date();
	now.setMinutes(now.getMinutes() + minutes);
	const date = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
	const time = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
	return { date, time };
}

// ---------------------------------------------------------------------------
// Test 1: UI structure matches Figma — header, both type options, explainer,
//         conditional task textarea, correct field order
// ---------------------------------------------------------------------------

test('reminder redesign — UI matches Figma: header, type dropdown, explainer, fields', async ({
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
	const editor = page.getByTestId('message-editor');
	await expect(editor).toBeVisible({ timeout: 15000 });
	await editor.click();
	await page.keyboard.type('Hello, testing reminder UI.');
	const sendBtn = page.locator('[data-action="send-message"]');
	await expect(sendBtn).toBeEnabled();
	await sendBtn.click();

	const assistantMsgs = page.getByTestId('message-assistant');
	await expect(assistantMsgs.first()).toBeVisible({ timeout: 60000 });
	log('Chat established.');

	// Open reminder settings via top-bar bell button
	const reminderBtn = page.locator('[data-testid="chat-reminders-button"]');
	await expect(reminderBtn).toBeVisible({ timeout: 10000 });
	await reminderBtn.click();
	await page.waitForTimeout(1500);

	// ── Verify section headings use SettingsSectionHeading ──
	const sectionHeading = page.locator('.settings-section-heading');
	await expect(sectionHeading.first()).toBeVisible({ timeout: 10000 });
	log('SettingsSectionHeading visible.');

	// ── Verify Reminder type dropdown with BOTH options ──
	const modeDropdown = page.getByTestId('settings-dropdown').first();
	await expect(modeDropdown).toBeVisible({ timeout: 5000 });

	// Both options should exist (Chat reminder + Task)
	const options = modeDropdown.locator('option:not([disabled])');
	const optionCount = await options.count();
	expect(optionCount).toBe(2);
	log(`Reminder type dropdown has ${optionCount} options — correct.`);

	// Default should be "this_chat" when opened from a chat
	const selectedValue = await modeDropdown.inputValue();
	expect(selectedValue).toBe('this_chat');
	log('Default mode is "this_chat" — correct.');

	// ── Verify explainer text is visible ──
	const explainer = page.getByTestId('reminder-type-explainer');
	await expect(explainer).toBeVisible({ timeout: 5000 });
	log('Explainer text visible.');

	// ── Verify chat context preview is visible (since we have an active chat) ──
	const chatContext = page.getByTestId('chat-context');
	await expect(chatContext).toBeVisible({ timeout: 5000 });
	log('Chat context preview with gradient circle visible.');

	// ── Verify no task textarea in "this_chat" mode ──
	const taskTextarea = page.locator('textarea');
	expect(await taskTextarea.count()).toBe(0);
	log('No task textarea in "this_chat" mode — correct.');

	// ── Verify date and time inputs exist ──
	const dateInput = page.locator('#settings-reminder-date');
	const timeInput = page.locator('#settings-reminder-time');
	await expect(dateInput).toBeVisible({ timeout: 5000 });
	await expect(timeInput).toBeVisible({ timeout: 5000 });
	log('Date and time inputs visible.');

	// ── Verify no old "note" field ──
	const noteField = page.locator('input[aria-label="Note"]');
	expect(await noteField.count()).toBe(0);
	log('No note field — correct.');

	await screenshot(page, 'ui-chat-reminder-mode');

	// ── Switch to "Task" mode ──
	await modeDropdown.selectOption('new_task');
	await page.waitForTimeout(500);

	// Task textarea should now appear
	const taskTextareaAfter = page.locator('textarea');
	await expect(taskTextareaAfter.first()).toBeVisible({ timeout: 5000 });
	log('Task textarea appears in "new_task" mode — correct.');

	// Chat context preview should disappear (only shown in this_chat mode)
	await expect(chatContext).not.toBeVisible({ timeout: 3000 });
	log('Chat context hidden in task mode — correct.');

	// Explainer text should now show task description
	await expect(explainer).toBeVisible();
	log('Explainer text updated for task mode.');

	await screenshot(page, 'ui-task-mode');

	// ── Verify submit button validation ──
	const submitButton = page.getByTestId('settings-button-primary');
	const { date, time } = getMinutesFromNow(5);
	await dateInput.fill(date);
	await timeInput.fill(time);
	await page.waitForTimeout(300);

	// Should be disabled because task prompt is empty
	await expect(submitButton).toBeDisabled();
	log('Submit disabled without task prompt — correct.');

	// Fill task prompt
	await taskTextareaAfter.first().fill('Search for the latest AI news');
	await page.waitForTimeout(300);
	await expect(submitButton).toBeEnabled();
	log('Submit enabled after filling task prompt — correct.');

	await screenshot(page, 'ui-validation-complete');

	// Close settings
	await page.keyboard.press('Escape');
	log('PASSED: UI structure test.');
});

// ---------------------------------------------------------------------------
// Test 2: Type A — "Chat reminder" creates notification in existing chat
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
	const editor = page.getByTestId('message-editor');
	await expect(editor).toBeVisible({ timeout: 15000 });
	await editor.click();
	await page.keyboard.type('Test chat for Type A reminder — notification only.');
	const sendBtn = page.locator('[data-action="send-message"]');
	await expect(sendBtn).toBeEnabled();
	await sendBtn.click();

	const assistantMsgs = page.getByTestId('message-assistant');
	await expect(assistantMsgs.first()).toBeVisible({ timeout: 60000 });
	log('Chat established.');
	await screenshot(page, 'chat-established');

	// Count sidebar chats before setting reminder
	const sidebarItems = page.getByTestId('chat-item-wrapper');
	const chatCountBefore = await sidebarItems.count();
	log(`Sidebar chats before: ${chatCountBefore}`);

	// Open reminder settings via bell button
	const reminderBtn = page.locator('[data-testid="chat-reminders-button"]');
	await expect(reminderBtn).toBeVisible({ timeout: 10000 });
	await reminderBtn.click();
	await page.waitForTimeout(1500);

	// Fill form — "Chat reminder" is default when opened from a chat
	const dateInput = page.locator('#settings-reminder-date');
	const timeInput = page.locator('#settings-reminder-time');
	await expect(dateInput).toBeVisible({ timeout: 10000 });

	const { date, time } = getMinutesFromNow(2);
	log(`Setting reminder for: ${date} ${time}`);
	await dateInput.fill(date);
	await timeInput.fill(time);

	// Submit
	const submitButton = page.getByTestId('settings-button-primary');
	await expect(submitButton).toBeEnabled();
	await submitButton.click();
	log('Form submitted.');
	await page.waitForTimeout(2000);

	// Verify success message
	const successBox = page.getByTestId('settings-info-box-success');
	await expect(successBox).toBeVisible({ timeout: 10000 });
	log('Success message displayed.');
	await screenshot(page, 'success-message');

	// Close settings and return to chat
	await page.keyboard.press('Escape');
	await page.waitForTimeout(1000);

	// Wait for the reminder to fire (up to 4 minutes)
	log('Waiting for reminder system message (up to 4 min)...');
	const systemMsg = page.getByTestId('message-system');
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
