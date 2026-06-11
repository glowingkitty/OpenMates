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
	withMockMarker
} = require('./signup-flow-helpers');

const { loginToTestAccount, startNewChat, sendMessage, deleteActiveChat, waitForAssistantMessage } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { docAssert, docCheckpoint } = require('./helpers/doc-checkpoint');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const SHARING_GUIDE_PATH = 'docs/user-guide/sharing.md';
const EXPECTED_CHAT_OG_DESCRIPTION_TERM = 'Paris';

function metaContent(html: string, selector: string): string {
	const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
	const regex = new RegExp(`<meta[^>]+(?:property|name)="${escapedSelector}"[^>]+content="([^"]*)"`, 'i');
	const match = html.match(regex);
	return match?.[1] ?? '';
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
	await waitForAssistantMessage(page, {
		which: 'last',
		contains: 'Paris',
		logCheckpoint
	});
	logCheckpoint('Assistant response received and contains "Paris".');
	await takeStepScreenshot(page, 'assistant-response');

	saveWarnErrorLogs('share-chat', 'after_response');

	// ── Step 5: Click share button in chat header ─────────────────────────
	const shareButton = page.locator('[data-testid="chat-share-button"]');
	await docAssert('share-panel-opens-from-chat-header', async () => {
		await expect(shareButton).toBeVisible({ timeout: 10000 });
		await shareButton.click();
	});
	logCheckpoint('Clicked chat share button.');

	// ── Step 6: Wait for share settings panel ─────────────────────────────
	// Wait for the share generate-link button (indicates share panel loaded)
	const generateLinkButton = page.locator('[data-testid="share-generate-link"]');
	await docAssert('share-panel-shows-link-configuration', async () => {
		await expect(generateLinkButton).toBeVisible({ timeout: 15000 });
	});
	logCheckpoint('Share panel loaded — configuration step visible.');
	await takeStepScreenshot(page, 'share-config-step');
	await docCheckpoint(page, {
		id: 'share-config-step',
		guide: SHARING_GUIDE_PATH,
		title: 'Configure a shared chat link',
		screenshot: 'docs/images/user-guide/sharing/share-config-step.jpg'
	});

	// ── Step 7: Verify chat preview is shown ──────────────────────────────
	const chatPreview = page.locator('[data-testid="share-chat-preview"]');
	await expect(chatPreview).toBeVisible({ timeout: 10000 });
	const expectedChatOgTitle = (await chatPreview.getByTestId('chat-title').textContent())?.trim();
	expect(expectedChatOgTitle).toBeTruthy();
	logCheckpoint('Chat preview is visible in share panel.');

	// ── Step 8: Click "Share chat" (default settings) ─────────────────────
	await generateLinkButton.click();
	logCheckpoint('Clicked "Share chat" button.');
	await expect(page.getByTestId('share-generation-status')).toContainText(/Sharing chat/i, {
		timeout: 1000
	});

	// ── Step 9: Verify link generated step ────────────────────────────────
	const copyLinkButton = page.locator('[data-testid="share-copy-link"]');
	await docAssert('share-link-has-copy-option', async () => {
		await expect(copyLinkButton).toBeVisible({ timeout: 30000 });
	});
	logCheckpoint('Copy link button is visible — link generated.');
	await takeStepScreenshot(page, 'link-generated');
	await docCheckpoint(page, {
		id: 'link-generated',
		guide: SHARING_GUIDE_PATH,
		title: 'Share link generated with copy and QR options',
		screenshot: 'docs/images/user-guide/sharing/link-generated.jpg'
	});

	// ── Step 10: Verify QR code ───────────────────────────────────────────
	const qrCode = page.locator('[data-testid="share-qr-code"]');
	await docAssert('share-link-has-qr-code', async () => {
		await expect(qrCode).toBeVisible({ timeout: 10000 });
		const qrSvg = qrCode.locator('svg');
		await expect(qrSvg).toBeVisible({ timeout: 5000 });
	});
	logCheckpoint('QR code is visible with SVG.');

	// ── Step 11: Test QR fullscreen ───────────────────────────────────────
	await qrCode.click();
	const qrFullscreen = page.locator('[data-testid="share-qr-fullscreen"]');
	await docAssert('share-qr-code-opens-fullscreen', async () => {
		await expect(qrFullscreen).toBeVisible({ timeout: 5000 });
	});
	logCheckpoint('QR fullscreen overlay opened.');
	await takeStepScreenshot(page, 'qr-fullscreen');
	await docCheckpoint(page, {
		id: 'qr-fullscreen',
		guide: SHARING_GUIDE_PATH,
		title: 'QR code fullscreen view',
		screenshot: 'docs/images/user-guide/sharing/qr-fullscreen.jpg'
	});

	await page.keyboard.press('Escape');
	await expect(qrFullscreen).not.toBeVisible({ timeout: 5000 });
	logCheckpoint('QR fullscreen closed.');

	// ── Step 12: Verify short link is primary ──────────────────────────────
	const shortLinkSection = page.locator('[data-testid="share-short-link-section"]');
	await docAssert('share-link-uses-short-link-by-default', async () => {
		await expect(shortLinkSection).toBeVisible({ timeout: 5000 });
	});
	logCheckpoint('Primary short link section is visible.');

	const shortLinkCopy = page.locator('[data-testid="share-short-link-copy"]');
	await expect(shortLinkCopy).toBeVisible({ timeout: 30000 });
	const shortLinkUrl = (await shortLinkCopy.getByTestId('share-short-link-url').innerText()).trim();
	expect(shortLinkUrl).toMatch(/\/s\/[A-Za-z0-9]{6,12}#[A-Za-z0-9]{4,12}$/);
	logCheckpoint('Generated link is already a durable short link.');

	const crawlerUrl = new URL(shortLinkUrl, page.url());
	crawlerUrl.hash = '';
	let crawlerHtml = '';
	await expect
		.poll(
			async () => {
				const response = await page.request.get(crawlerUrl.toString());
				crawlerHtml = await response.text();
				return metaContent(crawlerHtml, 'og:title');
			},
			{ timeout: 30000, intervals: [1000, 2000, 3000, 5000] }
		)
		.toBe(expectedChatOgTitle);

	const ogDescription = metaContent(crawlerHtml, 'og:description');
	const ogImage = metaContent(crawlerHtml, 'og:image');
	await docAssert('share-link-has-chat-og-metadata', async () => {
		expect(ogDescription).toContain(EXPECTED_CHAT_OG_DESCRIPTION_TERM);
		expect(ogImage).toContain('/v1/share/short-url/');
		expect(ogImage).toContain('/og-image.png');
	});
	logCheckpoint('Short link crawler metadata uses chat title, summary, and generated OG image.', {
		ogTitle: expectedChatOgTitle,
		ogDescription,
		ogImage
	});

	const ogImageResponse = await page.request.get(ogImage);
	await docAssert('share-link-og-image-is-generated-png', async () => {
		expect(ogImageResponse.ok()).toBe(true);
		expect(ogImageResponse.headers()['content-type']).toContain('image/png');
		const imageBytes = await ogImageResponse.body();
		expect(imageBytes.subarray(0, 8).toString('hex')).toBe('89504e470d0a1a0a');
		expect(imageBytes.length).toBeGreaterThan(1000);
	});
	logCheckpoint('Generated OG image URL returns PNG data.');

	await takeStepScreenshot(page, 'short-link-generated');
	await docCheckpoint(page, {
		id: 'short-link-generated',
		guide: SHARING_GUIDE_PATH,
		title: 'Short link generated by default',
		screenshot: 'docs/images/user-guide/sharing/short-link-generated.jpg'
	});

	await page.keyboard.press('Escape');
	await expect(copyLinkButton).not.toBeVisible({ timeout: 5000 });
	await shareButton.click();
	await expect(copyLinkButton).toBeVisible({ timeout: 10000 });
	await expect(page.locator('[data-testid="share-short-link-url"]')).toHaveText(shortLinkUrl, {
		timeout: 5000
	});
	await expect(qrCode).toBeVisible({ timeout: 5000 });
	logCheckpoint('Reopening share panel restored existing short link and QR code directly.');

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
	const durationOptions = page.getByTestId('duration-option');
	await expect(durationOptions.nth(1)).toBeVisible({ timeout: 5000 });
	await durationOptions.nth(1).click(); // 1 minute
	logCheckpoint('Selected 1-minute expiration.');

	await page.route('**/v1/share/short-url', async (route: any) => {
		if (route.request().method() !== 'POST') {
			await route.continue();
			return;
		}

		await page.waitForTimeout(7000);
		try {
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({ success: true, expires_at: null })
			});
		} catch (_error) {
			// The app aborts this request after 5 seconds and falls back to the long link.
		}
	});

	await generateLinkButton.click();
	logCheckpoint('Clicked "Share chat" with expiration.');
	await expect(page.getByTestId('share-generation-status')).toContainText(/Sharing chat/i, {
		timeout: 1000
	});

	// Verify link regenerated
	await expect(copyLinkButton).toBeVisible({ timeout: 30000 });
	await expect(page.getByTestId('share-short-link-error')).toContainText(/took too long/i, {
		timeout: 8000
	});
	await expect(page.locator('[data-share-url-kind="long"]')).toBeVisible({ timeout: 5000 });
	await page.unroute('**/v1/share/short-url');

	// Verify expiration info
	const expirationInfo = page.locator('[data-testid="share-expiration-info"]');
	await docAssert('share-link-can-have-expiration', async () => {
		await expect(expirationInfo).toBeVisible({ timeout: 5000 });
	});
	logCheckpoint('Expiration info is visible.');
	await takeStepScreenshot(page, 'with-expiration');
	await docCheckpoint(page, {
		id: 'with-expiration',
		guide: SHARING_GUIDE_PATH,
		title: 'Share link configured with expiration',
		screenshot: 'docs/images/user-guide/sharing/with-expiration.jpg'
	});

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
