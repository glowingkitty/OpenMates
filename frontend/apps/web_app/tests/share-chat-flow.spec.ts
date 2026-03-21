/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Share chat flow E2E test: login, create a chat, then share it.
 *
 * Tests the full share creation flow:
 *   1. Login with existing account + 2FA
 *   2. Start a new chat and send a simple question
 *   3. Wait for AI response
 *   4. Open the share panel via the chat header share button
 *   5. Generate a share link (default settings)
 *   6. Verify copy-link button, QR code, short link generation
 *   7. Test back-to-config flow and expiration setting
 *   8. Cleanup: delete the chat
 *
 * Uses data-testid selectors per R11 (testing.md).
 * Uses console-monitor.ts per R10.
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 * - PLAYWRIGHT_TEST_BASE_URL
 */

const { test, expect, attachConsoleListeners, attachNetworkListeners, saveWarnErrorLogs } =
	require('./console-monitor');

const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	generateTotp,
	assertNoMissingTranslations,
	getTestAccount,
	getE2EDebugUrl,
	withMockMarker
} = require('./signup-flow-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

// ─── Helpers ─────────────────────────────────────────────────────────────────

async function loginToTestAccount(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void,
	takeStepScreenshot: (page: any, label: string) => Promise<void>
): Promise<void> {
	await page.goto(getE2EDebugUrl('/'));
	await takeStepScreenshot(page, 'home');

	const headerLoginButton = page.getByRole('button', { name: /login.*sign up|sign up/i });
	await expect(headerLoginButton).toBeVisible({ timeout: 15000 });
	await headerLoginButton.click();
	await takeStepScreenshot(page, 'login-dialog');

	const emailInput = page.locator('#login-email-input');
	await expect(emailInput).toBeVisible({ timeout: 15000 });
	await emailInput.fill(TEST_EMAIL);

	const stayLoggedInLabel = page.locator(
		'label.toggle[for="stayLoggedIn"], label.toggle:has(#stayLoggedIn)'
	);
	try {
		await stayLoggedInLabel.waitFor({ state: 'visible', timeout: 3000 });
		const checkbox = page.locator('#stayLoggedIn');
		const isChecked = await checkbox.evaluate((el: HTMLInputElement) => el.checked);
		if (!isChecked) {
			await stayLoggedInLabel.click();
			logCheckpoint('Clicked "Stay logged in" toggle.');
		}
	} catch {
		logCheckpoint('Could not find "Stay logged in" toggle — proceeding without it.');
	}

	await page.getByRole('button', { name: /continue/i }).click();
	logCheckpoint('Entered email and clicked continue.');

	const passwordInput = page.locator('#login-password-input');
	await expect(passwordInput).toBeVisible({ timeout: 15000 });
	await passwordInput.fill(TEST_PASSWORD);

	const otpInput = page.locator('#login-otp-input');
	await expect(otpInput).toBeVisible({ timeout: 15000 });

	const submitLoginButton = page.locator('button[type="submit"]', { hasText: /log in|login/i });
	const errorMessage = page
		.locator('.error-message, [class*="error"]')
		.filter({ hasText: /wrong|invalid|incorrect/i });

	let loginSuccess = false;
	for (let attempt = 1; attempt <= 3 && !loginSuccess; attempt++) {
		const otpCode = generateTotp(TEST_OTP_KEY);
		await otpInput.fill(otpCode);
		logCheckpoint(`Generated and entered OTP (attempt ${attempt}).`);

		await expect(submitLoginButton).toBeVisible();
		await submitLoginButton.click();
		logCheckpoint('Submitted login form.');

		try {
			await expect(otpInput).not.toBeVisible({ timeout: 15000 });
			loginSuccess = true;
			logCheckpoint('Login successful.');
		} catch {
			const hasError = await errorMessage.isVisible().catch(() => false);
			if (hasError && attempt < 3) {
				logCheckpoint(`OTP attempt ${attempt} failed, retrying...`);
				await page.waitForTimeout(2000);
			} else if (attempt === 3) {
				throw new Error('Login failed after 3 OTP attempts');
			}
		}
	}

	logCheckpoint('Waiting for chat interface...');
	await page.waitForTimeout(3000);
	const messageEditor = page.locator('[data-testid="message-editor"]');
	await expect(messageEditor).toBeVisible({ timeout: 20000 });
	logCheckpoint('Chat interface loaded.');
}

async function startNewChat(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void
): Promise<void> {
	await page.waitForTimeout(1000);
	const newChatButtonSelectors = [
		'.new-chat-cta-button',
		'.icon_create',
		'button[aria-label*="New"]',
		'button[aria-label*="new"]'
	];
	for (const selector of newChatButtonSelectors) {
		const button = page.locator(selector).first();
		if (await button.isVisible({ timeout: 3000 }).catch(() => false)) {
			logCheckpoint(`Found New Chat button: ${selector}`);
			await button.click();
			await page.waitForTimeout(2000);
			return;
		}
	}
	logCheckpoint('WARNING: Could not find New Chat button.');
}

async function sendMessage(
	page: any,
	message: string,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void,
	takeStepScreenshot: (page: any, label: string) => Promise<void>,
	stepLabel: string
): Promise<void> {
	const messageEditor = page.locator('[data-testid="message-editor"]');
	await expect(messageEditor).toBeVisible();
	await messageEditor.click();
	await page.keyboard.type(message);
	logCheckpoint(`Typed message: "${message}"`);
	await takeStepScreenshot(page, `${stepLabel}-message-typed`);

	const sendButton = page.locator('[data-action="send-message"]');
	await expect(sendButton).toBeVisible({ timeout: 15000 });
	await expect(sendButton).toBeEnabled({ timeout: 5000 });
	await sendButton.click();
	logCheckpoint('Clicked send button.');
}

async function deleteActiveChat(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void,
	takeStepScreenshot: (page: any, label: string) => Promise<void>,
	stepLabel: string
): Promise<void> {
	logCheckpoint('Attempting to delete chat (best-effort)...');
	try {
		// Ensure sidebar is open
		const activityHistory = page.locator('.activity-history-wrapper');
		if (!(await activityHistory.isVisible().catch(() => false))) {
			const menuToggle = page.locator('[data-testid="sidebar-toggle"]');
			if (await menuToggle.isVisible().catch(() => false)) {
				await menuToggle.click();
				await page.waitForTimeout(1000);
			}
		}

		const activeChatItem = page.locator('.chat-item-wrapper.active');
		if (!(await activeChatItem.isVisible({ timeout: 5000 }).catch(() => false))) {
			logCheckpoint('No active chat item visible - skipping cleanup.');
			return;
		}

		await activeChatItem.click({ button: 'right' });
		await takeStepScreenshot(page, `${stepLabel}-context-menu`);
		await page.waitForTimeout(300);

		const deleteButton = page.locator('.menu-item.delete');
		if (!(await deleteButton.isVisible({ timeout: 3000 }).catch(() => false))) {
			logCheckpoint('Delete button not visible - skipping.');
			await page.keyboard.press('Escape');
			return;
		}

		await deleteButton.click();
		await takeStepScreenshot(page, `${stepLabel}-delete-confirm`);
		await deleteButton.click(); // confirm
		logCheckpoint('Confirmed chat deletion.');
		await expect(activeChatItem).not.toBeVisible({ timeout: 10000 });
		logCheckpoint('Chat deleted successfully.');
	} catch (error) {
		logCheckpoint(`Cleanup failed (non-fatal): ${error}`);
	}
}

// ─── Test ────────────────────────────────────────────────────────────────────

test('creates and shares a chat link with QR code and short link', async ({
	page
}: {
	page: any;
}) => {
	attachConsoleListeners(page);
	attachNetworkListeners(page);

	test.slow();
	test.setTimeout(300000);

	const logCheckpoint = createSignupLogger('SHARE_CHAT');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'share-chat'
	});

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	await archiveExistingScreenshots(logCheckpoint);
	logCheckpoint('Starting share chat flow test.', { email: TEST_EMAIL });

	// ── Step 1: Login ─────────────────────────────────────────────────────
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);

	// ── Step 2: Start new chat ────────────────────────────────────────────
	await startNewChat(page, logCheckpoint);

	// ── Step 3: Send a simple question ────────────────────────────────────
	await sendMessage(
		page,
		withMockMarker('What is the capital of France?', 'share_chat_flow'),
		logCheckpoint,
		takeStepScreenshot,
		'share-chat'
	);

	// ── Step 4: Wait for AI response ──────────────────────────────────────
	logCheckpoint('Waiting for assistant response...');
	const assistantMessage = page.locator('.message-wrapper.assistant');
	await expect(assistantMessage.first()).toBeVisible({ timeout: 60000 });
	await expect(assistantMessage.last()).toContainText('Paris', { timeout: 45000 });
	logCheckpoint('Assistant response received and contains "Paris".');
	await takeStepScreenshot(page, 'assistant-response');

	saveWarnErrorLogs('share-chat', 'after_response');

	// ── Step 5: Click share button in chat header ─────────────────────────
	const shareButton = page.locator('[data-testid="chat-share-button"]');
	await expect(shareButton).toBeVisible({ timeout: 10000 });
	await shareButton.click();
	logCheckpoint('Clicked chat share button.');

	// ── Step 6: Wait for share settings panel ─────────────────────────────
	// Wait for the share generate-link button (indicates share panel loaded)
	const generateLinkButton = page.locator('[data-testid="share-generate-link"]');
	await expect(generateLinkButton).toBeVisible({ timeout: 15000 });
	logCheckpoint('Share panel loaded — configuration step visible.');
	await takeStepScreenshot(page, 'share-config-step');

	// ── Step 7: Verify chat preview is shown ──────────────────────────────
	const chatPreview = page.locator('[data-testid="share-chat-preview"]');
	await expect(chatPreview).toBeVisible({ timeout: 10000 });
	logCheckpoint('Chat preview is visible in share panel.');

	// ── Step 8: Click "Share chat" (default settings) ─────────────────────
	await generateLinkButton.click();
	logCheckpoint('Clicked "Share chat" button.');

	// ── Step 9: Verify link generated step ────────────────────────────────
	const copyLinkButton = page.locator('[data-testid="share-copy-link"]');
	await expect(copyLinkButton).toBeVisible({ timeout: 30000 });
	logCheckpoint('Copy link button is visible — link generated.');
	await takeStepScreenshot(page, 'link-generated');

	// ── Step 10: Verify QR code ───────────────────────────────────────────
	const qrCode = page.locator('[data-testid="share-qr-code"]');
	await expect(qrCode).toBeVisible({ timeout: 10000 });
	const qrSvg = qrCode.locator('svg');
	await expect(qrSvg).toBeVisible({ timeout: 5000 });
	logCheckpoint('QR code is visible with SVG.');

	// ── Step 11: Test QR fullscreen ───────────────────────────────────────
	await qrCode.click();
	const qrFullscreen = page.locator('[data-testid="share-qr-fullscreen"]');
	await expect(qrFullscreen).toBeVisible({ timeout: 5000 });
	logCheckpoint('QR fullscreen overlay opened.');
	await takeStepScreenshot(page, 'qr-fullscreen');

	await page.keyboard.press('Escape');
	await expect(qrFullscreen).not.toBeVisible({ timeout: 5000 });
	logCheckpoint('QR fullscreen closed.');

	// ── Step 12: Test short link generation ───────────────────────────────
	const shortLinkSection = page.locator('[data-testid="share-short-link-section"]');
	await expect(shortLinkSection).toBeVisible({ timeout: 5000 });
	logCheckpoint('Short link section is visible.');

	// Select 1 min TTL (first TTL option)
	const ttlOptions = shortLinkSection.locator('.short-link-ttl-option');
	await expect(ttlOptions.first()).toBeVisible({ timeout: 5000 });
	await ttlOptions.first().click();
	logCheckpoint('Selected 1 min TTL for short link.');

	// Generate short link
	const generateShortLink = page.locator('[data-testid="share-short-link-generate"]');
	await expect(generateShortLink).toBeVisible({ timeout: 5000 });
	await generateShortLink.click();
	logCheckpoint('Clicked generate short link.');

	// Wait for short link to appear
	const shortLinkCopy = page.locator('[data-testid="share-short-link-copy"]');
	await expect(shortLinkCopy).toBeVisible({ timeout: 30000 });
	logCheckpoint('Short link generated and copy button visible.');

	// Verify countdown
	const countdown = page.locator('[data-testid="share-short-link-countdown"]');
	await expect(countdown).toBeVisible({ timeout: 5000 });
	logCheckpoint('Short link countdown timer visible.');
	await takeStepScreenshot(page, 'short-link-generated');

	// ── Step 13: Test copy link ───────────────────────────────────────────
	await copyLinkButton.click();
	// The copied state adds a .copied class
	await expect(copyLinkButton).toHaveClass(/copied/, { timeout: 5000 });
	logCheckpoint('Copy link button shows copied state.');

	// ── Step 14: Test back-to-config ──────────────────────────────────────
	const backButton = page.locator('[data-testid="share-back-to-config"]');
	await expect(backButton).toBeVisible({ timeout: 5000 });
	await backButton.click();
	logCheckpoint('Clicked back to configuration.');

	// Verify we're back in config step
	await expect(generateLinkButton).toBeVisible({ timeout: 10000 });
	logCheckpoint('Back in configuration step.');

	// ── Step 15: Set 1-minute expiration and reshare ──────────────────────
	const durationOptions = page.locator('.duration-option');
	await expect(durationOptions.nth(1)).toBeVisible({ timeout: 5000 });
	await durationOptions.nth(1).click(); // 1 minute
	logCheckpoint('Selected 1-minute expiration.');

	await generateLinkButton.click();
	logCheckpoint('Clicked "Share chat" with expiration.');

	// Verify link regenerated
	await expect(copyLinkButton).toBeVisible({ timeout: 30000 });

	// Verify expiration info
	const expirationInfo = page.locator('[data-testid="share-expiration-info"]');
	await expect(expirationInfo).toBeVisible({ timeout: 5000 });
	logCheckpoint('Expiration info is visible.');
	await takeStepScreenshot(page, 'with-expiration');

	saveWarnErrorLogs('share-chat', 'after_share_flow');

	// ── Step 16: Close settings ───────────────────────────────────────────
	await page.keyboard.press('Escape');
	await page.waitForTimeout(500);
	logCheckpoint('Closed settings panel.');

	// ── Step 17: Verify no missing translations ───────────────────────────
	await assertNoMissingTranslations(page);
	logCheckpoint('No missing translations.');

	// ── Step 18: Cleanup — delete chat ────────────────────────────────────
	await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'share-chat-cleanup');

	await takeStepScreenshot(page, 'test-complete');
	logCheckpoint('Share chat flow test completed successfully.');
});
