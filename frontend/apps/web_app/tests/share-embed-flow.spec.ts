/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Share embed flow E2E test: open a persisted web-search embed, then share it.
 *
 * Tests the embed share creation flow:
 *   1. Login with existing account + 2FA
 *   2. Open a shared chat with a persisted web-search embed
 *   3. Open the embed in fullscreen and load its stored results
 *   4. Click the share button in the embed fullscreen top bar
 *   5. Verify the share panel opens in embed share mode
 *   6. Generate a share link and verify QR code
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
	getTestAccount
} = require('./signup-flow-helpers');

const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const SHARED_CHAT_WITH_WEB_SEARCH = 'https://app.dev.openmates.org/s/pznF7EHJ#s28GVG';

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
		filenamePrefix: 'share-embed',
		fullPage: false
	});

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	await archiveExistingScreenshots(logCheckpoint);
	logCheckpoint('Starting share embed flow test.', { email: TEST_EMAIL });

	// ── Step 1: Login ─────────────────────────────────────────────────────
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);

	// ── Step 2: Open a persisted encrypted web-search embed ───────────────
	const response = await page.goto(SHARED_CHAT_WITH_WEB_SEARCH, { waitUntil: 'networkidle' });
	expect(response?.status()).toBe(200);
	const webPreview = page
		.locator('[data-testid="embed-preview"][data-app-id="web"][data-skill-id="search"]')
		.first();
	await expect(webPreview).toBeVisible({ timeout: 30_000 });
	logCheckpoint('Persisted web search embed is visible.');
	await takeStepScreenshot(page, 'embed-finished');

	// ── Step 3: Open the embed fullscreen and load stored results ─────────
	await webPreview.click();
	const fullscreenOverlay = page.getByTestId('embed-fullscreen-overlay');
	await expect(fullscreenOverlay).toBeVisible({ timeout: 10000 });
	await expect(fullscreenOverlay.getByTestId('search-template-grid')).toBeVisible({ timeout: 60_000 });
	logCheckpoint('Embed fullscreen overlay opened.');
	await takeStepScreenshot(page, 'embed-fullscreen');

	// ── Step 4: Click share button in embed fullscreen ────────────────────
	const embedShareButton = page.locator('[data-testid="embed-share-button"]');
	await expect(embedShareButton).toBeVisible({ timeout: 5000 });
	await embedShareButton.click();
	logCheckpoint('Clicked share button in embed fullscreen.');

	// ── Step 5: Wait for share settings panel (embed mode) ────────────────
	const shareEmbedButton = page.locator('[data-testid="share-generate-link"]');
	await expect(shareEmbedButton).toBeVisible({ timeout: 15000 });
	logCheckpoint('Share panel loaded — embed share configuration step.');
	await takeStepScreenshot(page, 'embed-share-config');

	// ── Step 6: Verify embed preview is shown (not chat preview) ──────────
	const embedPreview = page.locator('[data-testid="share-embed-preview"]');
	await expect(embedPreview).toBeVisible({ timeout: 10000 });
	logCheckpoint('Embed preview visible in share panel (correct share mode).');

	// Verify chat preview is NOT shown
	const chatPreview = page.locator('[data-testid="share-chat-preview"]');
	await expect(chatPreview).not.toBeVisible({ timeout: 2000 });
	logCheckpoint('Chat preview correctly not visible (embed sharing mode confirmed).');

	// ── Step 7: Click "Share embed" ───────────────────────────────────────
	await shareEmbedButton.click();
	logCheckpoint('Clicked "Share embed" button.');

	// ── Step 8: Verify link generated ─────────────────────────────────────
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

	// ── Step 9: Test copy link ────────────────────────────────────────────
	await copyLinkButton.click();
	await expect(copyLinkButton).toHaveClass(/copied/, { timeout: 5000 });
	logCheckpoint('Copy link shows copied state.');

	saveWarnErrorLogs('share-embed', 'after_share_flow');

	// ── Step 10: Close settings panel ─────────────────────────────────────
	await page.keyboard.press('Escape');
	await page.waitForTimeout(500);
	logCheckpoint('Closed settings panel.');

	// ── Step 11: Close fullscreen if still open ───────────────────────────
	if (await fullscreenOverlay.isVisible().catch(() => false)) {
		// Try minimize button first, then Escape
		const minimizeButton = fullscreenOverlay.getByTestId('embed-minimize').first();
		if (await minimizeButton.isVisible().catch(() => false)) {
			await minimizeButton.click();
		} else {
			await page.keyboard.press('Escape');
		}
		await expect(fullscreenOverlay).not.toBeVisible({ timeout: 5000 });
		logCheckpoint('Embed fullscreen closed.');
	}

	// ── Step 12: Verify no missing translations ───────────────────────────
	await assertNoMissingTranslations(page);
	logCheckpoint('No missing translations.');

	await takeStepScreenshot(page, 'test-complete');
	logCheckpoint('Share embed flow test completed successfully.');
});
