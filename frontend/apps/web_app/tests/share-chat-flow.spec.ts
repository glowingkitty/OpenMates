/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Share chat flow E2E test: login, create a chat, then share it.
 *
 * Tests the full share creation flow:
 *   1. Login with existing account + 2FA
 *   2. Start a new chat with a deterministic plain chat fixture
 *   3. Wait for AI response
 *   4. Open the share panel via the chat header share button
 *   5. Generate a share link (default settings)
 *   6. Verify copy-link button, QR code, URL reveal, and long-link fallback generation
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
	getTestAccount,
	withMockMarker
} = require('./signup-flow-helpers');

const { loginToTestAccount, startNewChat, sendMessage, waitForAssistantMessage } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { docAssert } = require('./helpers/doc-checkpoint');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

async function installShortUrlFallback(page: any): Promise<void> {
	await page.addInitScript(() => {
		const browserWindow = window as typeof window & {
			__openmatesShortUrlFallbackInstalled?: boolean;
		};
		if (browserWindow.__openmatesShortUrlFallbackInstalled) return;
		const originalFetch = window.fetch.bind(window);
		browserWindow.__openmatesShortUrlFallbackInstalled = true;
		window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
			const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
			if (url.includes('/v1/share/short-url')) {
				return Promise.resolve(
					new Response(JSON.stringify({ detail: 'short link unavailable in fallback test' }), {
						status: 503,
						headers: { 'Content-Type': 'application/json' }
					})
				);
			}
			return originalFetch(input, init);
		};
	});
}

// ─── Test ────────────────────────────────────────────────────────────────────

test('creates and shares a chat link with QR code and fallback link', async ({
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
	await installShortUrlFallback(page);

	await archiveExistingScreenshots(logCheckpoint);
	logCheckpoint('Starting share chat flow test.', { email: TEST_EMAIL });

	// ── Step 1: Login ─────────────────────────────────────────────────────
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);

	// ── Step 2: Start new chat ────────────────────────────────────────────
	await startNewChat(page, logCheckpoint);

	// ── Step 3: Send a plain deterministic chat message ────────────────────
	await sendMessage(
		page,
		withMockMarker('What is the capital of France?', 'chat_flow_capital'),
		logCheckpoint,
		takeStepScreenshot,
		'share-chat'
	);

	// ── Step 4: Wait for AI response ───────────────────────────────────────
	logCheckpoint('Waiting for assistant response...');
	await waitForAssistantMessage(page, { which: 'last', logCheckpoint });
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
		await shareButton.dispatchEvent('click');
		await expect(page.getByTestId('settings-menu')).toHaveAttribute('data-active-view', /^chats\/[a-zA-Z0-9-]+\/share$/, {
			timeout: 10000
		});
	});
	logCheckpoint('Clicked chat share button.');

	await docAssert('share-link-generates-with-fallback-url', async () => {
		const generateButton = page.getByTestId('share-generate-link');
		await expect(generateButton).toBeVisible({ timeout: 10000 });
		const metadataResponsePromise = page.waitForResponse(
			(response: any) => response.url().includes('/v1/share/chat/metadata') && response.request().method() === 'POST',
			{ timeout: 90000 }
		);
		await generateButton.dispatchEvent('click');
		const metadataResponse = await metadataResponsePromise;
		expect(metadataResponse.ok()).toBe(true);
		await expect(page.getByTestId('share-short-link-section')).toBeVisible({ timeout: 90000 });
	});

	const url = (await page.getByTestId('share-short-link-url').textContent())?.trim() ?? '';
	await page.getByTestId('chat-settings-share-show-qr').dispatchEvent('click');
	await expect(page.locator('[data-testid="chat-settings-share-qr"] img')).toBeVisible({ timeout: 10000 });
	await page.getByTestId('chat-settings-share-show-url').dispatchEvent('click');
	const longUrlBox = page.locator('[data-share-url-kind="long"]');
	await expect(longUrlBox).toBeVisible({ timeout: 10000 });
	const longUrl = (await longUrlBox.textContent())?.trim() ?? '';
	const expirationText = (await page.getByTestId('chat-settings-share-generated').textContent())?.trim() ?? '';

	expect(url).toContain(`/share/chat/${activeChatId}#key=`);
	expect(longUrl).toContain(`/share/chat/${activeChatId}#key=`);
	expect(expirationText).toMatch(/Auto expire(?: in|:)\s+never/i);

	const apiUrl = process.env.PLAYWRIGHT_TEST_API_URL || 'https://api.dev.openmates.org';
	const sharedMessagesResponse = await page.request.get(`${apiUrl}/v1/share/chat/${activeChatId}/messages?limit=10`);
	expect(sharedMessagesResponse.ok()).toBe(true);
	const sharedMessages = await sharedMessagesResponse.json();
	expect(sharedMessages.messages?.length ?? 0).toBeGreaterThan(2);
	expect(sharedMessages.messages?.some((message: any) => String(message.message_id || '').startsWith('dummy-'))).toBe(false);
	logCheckpoint('Generated chat share link, QR code, and revealed URL verified in browser automation.');

	logCheckpoint('Share chat flow test completed successfully.');
});
