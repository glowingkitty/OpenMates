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
	assertNoMissingTranslations,
	getTestAccount,
	getE2EDebugUrl,
	withMockMarker
} = require('./signup-flow-helpers');

const { loginToTestAccount, startNewChat, sendMessage, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

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

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

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
