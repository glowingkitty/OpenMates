/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('@playwright/test');
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
	await takeStepScreenshot(page, 'chat-loaded');
	logChatCheckpoint('Arrived at chat page.');

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
