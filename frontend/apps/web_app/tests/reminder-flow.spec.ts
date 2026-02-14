/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('@playwright/test');

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
	generateTotp,
	assertNoMissingTranslations
} = require('./signup-flow-helpers');

/**
 * Reminder flow test: login, set a 1-minute reminder, verify delivery and ordering.
 *
 * Test verifies the full reminder lifecycle:
 * 1. User sends a message that requests a reminder in 1 minute
 * 2. AI confirms the reminder is set
 * 3. After ~1 minute, reminder fires — a system message appears
 * 4. AI responds to the reminder
 * 5. System message appears BEFORE the assistant response (correct ordering)
 * 6. Chat is deleted at the end
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL: Email of an existing test account
 * - OPENMATES_TEST_ACCOUNT_PASSWORD: Password for the test account
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY: 2FA OTP secret (base32) for the test account
 * - PLAYWRIGHT_TEST_BASE_URL: Base URL for the deployed web app under test
 */

const TEST_EMAIL = process.env.OPENMATES_TEST_ACCOUNT_EMAIL;
const TEST_PASSWORD = process.env.OPENMATES_TEST_ACCOUNT_PASSWORD;
const TEST_OTP_KEY = process.env.OPENMATES_TEST_ACCOUNT_OTP_KEY;

test('sets a reminder and verifies delivery with correct message ordering', async ({
	page
}: {
	page: any;
}) => {
	// Listen for console logs
	page.on('console', (msg: any) => {
		const timestamp = new Date().toISOString();
		consoleLogs.push(`[${timestamp}] [${msg.type()}] ${msg.text()}`);
	});

	// Listen for network requests
	page.on('request', (request: any) => {
		const timestamp = new Date().toISOString();
		networkActivities.push(`[${timestamp}] >> ${request.method()} ${request.url()}`);
	});

	// Listen for network responses
	page.on('response', (response: any) => {
		const timestamp = new Date().toISOString();
		networkActivities.push(`[${timestamp}] << ${response.status()} ${response.url()}`);
	});

	test.slow();
	// Reminder needs ~60s to fire + time for login + AI responses + buffer
	test.setTimeout(300000); // 5 minutes

	const logCheckpoint = createSignupLogger('REMINDER_FLOW');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint);

	// Pre-test skip checks
	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	await archiveExistingScreenshots(logCheckpoint);

	logCheckpoint('Starting reminder flow test.', { email: TEST_EMAIL });

	// ============================================================
	// STEP 1: Login
	// ============================================================
	await page.goto('/');
	await takeStepScreenshot(page, 'home');

	// Open login dialog
	const headerLoginButton = page.getByRole('button', {
		name: /login.*sign up|sign up/i
	});
	await expect(headerLoginButton).toBeVisible();
	await headerLoginButton.click();
	await takeStepScreenshot(page, 'login-dialog');

	// Enter email
	const emailInput = page.locator('input[name="username"][type="email"]');
	await expect(emailInput).toBeVisible();
	await emailInput.fill(TEST_EMAIL);
	await page.getByRole('button', { name: /continue/i }).click();
	logCheckpoint('Entered email and clicked continue.');

	// Enter password
	const passwordInput = page.locator('input[type="password"]');
	await expect(passwordInput).toBeVisible();
	await passwordInput.fill(TEST_PASSWORD);
	await takeStepScreenshot(page, 'password-entered');

	// Handle 2FA OTP
	const otpCode = generateTotp(TEST_OTP_KEY);
	const otpInput = page.locator('input[autocomplete="one-time-code"]');
	await expect(otpInput).toBeVisible();
	await otpInput.fill(otpCode);
	logCheckpoint('Generated and entered OTP.');
	await takeStepScreenshot(page, 'otp-entered');

	// Submit login
	const submitLoginButton = page.locator('button[type="submit"]', { hasText: /log in|login/i });
	await expect(submitLoginButton).toBeVisible();
	await submitLoginButton.click();
	logCheckpoint('Submitted login form.');

	// Wait for redirect to chat
	await page.waitForURL(/chat/);

	// Wait for initial chat to load
	logCheckpoint('Waiting 5 seconds for initial chat to load...');
	await page.waitForTimeout(5000);

	// ============================================================
	// STEP 2: Start a new chat
	// ============================================================
	const newChatButton = page.locator('.icon_create');
	if (await newChatButton.isVisible()) {
		logCheckpoint('New Chat button visible, clicking it to start a fresh chat.');
		await newChatButton.click();
		await page.waitForTimeout(2000);
	}
	await takeStepScreenshot(page, 'new-chat-ready');

	// ============================================================
	// STEP 3: Send a message requesting a 1-minute reminder
	// ============================================================
	const messageEditor = page.locator('.editor-content.prose');
	await expect(messageEditor).toBeVisible();
	await messageEditor.click();

	// Request a reminder in 1 minute. Be explicit about setting it in this chat
	// to avoid the AI asking clarifying questions about target chat preference.
	const reminderMessage =
		'Set a reminder in this chat for 1 minute from now to check the test results. Just set it, no need to ask questions.';
	await page.keyboard.type(reminderMessage);
	await takeStepScreenshot(page, 'reminder-message-typed');

	const sendButton = page.locator('.send-button');
	await expect(sendButton).toBeEnabled();
	await sendButton.click();
	logCheckpoint(`Sent message: "${reminderMessage}"`);
	await takeStepScreenshot(page, 'reminder-message-sent');

	// Wait for chat ID to appear in URL
	logCheckpoint('Waiting for Chat ID to appear in URL...');
	await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 15000 });
	const urlAfterSend = page.url();
	const chatIdMatch = urlAfterSend.match(/chat-id=([a-zA-Z0-9-]+)/);
	const chatId = chatIdMatch ? chatIdMatch[1] : 'unknown';
	logCheckpoint(`Chat ID detected: ${chatId}`, { chatId });

	// ============================================================
	// STEP 4: Wait for AI response confirming the reminder was set
	// ============================================================
	logCheckpoint('Waiting for AI response confirming reminder was set...');
	const assistantMessages = page.locator('.message-wrapper.assistant');

	// The AI should respond acknowledging the reminder. Wait for the first assistant message.
	await expect(assistantMessages.first()).toBeVisible({ timeout: 60000 });
	await takeStepScreenshot(page, 'initial-ai-response');

	// Record the time when the reminder was confirmed — the reminder should fire ~60s from when it was set
	const reminderSetTime = Date.now();
	logCheckpoint('AI responded. Now waiting for reminder to fire...', {
		reminderSetTime: new Date(reminderSetTime).toISOString()
	});

	// ============================================================
	// STEP 5: Wait for the reminder to fire (~60-90 seconds)
	// ============================================================
	// The reminder fires via a Celery beat task that runs every 60s,
	// so we need to wait for:
	// - The 1-minute timer to expire
	// - The next Celery beat cycle to pick it up (up to 60s)
	// - WebSocket delivery + AI response time
	// Total worst case: ~150s. We poll every 5s for up to 180s.

	const REMINDER_TIMEOUT_MS = 180000; // 3 minutes max wait
	const POLL_INTERVAL_MS = 5000;
	const startWaitTime = Date.now();

	logCheckpoint('Starting to poll for reminder system message...');

	// We look for a system message containing "Reminder" (the template starts with "🔔 **Reminder**")
	const systemMessage = page.locator('.message-wrapper.system');

	let reminderDelivered = false;
	while (Date.now() - startWaitTime < REMINDER_TIMEOUT_MS) {
		const systemMessageCount = await systemMessage.count();
		if (systemMessageCount > 0) {
			reminderDelivered = true;
			const elapsedMs = Date.now() - startWaitTime;
			logCheckpoint(`Reminder system message appeared after ${Math.round(elapsedMs / 1000)}s`);
			break;
		}

		const elapsedSoFar = Math.round((Date.now() - startWaitTime) / 1000);
		if (elapsedSoFar % 15 === 0) {
			logCheckpoint(`Still waiting for reminder... (${elapsedSoFar}s elapsed)`);
		}
		await page.waitForTimeout(POLL_INTERVAL_MS);
	}

	await takeStepScreenshot(page, 'after-reminder-wait');

	// Assert that the reminder system message appeared
	expect(reminderDelivered, 'Reminder system message should have appeared within 3 minutes').toBe(
		true
	);

	// Verify the system message contains expected reminder content
	const systemMessageText = await systemMessage.first().textContent();
	logCheckpoint(`System message content: "${systemMessageText?.substring(0, 200)}"`);

	// The system message should contain the reminder text
	expect(systemMessageText).toContain('Reminder');
	// Case-insensitive check — AI may capitalize the prompt when storing it
	expect(systemMessageText?.toLowerCase()).toContain('check the test results');
	logCheckpoint('Verified system message contains reminder content.');

	// ============================================================
	// STEP 6: Wait for AI response to the reminder
	// ============================================================
	logCheckpoint('Waiting for AI response to reminder...');

	// After the system message, there should be a second assistant message (the AI's response to the reminder)
	// The first assistant message was from step 4 (confirmation). The second is the reminder follow-up.
	// Wait for the count of assistant messages to be at least 2
	await expect(async () => {
		const count = await assistantMessages.count();
		expect(count).toBeGreaterThanOrEqual(2);
	}).toPass({ timeout: 90000, intervals: [3000] });

	await takeStepScreenshot(page, 'reminder-ai-response');
	logCheckpoint('AI response to reminder received.');

	// ============================================================
	// STEP 7: Verify message ordering (system message before AI response)
	// ============================================================
	logCheckpoint('Verifying message ordering...');

	// Get all messages in the chat area in DOM order
	const allMessages = page.locator('.message-wrapper');
	const messageCount = await allMessages.count();
	logCheckpoint(`Total messages in chat: ${messageCount}`);

	// Find the indices of the last system message and the last assistant message
	let lastSystemIndex = -1;
	let lastAssistantIndex = -1;

	for (let i = 0; i < messageCount; i++) {
		const classList = await allMessages.nth(i).getAttribute('class');
		if (classList?.includes('system')) {
			lastSystemIndex = i;
		}
		if (classList?.includes('assistant')) {
			lastAssistantIndex = i;
		}
	}

	logCheckpoint(
		`Message indices - last system: ${lastSystemIndex}, last assistant: ${lastAssistantIndex}`
	);

	// The system message (reminder) should appear before the last assistant message (AI's response to reminder)
	expect(lastSystemIndex, 'System message should exist').toBeGreaterThan(-1);
	expect(lastAssistantIndex, 'Assistant message should exist').toBeGreaterThan(-1);
	expect(
		lastSystemIndex,
		'System message (reminder) should appear before the AI response to it'
	).toBeLessThan(lastAssistantIndex);

	logCheckpoint('Message ordering verified: system message appears before AI response.');
	await takeStepScreenshot(page, 'ordering-verified');

	// Verify no missing translations on the chat page with reminder messages
	await assertNoMissingTranslations(page);
	logCheckpoint('No missing translations detected.');

	// ============================================================
	// STEP 8: Delete the chat
	// ============================================================
	logCheckpoint('Attempting to delete the chat...');

	// Ensure sidebar is open (if on mobile/narrow screen)
	const sidebarToggle = page.locator('.sidebar-toggle-button');
	if (await sidebarToggle.isVisible()) {
		await sidebarToggle.click();
		await page.waitForTimeout(500);
	}

	// Find the active chat in the sidebar
	const activeChatItem = page.locator('.chat-item-wrapper.active');
	await expect(activeChatItem).toBeVisible();

	// Right-click to open context menu
	await activeChatItem.click({ button: 'right' });
	await takeStepScreenshot(page, 'context-menu-open');
	logCheckpoint('Opened chat context menu.');

	// Click delete button (first time to enter confirm mode)
	const deleteButton = page.locator('.menu-item.delete');
	await expect(deleteButton).toBeVisible();
	await deleteButton.click();
	await takeStepScreenshot(page, 'delete-confirm-mode');
	logCheckpoint('Clicked delete, now in confirm mode.');

	// Click delete button again to confirm
	await deleteButton.click();
	logCheckpoint('Confirmed chat deletion.');

	// Verify chat is removed (should redirect to home or another chat)
	await expect(activeChatItem).not.toBeVisible({ timeout: 10000 });
	await takeStepScreenshot(page, 'chat-deleted');
	logCheckpoint('Verified chat deletion. Reminder flow test completed successfully.');
});
