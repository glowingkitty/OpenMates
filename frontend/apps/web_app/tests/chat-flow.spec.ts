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
		consoleLogs.slice(-20).forEach(log => console.log(log));
		
		console.log('\n[RECENT NETWORK ACTIVITIES]');
		networkActivities.slice(-20).forEach(activity => console.log(activity));
		console.log('\n--- END DEBUG INFO ---\n');
	}
});

const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	generateTotp
} = require('./signup-flow-helpers');

/**
 * Chat flow test: login with existing account + 2FA, then send a message.
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL: Email of an existing test account.
 * - OPENMATES_TEST_ACCOUNT_PASSWORD: Password for the test account.
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY: 2FA OTP secret (base32) for the test account.
 * - PLAYWRIGHT_TEST_BASE_URL: Base URL for the deployed web app under test.
 */

const TEST_EMAIL = process.env.OPENMATES_TEST_ACCOUNT_EMAIL;
const TEST_PASSWORD = process.env.OPENMATES_TEST_ACCOUNT_PASSWORD;
const TEST_OTP_KEY = process.env.OPENMATES_TEST_ACCOUNT_OTP_KEY;

test('logs in and sends a chat message', async ({ page }: { page: any }) => {
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
	// Basic login + message shouldn't take long, but we allow time for AI response.
	test.setTimeout(120000);

	const logChatCheckpoint = createSignupLogger('CHAT_FLOW');
	const takeStepScreenshot = createStepScreenshotter(logChatCheckpoint);

	// Pre-test skip checks
	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	await archiveExistingScreenshots(logChatCheckpoint);

	logChatCheckpoint('Starting chat flow test.', { email: TEST_EMAIL });

	// 1. Navigate to home
	await page.goto('/');
	await takeStepScreenshot(page, 'home');

	// 2. Open login dialog
	const headerLoginButton = page.getByRole('button', {
		name: /login.*sign up|sign up/i
	});
	await expect(headerLoginButton).toBeVisible();
	await headerLoginButton.click();
	await takeStepScreenshot(page, 'login-dialog');

	// 3. Enter email
	const emailInput = page.locator('input[name="username"][type="email"]');
	await expect(emailInput).toBeVisible();
	await emailInput.fill(TEST_EMAIL);
	await page.getByRole('button', { name: /continue/i }).click();
	logChatCheckpoint('Entered email and clicked continue.');

	// 4. Enter password
	const passwordInput = page.locator('input[type="password"]');
	await expect(passwordInput).toBeVisible();
	await passwordInput.fill(TEST_PASSWORD);
	await takeStepScreenshot(page, 'password-entered');

	// 5. Handle 2FA OTP
	const otpCode = generateTotp(TEST_OTP_KEY);
	const otpInput = page.locator('input[autocomplete="one-time-code"]');
	await expect(otpInput).toBeVisible();
	await otpInput.fill(otpCode);
	logChatCheckpoint('Generated and entered OTP.');
	await takeStepScreenshot(page, 'otp-entered');

	// 6. Submit login
	const submitLoginButton = page.locator('button[type="submit"]', { hasText: /log in|login/i });
	await expect(submitLoginButton).toBeVisible();
	await submitLoginButton.click();
	logChatCheckpoint('Submitted login form.');

	// 7. Wait for redirect to chat
	await page.waitForURL(/chat/);
	
	// Wait 5 seconds to ensure any demo/welcome chat is loaded
	logChatCheckpoint('Waiting 5 seconds for initial chat to load...');
	await page.waitForTimeout(5000);

	// Check if "New Chat" button is visible and click it to ensure we're in a fresh chat
	const newChatButton = page.locator('.icon_create');
	if (await newChatButton.isVisible()) {
		logChatCheckpoint('New Chat button visible, clicking it to start a fresh chat.');
		await newChatButton.click();
		await page.waitForTimeout(2000); // Wait for new chat to initialize
	}

	// 8. Send message "Capital of Germany?"
	const messageEditor = page.locator('.editor-content.prose');
	await expect(messageEditor).toBeVisible();
	await messageEditor.click();
	// Use keyboard.type instead of fill for TipTap editor
	await page.keyboard.type('Capital of Germany?');
	await takeStepScreenshot(page, 'message-filled');

	const sendButton = page.locator('.send-button');
	await expect(sendButton).toBeEnabled();
	await sendButton.click();
	logChatCheckpoint('Sent message: "Capital of Germany?"');
	await takeStepScreenshot(page, 'message-sent');

	// The chat ID is generated and added to URL after the first message is sent
	logChatCheckpoint('Waiting for Chat ID to appear in URL...');
	await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 15000 });
	const urlAfterSend = page.url();
	const chatIdMatch = urlAfterSend.match(/chat-id=([a-zA-Z0-9-]+)/);
	const chatId = chatIdMatch ? chatIdMatch[1] : 'unknown';
	logChatCheckpoint(`Chat ID detected: ${chatId}`, { chatId });

	// 9. Wait for response containing "Berlin"
	logChatCheckpoint('Waiting for assistant response...');
	const assistantResponse = page.locator('.message-wrapper.assistant');
	// Increased timeout for AI response
	await expect(assistantResponse.last()).toContainText('Berlin', { timeout: 45000 });
	
	await takeStepScreenshot(page, 'response-received');
	logChatCheckpoint('Confirmed "Berlin" in assistant response.');

	// 10. Delete the chat via context menu
	logChatCheckpoint('Attempting to delete the chat...');
	
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
	logChatCheckpoint('Opened chat context menu.');

	// Click delete button (first time to enter confirm mode)
	const deleteButton = page.locator('.menu-item.delete');
	await expect(deleteButton).toBeVisible();
	await deleteButton.click();
	await takeStepScreenshot(page, 'delete-confirm-mode');
	logChatCheckpoint('Clicked delete, now in confirm mode.');

	// Click delete button again to confirm
	await deleteButton.click();
	logChatCheckpoint('Confirmed chat deletion.');

	// Verify chat is removed (should redirect to home or another chat)
	await expect(activeChatItem).not.toBeVisible({ timeout: 10000 });
	await takeStepScreenshot(page, 'chat-deleted');
	logChatCheckpoint('Verified chat deletion successfully.');
});
