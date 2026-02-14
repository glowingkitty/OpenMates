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
		consoleLogs.slice(-20).forEach((log) => console.log(log));

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
 * Background Chat Notification Test
 *
 * Tests the notification popup when a background chat receives an AI response:
 * 1. Login with existing test account
 * 2. Send a message in Chat A
 * 3. Immediately switch to a new Chat B (making Chat A background)
 * 4. Wait for the notification popup from Chat A's AI response
 * 5. Verify notification content (message preview, avatar)
 * 6. Hover to interrupt auto-dismiss
 * 7. Use reply button, type a reply, send it
 * 8. Verify navigation to Chat A
 * 9. Delete Chat A
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 * - PLAYWRIGHT_TEST_BASE_URL
 */

const TEST_EMAIL = process.env.OPENMATES_TEST_ACCOUNT_EMAIL;
const TEST_PASSWORD = process.env.OPENMATES_TEST_ACCOUNT_PASSWORD;
const TEST_OTP_KEY = process.env.OPENMATES_TEST_ACCOUNT_OTP_KEY;

test('background chat notification shows and allows reply', async ({ page }: { page: any }) => {
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
	test.setTimeout(180000); // 3 minutes — background processing takes time

	const logStep = createSignupLogger('BG_NOTIFICATION');
	const takeScreenshot = createStepScreenshotter(logStep);

	// Pre-test skip checks
	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	await archiveExistingScreenshots(logStep);
	logStep('Starting background chat notification test.', { email: TEST_EMAIL });

	// ══════════════════════════════════════════════════════════════
	// 1. Navigate to home
	// ══════════════════════════════════════════════════════════════
	await page.goto('/');
	await takeScreenshot(page, 'home');

	// 2. Open login dialog
	const headerLoginButton = page.getByRole('button', {
		name: /login.*sign up|sign up/i
	});
	await expect(headerLoginButton).toBeVisible();
	await headerLoginButton.click();
	await takeScreenshot(page, 'login-dialog');

	// 3. Enter email
	const emailInput = page.locator('input[name="username"][type="email"]');
	await expect(emailInput).toBeVisible();
	await emailInput.fill(TEST_EMAIL);
	await page.getByRole('button', { name: /continue/i }).click();
	logStep('Entered email and clicked continue.');

	// 4. Enter password
	const passwordInput = page.locator('input[type="password"]');
	await expect(passwordInput).toBeVisible();
	await passwordInput.fill(TEST_PASSWORD);
	await takeScreenshot(page, 'password-entered');

	// 5. Handle 2FA OTP — generate fresh code right before submission to avoid TOTP window expiry.
	// Retry up to 3 times if the code is rejected (window boundary race condition).
	const otpInput = page.locator('input[autocomplete="one-time-code"]');
	await expect(otpInput).toBeVisible();
	const submitLoginButton = page.locator('button[type="submit"]', { hasText: /log in|login/i });
	await expect(submitLoginButton).toBeVisible();

	let loginSuccess = false;
	for (let attempt = 0; attempt < 3; attempt++) {
		const otpCode = generateTotp(TEST_OTP_KEY);
		await otpInput.fill(otpCode);
		logStep(`OTP attempt ${attempt + 1}: entered code ${otpCode}`);
		await submitLoginButton.click();

		try {
			await page.waitForURL(/chat/, { timeout: 10000 });
			loginSuccess = true;
			logStep('Login succeeded.');
			break;
		} catch {
			logStep(`OTP attempt ${attempt + 1} failed, retrying...`);
			await takeScreenshot(page, `otp-retry-${attempt + 1}`);
			// Wait a moment before retrying — if we're at a TOTP boundary, the next
			// 30-second window should give us a valid code
			await page.waitForTimeout(2000);
		}
	}

	if (!loginSuccess) {
		throw new Error('Login failed after 3 OTP attempts');
	}

	// Wait for initial chat load
	logStep('Waiting for initial chat to load...');
	await page.waitForTimeout(5000);
	await takeScreenshot(page, 'after-login');

	// 8. Start a fresh chat
	const newChatButton = page.locator('.icon_create');
	if (await newChatButton.isVisible()) {
		logStep('New Chat button visible, clicking it to start a fresh chat.');
		await newChatButton.click();
		await page.waitForTimeout(2000);
	}

	// ══════════════════════════════════════════════════════════════
	// 9. Send a message in Chat A
	// ══════════════════════════════════════════════════════════════
	const messageEditor = page.locator('.editor-content.prose');
	await expect(messageEditor).toBeVisible();
	await messageEditor.click();
	await page.keyboard.type('What is the tallest mountain in the world?');
	await takeScreenshot(page, 'chat-a-message-typed');

	const sendButton = page.locator('.send-button');
	await expect(sendButton).toBeEnabled();
	await sendButton.click();
	logStep('Sent message in Chat A.');
	await takeScreenshot(page, 'chat-a-message-sent');

	// Wait for Chat A URL to contain a chat-id
	logStep('Waiting for Chat A ID in URL...');
	await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 15000 });
	const chatAUrl = page.url();
	const chatAIdMatch = chatAUrl.match(/chat-id=([a-zA-Z0-9-]+)/);
	const chatAId = chatAIdMatch ? chatAIdMatch[1] : 'unknown';
	logStep(`Chat A created with ID: ${chatAId}`);

	// ══════════════════════════════════════════════════════════════
	// 10. Switch to a new Chat B (making Chat A a background chat)
	// ══════════════════════════════════════════════════════════════
	await page.waitForTimeout(1500); // Let processing start
	const newChatButton2 = page.locator('.icon_create');
	await expect(newChatButton2).toBeVisible();
	await newChatButton2.click();
	logStep('Switched to Chat B — Chat A is now in background.');
	await takeScreenshot(page, 'switched-to-chat-b');
	await page.waitForTimeout(1000);

	// ══════════════════════════════════════════════════════════════
	// 11. (Soft check) Typing indicator shimmer in sidebar
	// ══════════════════════════════════════════════════════════════
	logStep('Checking for typing shimmer in sidebar...');
	const typingShimmer = page.locator('.status-message.typing-shimmer');
	try {
		await expect(typingShimmer).toBeVisible({ timeout: 10000 });
		logStep('Typing shimmer visible.');
		await takeScreenshot(page, 'typing-shimmer');
	} catch {
		logStep('Typing shimmer not caught (may have already completed).');
		await takeScreenshot(page, 'typing-shimmer-missed');
	}

	// ══════════════════════════════════════════════════════════════
	// 12. Wait for the background chat notification popup
	// ══════════════════════════════════════════════════════════════
	logStep('Waiting for background chat notification...');
	const notification = page.locator('.notification.notification-chat-message');
	await expect(notification).toBeVisible({ timeout: 60000 });
	logStep('Notification appeared!');
	await takeScreenshot(page, 'notification-appeared');

	// 13. Verify notification content
	const messagePreview = notification.locator('.notification-message-primary');
	await expect(messagePreview).toBeVisible();
	const previewText = await messagePreview.textContent();
	logStep(`Notification preview: "${previewText}"`);
	expect(previewText).toBeTruthy();
	expect(previewText!.trim().length).toBeGreaterThan(0);

	// Check for mate profile or avatar placeholder
	const mateProfile = notification.locator('.mate-profile');
	const avatarPlaceholder = notification.locator('.avatar-placeholder');
	const hasProfile = await mateProfile.isVisible().catch(() => false);
	const hasPlaceholder = await avatarPlaceholder.isVisible().catch(() => false);
	logStep(`Avatar: mateProfile=${hasProfile}, placeholder=${hasPlaceholder}`);
	expect(hasProfile || hasPlaceholder).toBeTruthy();

	// ══════════════════════════════════════════════════════════════
	// 14. Hover to interrupt auto-dismiss
	// ══════════════════════════════════════════════════════════════
	await notification.hover();
	logStep('Hovered notification to interrupt auto-dismiss.');
	await page.waitForTimeout(3000);
	await expect(notification).toBeVisible();
	logStep('Notification still visible after 3s hover.');

	// ══════════════════════════════════════════════════════════════
	// 15. Reply via notification
	// ══════════════════════════════════════════════════════════════
	const replyButton = notification.locator('.notification-reply-button');
	await expect(replyButton).toBeVisible();
	await replyButton.click();
	logStep('Clicked reply button.');
	await takeScreenshot(page, 'reply-expanded');

	// TipTap creates a .ProseMirror contenteditable div inside .notification-reply-input.
	// The class .notification-reply-editor is applied to it via editorProps.attributes.
	// Wait for TipTap to initialize after the reply section expands.
	await page.waitForTimeout(500);
	const replyEditor = page.locator(
		'.notification-reply-input .ProseMirror[contenteditable="true"]'
	);
	await expect(replyEditor).toBeVisible({ timeout: 5000 });
	await replyEditor.click();
	await page.keyboard.type('Thanks for the info!');
	logStep('Typed reply.');
	await takeScreenshot(page, 'reply-typed');

	const sendReplyBtn = notification.locator('.notification-send-btn');
	await expect(sendReplyBtn).toBeEnabled();
	await sendReplyBtn.click();
	logStep('Sent reply.');

	// ══════════════════════════════════════════════════════════════
	// 16. Verify navigation to Chat A
	// ══════════════════════════════════════════════════════════════
	await page.waitForURL(new RegExp(`chat-id=${chatAId}`), { timeout: 10000 });
	logStep('Navigated to Chat A via notification reply.');
	await takeScreenshot(page, 'navigated-to-chat-a');
	await page.waitForTimeout(2000);

	const assistantResponse = page.locator('.message-wrapper.assistant');
	await expect(assistantResponse.last()).toBeVisible({ timeout: 10000 });
	logStep('Assistant response visible in Chat A.');

	// Verify no missing translations on the chat page with notification UI
	await assertNoMissingTranslations(page);
	logStep('No missing translations detected.');

	// ══════════════════════════════════════════════════════════════
	// 17. Delete Chat A via context menu
	// ══════════════════════════════════════════════════════════════
	logStep('Deleting Chat A...');

	const sidebarToggle = page.locator('.sidebar-toggle-button');
	if (await sidebarToggle.isVisible()) {
		await sidebarToggle.click();
		await page.waitForTimeout(500);
	}

	const activeChatItem = page.locator('.chat-item-wrapper.active');
	await expect(activeChatItem).toBeVisible();

	// Right-click → delete (click once for confirm mode, click again to confirm)
	await activeChatItem.click({ button: 'right' });
	await takeScreenshot(page, 'context-menu');

	const deleteButton = page.locator('.menu-item.delete');
	await expect(deleteButton).toBeVisible();
	await deleteButton.click();
	await takeScreenshot(page, 'delete-confirm');
	await deleteButton.click();
	logStep('Confirmed Chat A deletion.');

	await expect(activeChatItem).not.toBeVisible({ timeout: 10000 });
	await takeScreenshot(page, 'chat-deleted');
	logStep('Chat A deleted. Test complete.');
});
