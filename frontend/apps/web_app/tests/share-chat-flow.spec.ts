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
const { waitForEmbedFinished } = require('./helpers/embed-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { docAssert } = require('./helpers/doc-checkpoint');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const SHARE_AUTOMATION_RESULT_PREFIX = '[SHARE_CHAT_AUTOMATION_RESULT]';

type ShareAutomationResult = {
	status: 'passed' | 'failed';
	chatId: string;
	url: string;
	longUrl: string;
	expirationText: string;
	hasQr: boolean;
	error?: string;
};

async function installShortUrlFallback(page: any): Promise<void> {
	await page.addInitScript((resultPrefix: string) => {
		const browserWindow = window as typeof window & {
			__openmatesShortUrlFallbackInstalled?: boolean;
			__openmatesShareAutomationInstalled?: boolean;
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

		if (browserWindow.__openmatesShareAutomationInstalled) return;
		browserWindow.__openmatesShareAutomationInstalled = true;
		const automationState = {
			generateClicked: false,
			qrClicked: false,
			urlClicked: false,
			reported: false,
			startedAt: 0
		};
		const report = (result: ShareAutomationResult) => {
			if (automationState.reported) return;
			automationState.reported = true;
			console.info(`${resultPrefix}${JSON.stringify(result)}`);
		};
		const clickIfReady = (selector: string): boolean => {
			const button = document.querySelector<HTMLButtonElement>(selector);
			if (!button || button.disabled) return false;
			button.click();
			return true;
		};
		const driveSharePanel = () => {
			if (automationState.reported) return;
			const generatedSection = document.querySelector('[data-testid="share-short-link-section"]');
			if (!automationState.generateClicked && !generatedSection) {
				if (clickIfReady('[data-testid="share-generate-link"]')) {
					automationState.generateClicked = true;
					automationState.startedAt = Date.now();
				}
			}
			if (automationState.generateClicked && !generatedSection && Date.now() - automationState.startedAt > 60000) {
				report({
					status: 'failed',
					chatId: new URLSearchParams(window.location.hash.replace(/^#/, '')).get('chat-id') ?? '',
					url: '',
					longUrl: '',
					expirationText: '',
					hasQr: false,
					error: 'Share generation did not complete within 60 seconds.'
				});
			}
			if (!generatedSection) return;
			if (!automationState.qrClicked && !document.querySelector('[data-testid="chat-settings-share-qr"]')) {
				automationState.qrClicked = clickIfReady('[data-testid="chat-settings-share-show-qr"]');
			}
			if (!automationState.urlClicked && !document.querySelector('[data-share-url-kind="long"]')) {
				automationState.urlClicked = clickIfReady('[data-testid="chat-settings-share-show-url"]');
			}
			const url = document.querySelector('[data-testid="share-short-link-url"]')?.textContent?.trim() ?? '';
			const longUrl = document.querySelector('[data-share-url-kind="long"]')?.textContent?.trim() ?? '';
			const expirationText = document.querySelector('[data-testid="chat-settings-share-generated"]')?.textContent?.trim() ?? '';
			const hasQr = Boolean(document.querySelector('[data-testid="chat-settings-share-qr"] img'));
			const chatId = window.location.hash.match(/chat-id=([a-zA-Z0-9-]+)/)?.[1] ?? '';
			if (url && longUrl && hasQr && /Auto expire in\s+never/i.test(expirationText)) {
				report({ status: 'passed', chatId, url, longUrl, expirationText, hasQr });
			}
		};
		const observeWhenReady = () => {
			if (!document.documentElement) {
				window.requestAnimationFrame(observeWhenReady);
				return;
			}
			new MutationObserver(driveSharePanel).observe(document.documentElement, {
				attributes: true,
				childList: true,
				subtree: true
			});
		};
		observeWhenReady();
		window.setInterval(driveSharePanel, 250);
	}, SHARE_AUTOMATION_RESULT_PREFIX);
}

function waitForShareAutomationResult(page: any, expectedChatId: string): Promise<ShareAutomationResult> {
	return new Promise((resolve, reject) => {
		const timeout = setTimeout(() => {
			page.off('console', handleConsoleMessage);
			reject(new Error('Timed out waiting for chat share automation result.'));
		}, 90000);
		const handleConsoleMessage = (msg: any) => {
			const text = msg.text();
			if (!text.startsWith(SHARE_AUTOMATION_RESULT_PREFIX)) return;
			clearTimeout(timeout);
			page.off('console', handleConsoleMessage);
			const result = JSON.parse(text.slice(SHARE_AUTOMATION_RESULT_PREFIX.length)) as ShareAutomationResult;
			if (result.status !== 'passed') {
				reject(new Error(result.error ?? 'Chat share automation failed.'));
				return;
			}
			if (result.chatId !== expectedChatId) {
				reject(new Error(`Share automation used chat ${result.chatId}, expected ${expectedChatId}.`));
				return;
			}
			resolve(result);
		};
		page.on('console', handleConsoleMessage);
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
	const shareAutomationResult = waitForShareAutomationResult(page, activeChatId);

	// ── Step 5: Click share button in chat header ─────────────────────────
	const shareButton = page.locator('[data-testid="chat-share-button"]');
	await docAssert('share-panel-opens-from-chat-header', async () => {
		await expect(shareButton).toBeVisible({ timeout: 10000 });
		await shareButton.click({ timeout: 10000 });
		await expect(page.getByTestId('settings-menu')).toHaveAttribute('data-active-view', /^chats\/[a-zA-Z0-9-]+\/share$/, {
			timeout: 10000
		});
	});
	logCheckpoint('Clicked chat share button.');

	const result = await shareAutomationResult;
	expect(result.url).toContain(`/share/chat/${activeChatId}#key=`);
	expect(result.longUrl).toContain(`/share/chat/${activeChatId}#key=`);
	expect(result.hasQr).toBe(true);
	expect(result.expirationText).toMatch(/Auto expire in\s+never/i);
	logCheckpoint('Generated chat share link, QR code, and revealed URL verified in browser automation.');

	logCheckpoint('Share chat flow test completed successfully.');
});
