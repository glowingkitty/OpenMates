/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Share chat flow E2E test: login, create a chat, then share it.
 *
 * Tests the full share creation flow:
 *   1. Login with existing account + 2FA
 *   2. Start a new chat with a deterministic web + image embed fixture
 *   3. Wait for AI response and image-search embed completion
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
const { waitForEmbedFinished } = require('./helpers/embed-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { docAssert } = require('./helpers/doc-checkpoint');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const EXPECTED_CHAT_OG_DESCRIPTION_TERM = 'berlin';

function metaContent(html: string, selector: string): string {
	const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
	const regex = new RegExp(`<meta[^>]+(?:property|name)="${escapedSelector}"[^>]+content="([^"]*)"`, 'i');
	const match = html.match(regex);
	return match?.[1] ?? '';
}

function shortLinkMetadataUrlFromOgImage(ogImage: string): string {
	return ogImage.replace(/\/og-image\.png(?:\?.*)?$/, '/metadata');
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

	// ── Step 3: Trigger image search so the shared preview has image metadata ─
	await sendMessage(
		page,
		withMockMarker("Search on the web for 'Berlin weather'", 'share_embed_flow'),
		logCheckpoint,
		takeStepScreenshot,
		'share-chat'
	);

	// ── Step 4: Wait for AI response and image-search embed ───────────────
	logCheckpoint('Waiting for assistant response...');
	await waitForAssistantMessage(page, { which: 'last', logCheckpoint });
	await waitForEmbedFinished(page, 'images', 'search');
	await expect(page.getByTestId('chat-header-title')).not.toContainText(/processing|untitled/i, { timeout: 30000 });
	await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 15000 });
	const chatIdMatch = page.url().match(/chat-id=([a-zA-Z0-9-]+)/);
	const activeChatId = chatIdMatch?.[1] ?? '';
	expect(activeChatId).toBeTruthy();
	logCheckpoint('Assistant response received and image-search embed is finished.');

	saveWarnErrorLogs('share-chat', 'after_response');

	// ── Step 5: Click share button in chat header ─────────────────────────
	const shareButton = page.locator('[data-testid="chat-share-button"]');
	await docAssert('share-panel-opens-from-chat-header', async () => {
		await expect(shareButton).toBeVisible({ timeout: 10000 });
		await shareButton.dispatchEvent('click', undefined, { timeout: 10000 });
		await expect(page.getByTestId('settings-menu')).toHaveAttribute('data-active-view', /^chats\/[a-zA-Z0-9-]+\/share$/, {
			timeout: 10000
		});
	});
	logCheckpoint('Clicked chat share button.');

	// ── Step 6: Wait for share settings panel ─────────────────────────────
	// Wait for the share generate-link button (indicates share panel loaded)
	const generateLinkButton = page.locator('[data-testid="share-generate-link"]');
	await docAssert('share-panel-shows-link-configuration', async () => {
		await expect(generateLinkButton).toBeVisible({ timeout: 15000 });
	});
	logCheckpoint('Share panel loaded — configuration step visible.');

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

	// ── Step 10: Verify QR code reveal ─────────────────────────────────────
	await page.getByTestId('chat-settings-share-show-qr').click();
	const qrCode = page.locator('[data-testid="chat-settings-share-qr"]');
	await docAssert('share-link-has-qr-code', async () => {
		await expect(qrCode).toBeVisible({ timeout: 10000 });
		await expect(qrCode.locator('img')).toBeVisible({ timeout: 5000 });
	});
	logCheckpoint('QR code is visible with SVG.');

	// ── Step 11: Verify short link is primary ──────────────────────────────
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
	const metadataResponse = await page.request.get(shortLinkMetadataUrlFromOgImage(ogImage));
	const shortLinkMetadata = await metadataResponse.json();
	await docAssert('share-link-has-chat-og-metadata', async () => {
		expect(ogDescription.toLowerCase()).toContain(EXPECTED_CHAT_OG_DESCRIPTION_TERM);
		expect(shortLinkMetadata.image_text).toBeTruthy();
		expect(shortLinkMetadata.image_text.toLowerCase()).toContain(EXPECTED_CHAT_OG_DESCRIPTION_TERM);
		expect(ogImage).toContain('/v1/share/short-url/');
		expect(ogImage).toContain('/og-image.png');
		expect(metadataResponse.ok()).toBe(true);
		expect(shortLinkMetadata.image_bubbles.length).toBeGreaterThanOrEqual(2);
		expect(shortLinkMetadata.image_bubbles[0].imageUrl).toContain('preview.openmates.org/api/v1/image');
		expect(shortLinkMetadata.image_bubbles[1].imageUrl).toContain('preview.openmates.org/api/v1/image');
	});
	logCheckpoint('Short link crawler metadata uses chat title, summary, image bubbles, and generated OG image.', {
		ogTitle: expectedChatOgTitle,
		ogDescription,
		ogImage,
		imageBubbleCount: shortLinkMetadata.image_bubbles.length
	});

	const ogImageResponse = await page.request.get(ogImage);
	await docAssert('share-link-og-image-is-generated-png', async () => {
		expect(ogImageResponse.ok()).toBe(true);
		expect(ogImageResponse.headers()['content-type']).toContain('image/png');
		const imageBytes = await ogImageResponse.body();
		expect(imageBytes.subarray(0, 8).toString('hex')).toBe('89504e470d0a1a0a');
		expect(imageBytes.length).toBeGreaterThan(10000);
	});
	logCheckpoint('Generated OG image URL returns PNG data large enough to include rendered preview artwork.');

	const directCrawlerUrl = new URL(`/share/chat/${activeChatId}`, page.url()).toString();
	const directCrawlerResponse = await page.request.get(directCrawlerUrl);
	const directCrawlerHtml = await directCrawlerResponse.text();
	const directOgImage = metaContent(directCrawlerHtml, 'og:image');
	await docAssert('direct-share-link-uses-generated-og-image', async () => {
		expect(directCrawlerResponse.ok()).toBe(true);
		expect(directOgImage).toContain(`/v1/share/chat/${activeChatId}/og-image.png`);
		expect(directOgImage).toContain('api.dev.openmates.org');
	});

	const directOgImageResponse = await page.request.get(directOgImage);
	await docAssert('direct-share-link-og-image-is-generated-png', async () => {
		expect(directOgImageResponse.ok()).toBe(true);
		expect(directOgImageResponse.headers()['content-type']).toContain('image/png');
		const directImageBytes = await directOgImageResponse.body();
		expect(directImageBytes.subarray(0, 8).toString('hex')).toBe('89504e470d0a1a0a');
		expect(directImageBytes.length).toBeGreaterThan(10000);
	});
	logCheckpoint('Direct shared-chat crawler metadata uses generated API-hosted PNG.', { directOgImage });

	await expect(qrCode).toBeVisible({ timeout: 5000 });
	logCheckpoint('Generated share panel shows short link and a revealable QR code.');

	// ── Step 12: Test copy link ────────────────────────────────────────────
	await copyLinkButton.click();
	// The copied state adds a .copied class
	await expect(copyLinkButton).toHaveClass(/copied/, { timeout: 5000 });
	logCheckpoint('Copy link button shows copied state.');

	// ── Step 13: Test URL reveal and expiration summary ────────────────────
	await page.getByTestId('chat-settings-share-show-url').click();
	await expect(page.locator('[data-share-url-kind="short"]')).toBeVisible({ timeout: 5000 });
	await expect(page.getByTestId('chat-settings-share-generated')).toContainText(/Auto expire in\s+never/i);
	logCheckpoint('Generated share panel reveals the primary URL and expiration summary.');

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
