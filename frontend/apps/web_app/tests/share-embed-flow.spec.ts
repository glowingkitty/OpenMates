/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Share embed flow E2E test: login, trigger a web search, then share the embed.
 *
 * Tests the embed share creation flow:
 *   1. Login with existing account + 2FA
 *   2. Start a new chat and send a web search query
 *   3. Wait for the web search embed to appear and reach "finished" state
 *   4. Open the embed in fullscreen
 *   5. Click the share button in the embed fullscreen top bar
 *   6. Verify the share panel opens in embed share mode
 *   7. Generate a share link and verify QR code
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

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

// ─── Test ────────────────────────────────────────────────────────────────────

test('shares a web search embed via fullscreen share button', async ({
	page
}: {
	page: any;
}) => {
	attachConsoleListeners(page);
	attachNetworkListeners(page);

	test.slow();
	test.setTimeout(300000);

	const logCheckpoint = createSignupLogger('SHARE_EMBED');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'share-embed'
	});

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	await archiveExistingScreenshots(logCheckpoint);
	logCheckpoint('Starting share embed flow test.', { email: TEST_EMAIL });

	// ── Step 1: Login ─────────────────────────────────────────────────────
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);

	// ── Step 2: Start new chat ────────────────────────────────────────────
	await startNewChat(page, logCheckpoint);

	// ── Step 3: Send a web search query ───────────────────────────────────
	await sendMessage(
		page,
		withMockMarker("Search on the web for 'Berlin weather'", 'share_embed_flow'),
		logCheckpoint,
		takeStepScreenshot,
		'share-embed'
	);

	// ── Step 4: Wait for AI response ──────────────────────────────────────
	logCheckpoint('Waiting for assistant response with web search results...');
	const assistantMessage = page.locator('.message-wrapper.assistant');
	await expect(assistantMessage.first()).toBeVisible({ timeout: 60000 });
	logCheckpoint('Assistant response visible.');

	// ── Step 5: Wait for web search embed to finish ───────────────────────
	const finishedPreview = page.locator(
		'.unified-embed-preview[data-app-id="web"][data-skill-id="search"][data-status="finished"]'
	);
	logCheckpoint('Waiting for web search embed to reach finished state...');
	await expect(finishedPreview.first()).toBeVisible({ timeout: 90000 });
	logCheckpoint('Web search embed reached finished state.');
	await takeStepScreenshot(page, 'embed-finished');

	saveWarnErrorLogs('share-embed', 'after_search_finished');

	// ── Step 6: Open embed fullscreen ─────────────────────────────────────
	await finishedPreview.first().click();
	const fullscreenOverlay = page.locator('.unified-embed-fullscreen-overlay');
	await expect(fullscreenOverlay).toBeVisible({ timeout: 10000 });
	await page.waitForTimeout(500); // wait for open animation
	logCheckpoint('Embed fullscreen overlay opened.');
	await takeStepScreenshot(page, 'embed-fullscreen');

	// ── Step 7: Click share button in embed fullscreen ────────────────────
	const embedShareButton = page.locator('[data-testid="embed-share-button"]');
	await expect(embedShareButton).toBeVisible({ timeout: 5000 });
	await embedShareButton.click();
	logCheckpoint('Clicked share button in embed fullscreen.');

	// ── Step 8: Wait for share settings panel (embed mode) ────────────────
	const shareEmbedButton = page.locator('[data-testid="share-generate-link"]');
	await expect(shareEmbedButton).toBeVisible({ timeout: 15000 });
	logCheckpoint('Share panel loaded — embed share configuration step.');
	await takeStepScreenshot(page, 'embed-share-config');

	// ── Step 9: Verify embed preview is shown (not chat preview) ──────────
	const embedPreview = page.locator('[data-testid="share-embed-preview"]');
	await expect(embedPreview).toBeVisible({ timeout: 10000 });
	logCheckpoint('Embed preview visible in share panel (correct share mode).');

	// Verify chat preview is NOT shown
	const chatPreview = page.locator('[data-testid="share-chat-preview"]');
	await expect(chatPreview).not.toBeVisible({ timeout: 2000 });
	logCheckpoint('Chat preview correctly not visible (embed sharing mode confirmed).');

	// ── Step 10: Click "Share embed" ──────────────────────────────────────
	await shareEmbedButton.click();
	logCheckpoint('Clicked "Share embed" button.');

	// ── Step 11: Verify link generated ────────────────────────────────────
	const copyLinkButton = page.locator('[data-testid="share-copy-link"]');
	await expect(copyLinkButton).toBeVisible({ timeout: 30000 });
	logCheckpoint('Copy link button visible — embed share link generated.');
	await takeStepScreenshot(page, 'embed-link-generated');

	// Verify QR code
	const qrCode = page.locator('[data-testid="share-qr-code"]');
	await expect(qrCode).toBeVisible({ timeout: 10000 });
	const qrSvg = qrCode.locator('svg');
	await expect(qrSvg).toBeVisible({ timeout: 5000 });
	logCheckpoint('QR code visible with SVG.');

	// ── Step 12: Test copy link ───────────────────────────────────────────
	await copyLinkButton.click();
	await expect(copyLinkButton).toHaveClass(/copied/, { timeout: 5000 });
	logCheckpoint('Copy link shows copied state.');

	saveWarnErrorLogs('share-embed', 'after_share_flow');

	// ── Step 13: Close settings panel ─────────────────────────────────────
	await page.keyboard.press('Escape');
	await page.waitForTimeout(500);
	logCheckpoint('Closed settings panel.');

	// ── Step 14: Close fullscreen if still open ───────────────────────────
	if (await fullscreenOverlay.isVisible().catch(() => false)) {
		// Try minimize button first, then Escape
		const minimizeButton = fullscreenOverlay.locator('.icon_minimize').first();
		if (await minimizeButton.isVisible().catch(() => false)) {
			await minimizeButton.click();
		} else {
			await page.keyboard.press('Escape');
		}
		await expect(fullscreenOverlay).not.toBeVisible({ timeout: 5000 });
		logCheckpoint('Embed fullscreen closed.');
	}

	// ── Step 15: Verify no missing translations ───────────────────────────
	await assertNoMissingTranslations(page);
	logCheckpoint('No missing translations.');

	// ── Step 16: Cleanup — delete chat ────────────────────────────────────
	await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'embed-share-cleanup');

	await takeStepScreenshot(page, 'test-complete');
	logCheckpoint('Share embed flow test completed successfully.');
});
