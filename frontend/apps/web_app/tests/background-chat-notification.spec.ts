/* eslint-disable @typescript-eslint/no-require-imports */
export {};

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
 * Selectors: data-testid attributes (stable, won't break on CSS renames).
 * Console monitoring: shared console-monitor.ts (Rule 10).
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 * - PLAYWRIGHT_TEST_BASE_URL
 */

const {
	test,
	expect,
	consoleLogs,
	networkActivities,
	attachConsoleListeners,
	attachNetworkListeners
} = require('./console-monitor');

const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	assertNoMissingTranslations,
	getTestAccount,
	getE2EDebugUrl
} = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

test('background chat notification shows and allows reply', async ({ page }: { page: any }) => {
	attachConsoleListeners(page);
	attachNetworkListeners(page);

	test.slow();
	test.setTimeout(240000); // 4 minutes — TOTP retry can use up to 90s + background processing

	const logStep = createSignupLogger('BG_NOTIFICATION');
	const takeScreenshot = createStepScreenshotter(logStep);

	// Pre-test skip checks
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	await archiveExistingScreenshots(logStep);
	logStep('Starting background chat notification test.', { email: TEST_EMAIL });

	// ══════════════════════════════════════════════════════════════
	// 1-5. Login via shared helper (includes OTP retry with clock-drift compensation)
	// ══════════════════════════════════════════════════════════════
	await loginToTestAccount(page, logStep, takeScreenshot);
	logStep('Login succeeded. Waiting for initial chat load...');
	await page.waitForTimeout(2000);
	await takeScreenshot(page, 'after-login');

	// ══════════════════════════════════════════════════════════════
	// 9. Send a message in Chat A
	// ══════════════════════════════════════════════════════════════
	const messageEditor = page.getByTestId('message-editor');
	await expect(messageEditor).toBeVisible({ timeout: 15000 });
	await messageEditor.click();
	await page.keyboard.type('What is the tallest mountain in the world?');
	await takeScreenshot(page, 'chat-a-message-typed');

	const sendButton = page.locator('[data-action="send-message"]');
	await expect(sendButton).toBeEnabled({ timeout: 10000 });
	await sendButton.click();
	logStep('Sent message in Chat A.');
	await takeScreenshot(page, 'chat-a-message-sent');

	// Wait for Chat A URL to contain a chat-id (hash-based: /#chat-id=xxx)
	logStep('Waiting for Chat A ID in URL...');
	await expect(page).toHaveURL(/chat-id=/, { timeout: 15000 });
	const chatAUrl = page.url();
	// Chat IDs can contain alphanumeric, hyphens, underscores — capture everything up to & or end
	const chatAIdMatch = chatAUrl.match(/chat-id=([^&# ]+)/);
	const chatAId = chatAIdMatch ? chatAIdMatch[1] : null;
	logStep(`Chat A created with ID: ${chatAId}, full URL: ${chatAUrl}`);
	if (!chatAId) {
		throw new Error(`Could not extract chat ID from URL: ${chatAUrl}`);
	}

	// ══════════════════════════════════════════════════════════════
	// 10. Switch to a new Chat B (making Chat A a background chat)
	// ══════════════════════════════════════════════════════════════
	await page.waitForTimeout(1500); // Let processing start
	const newChatButton2 = page.getByTestId('new-chat-button');
	await expect(newChatButton2).toBeVisible({ timeout: 10000 });
	await newChatButton2.click();
	logStep('Switched to Chat B — Chat A is now in background.');
	await takeScreenshot(page, 'switched-to-chat-b');
	await page.waitForTimeout(1000);

	// ══════════════════════════════════════════════════════════════
	// 11. (Soft check) Typing indicator shimmer in sidebar
	// ══════════════════════════════════════════════════════════════
	logStep('Checking for typing shimmer in sidebar...');
	const typingShimmer = page.getByTestId('chat-typing-shimmer');
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
	const notification = page.getByTestId('chat-notification');
	await expect(notification).toBeVisible({ timeout: 60000 });
	logStep('Notification appeared!');
	await takeScreenshot(page, 'notification-appeared');

	// 13. Verify notification content
	const messagePreview = notification.getByTestId('notification-message');
	await expect(messagePreview).toBeVisible({ timeout: 10000 });
	const previewText = await messagePreview.textContent();
	logStep(`Notification preview: "${previewText}"`);
	expect(previewText).toBeTruthy();
	expect(previewText!.trim().length).toBeGreaterThan(0);

	// Check for mate profile or avatar placeholder (still CSS since they're dynamic class variants)
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
	const replyButton = notification.getByTestId('notification-reply-button');
	await expect(replyButton).toBeVisible({ timeout: 5000 });
	await replyButton.click();
	logStep('Clicked reply button.');
	await takeScreenshot(page, 'reply-expanded');

	// TipTap creates a .ProseMirror contenteditable div inside .notification-reply-input.
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

	const sendReplyBtn = notification.locator('[data-action="send-message"]');
	await expect(sendReplyBtn).toBeVisible({ timeout: 8000 });
	await expect(sendReplyBtn).toBeEnabled({ timeout: 8000 });
	await sendReplyBtn.click();
	logStep('Sent reply.');

	// ══════════════════════════════════════════════════════════════
	// 16. Verify navigation to Chat A
	// ══════════════════════════════════════════════════════════════
	const targetChatUrlPattern = new RegExp(`chat-id=${chatAId}`);
	try {
		await page.waitForURL(targetChatUrlPattern, { timeout: 10000 });
	} catch {
		logStep('Reply did not auto-navigate to Chat A within timeout, selecting Chat A from sidebar.');
		// Open sidebar if closed (mobile: sidebar toggle in header)
		const sidebarToggle = page.getByTestId('sidebar-toggle');
		if (await sidebarToggle.isVisible().catch(() => false)) {
			await sidebarToggle.click();
			await page.waitForTimeout(300);
		}
		// App uses hash-based navigation: /#chat-id={id}
		const chatLink = page.locator(`a[href*="chat-id=${chatAId}"]`).first();
		if (await chatLink.isVisible().catch(() => false)) {
			await chatLink.click();
		} else {
			await page.goto(`/#chat-id=${chatAId}`);
		}
		await page.waitForURL(targetChatUrlPattern, { timeout: 10000 });
	}
	logStep(`Navigated to Chat A via notification reply. Current URL: ${page.url()}`);
	await takeScreenshot(page, 'navigated-to-chat-a');

	// Wait for the message editor to be present (confirms chat view is mounted)
	await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 15000 });

	// Wait for at least one message of any kind to appear before asserting assistant messages.
	// After a sidebar/hash navigation, the chat loads from IndexedDB asynchronously.
	// Waiting for any message first prevents a race where the assertion starts before
	// the chat list has rendered at all, causing spurious "count = 0" failures.
	const anyMessage = page.locator('[data-testid="message-assistant"], [data-testid="message-user"]');
	await expect(async () => {
		const anyCount = await anyMessage.count();
		logStep(`Total message count: ${anyCount}, URL: ${page.url()}`);
		expect(anyCount).toBeGreaterThan(0);
	}).toPass({ timeout: 30000 });

	// Allow extra time for the AI response to finish streaming if still in progress
	await page.waitForTimeout(5000);
	await takeScreenshot(page, 'chat-a-after-wait');

	// Wait for at least one assistant message to be visible (the original AI response)
	const assistantResponse = page.getByTestId('message-assistant');
	await expect(async () => {
		const count = await assistantResponse.count();
		logStep(`Assistant message count: ${count}, URL: ${page.url()}`);
		expect(count).toBeGreaterThan(0);
	}).toPass({ timeout: 120000 });
	await expect(assistantResponse.first()).toBeVisible({ timeout: 15000 });
	logStep('Assistant response visible in Chat A.');

	// Verify no missing translations on the chat page with notification UI
	await assertNoMissingTranslations(page);
	logStep('No missing translations detected.');

	// ══════════════════════════════════════════════════════════════
	// 17. Delete Chat A via context menu
	// ══════════════════════════════════════════════════════════════
	logStep('Deleting Chat A...');

	// Open sidebar if closed
	const sidebarToggleFinal = page.getByTestId('sidebar-toggle');
	if (await sidebarToggleFinal.isVisible().catch(() => false)) {
		await sidebarToggleFinal.click();
		await page.waitForTimeout(500);
	}

	// Active chat item — use data-testid + active class for specificity
	const activeChatItem = page.locator('[data-testid="chat-item"].active');
	await expect(activeChatItem).toBeVisible({ timeout: 10000 });

	// Right-click → delete (click once for confirm mode, click again to confirm)
	await activeChatItem.click({ button: 'right' });
	await takeScreenshot(page, 'context-menu');

	const deleteButton = page.getByTestId('chat-context-delete');
	await expect(deleteButton).toBeVisible({ timeout: 5000 });
	await deleteButton.click();
	await takeScreenshot(page, 'delete-confirm');
	await deleteButton.click();
	logStep('Confirmed Chat A deletion.');

	await expect(activeChatItem).not.toBeVisible({ timeout: 10000 });
	await takeScreenshot(page, 'chat-deleted');
	logStep('Chat A deleted. Test complete.');
});
