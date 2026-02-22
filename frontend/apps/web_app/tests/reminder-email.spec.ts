/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Reminder E2E — Scenario: Email notification
 *
 * Enables email notifications in Settings → Chat → Notifications, sets a
 * 1-minute reminder, then closes the browser context (simulating the user
 * leaving). Polls Mailosaur for a reminder email for up to 3 minutes.
 * Re-opens to clean up the chat.
 *
 * Runtime: ~5 minutes.
 *
 * REQUIRED ENV VARS:
 *   OPENMATES_TEST_ACCOUNT_EMAIL    — must be a Mailosaur address
 *   OPENMATES_TEST_ACCOUNT_PASSWORD
 *   OPENMATES_TEST_ACCOUNT_OTP_KEY
 *   MAILOSAUR_API_KEY
 */

const { test, expect } = require('@playwright/test');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	generateTotp,
	createMailosaurClient,
	getMailosaurServerId
} = require('./signup-flow-helpers');

const TEST_EMAIL = process.env.OPENMATES_TEST_ACCOUNT_EMAIL;
const TEST_PASSWORD = process.env.OPENMATES_TEST_ACCOUNT_PASSWORD;
const TEST_OTP_KEY = process.env.OPENMATES_TEST_ACCOUNT_OTP_KEY;
const MAILOSAUR_API_KEY = process.env.MAILOSAUR_API_KEY;
const MAILOSAUR_SERVER_ID_ENV = process.env.MAILOSAUR_SERVER_ID;

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

async function enableEmailNotifications(page: any, log: any, screenshot: any): Promise<void> {
	const profileContainer = page.locator('.profile-container');
	await expect(profileContainer).toBeVisible({ timeout: 10000 });
	await profileContainer.click();

	const settingsMenu = page.locator('.settings-menu.visible');
	await expect(settingsMenu).toBeVisible({ timeout: 10000 });
	await screenshot(page, 'settings-menu');

	const chatItem = settingsMenu.getByRole('menuitem', { name: /^chat$/i }).first();
	await expect(chatItem).toBeVisible({ timeout: 10000 });
	await chatItem.click();
	await page.waitForTimeout(800);

	const notificationsItem = settingsMenu.getByRole('menuitem', { name: /notifications/i }).first();
	await expect(notificationsItem).toBeVisible({ timeout: 10000 });
	await notificationsItem.click();
	await page.waitForTimeout(800);
	await screenshot(page, 'notifications-settings');

	const emailSection = page.locator('.email-section');
	await expect(emailSection).toBeVisible({ timeout: 10000 });

	const toggle = emailSection.locator('.toggle-container').first();
	await expect(toggle).toBeVisible({ timeout: 8000 });

	const checkbox = toggle.locator('input[type="checkbox"]');
	const alreadyOn = await checkbox.isChecked().catch(() => false);
	if (alreadyOn) {
		log('Email notifications already enabled.');
	} else {
		await toggle.click();
		await page.waitForTimeout(2000);
		log('Email notifications enabled.');
	}
	await screenshot(page, 'email-toggle-enabled');

	// Close settings
	await page.keyboard.press('Escape');
	await page.waitForTimeout(500);
	if (
		await page
			.locator('.settings-menu.visible')
			.isVisible({ timeout: 500 })
			.catch(() => false)
	) {
		await page.mouse.click(10, 10);
		await page.waitForTimeout(500);
	}
	log('Settings closed.');
}

// ---------------------------------------------------------------------------
// Test
// ---------------------------------------------------------------------------

test('reminder — email: reminder email arrives after browser is closed', async ({
	page,
	context,
	browser
}: {
	page: any;
	context: any;
	browser: any;
}) => {
	test.slow();
	test.setTimeout(600000); // 10 min

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');
	test.skip(!MAILOSAUR_API_KEY, 'MAILOSAUR_API_KEY is required.');

	const mailosaurServerId = getMailosaurServerId(TEST_EMAIL ?? '', MAILOSAUR_SERVER_ID_ENV);
	if (!mailosaurServerId) {
		throw new Error(
			'Cannot derive Mailosaur server ID. Set MAILOSAUR_SERVER_ID or use a Mailosaur email for OPENMATES_TEST_ACCOUNT_EMAIL.'
		);
	}

	const log = createSignupLogger('REMINDER_EMAIL');
	const screenshot = createStepScreenshotter(log);
	await archiveExistingScreenshots(log);

	const { waitForMailosaurMessage } = createMailosaurClient({
		apiKey: MAILOSAUR_API_KEY,
		serverId: mailosaurServerId
	});

	await loginTestAccount(page, log);
	await screenshot(page, 'logged-in');

	// Enable email notifications in settings
	await enableEmailNotifications(page, log, screenshot);
	await page.waitForTimeout(1000);

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
		'Set a reminder in this chat for 1 minute from now with the message "email notification test". Just set it, no need to ask questions.'
	);

	const sendBtn = page.locator('.send-button');
	await expect(sendBtn).toBeEnabled();
	await sendBtn.click();
	log('Reminder request sent.');

	// Wait for AI confirmation
	await expect(page.locator('.message-wrapper.assistant').first()).toBeVisible({ timeout: 60000 });
	log('AI confirmed. Closing browser context now.');
	await screenshot(page, 'before-close');

	// Record timestamp for Mailosaur receivedAfter filter
	const sentAfter = new Date().toISOString();

	// Close the browser context — simulates user leaving
	await context.close();
	log('Browser context closed.');

	// Poll Mailosaur for the reminder email (3-min window)
	log('Polling Mailosaur for reminder email (up to 3 min)...');
	let email: any = null;
	try {
		email = await waitForMailosaurMessage({
			sentTo: TEST_EMAIL,
			subjectContains: 'Reminder',
			receivedAfter: sentAfter,
			timeoutMs: 180000,
			pollIntervalMs: 10000
		});
		log('Reminder email received!', { subject: email?.subject });
	} catch (err: any) {
		throw new Error(
			`No reminder email received within 3 minutes. ` +
				`Checked for emails to "${TEST_EMAIL}" with subject "Reminder" ` +
				`sent after ${sentAfter}. Error: ${err?.message}`
		);
	}

	expect(email?.subject, 'Email subject must contain Reminder').toMatch(/reminder/i);
	log('Email notification verified.');

	// Re-open browser for cleanup
	log('Re-opening browser for cleanup...');
	const cleanupCtx = await browser.newContext();
	const cleanupPage = await cleanupCtx.newPage();

	await loginTestAccount(cleanupPage, log);

	const activeChat = cleanupPage.locator('.chat-item-wrapper.active');
	if (await activeChat.isVisible({ timeout: 5000 }).catch(() => false)) {
		await deleteActiveChat(cleanupPage, log);
		log('Cleanup chat deleted.');
	} else {
		log('No active chat found for cleanup.');
	}

	await cleanupCtx.close();
	log('PASSED.');
});
