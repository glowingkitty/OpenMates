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

async function getVerticalCenterDistanceToViewport(page: any, locator: any): Promise<number> {
	return locator.evaluate((element: HTMLElement) => {
		const rect = element.getBoundingClientRect();
		return Math.abs(rect.top + rect.height / 2 - window.innerHeight / 2);
	});
}

async function navigateToReportIssue(page: any): Promise<void> {
	const settingsToggle = page.locator('#settings-menu-toggle');
	const settingsMenu = page.locator('[data-testid="settings-menu"].visible');
	if (await settingsMenu.isVisible().catch(() => false)) {
		await settingsToggle.click();
		await expect(settingsMenu).toHaveCount(0, { timeout: 10000 });
	}
	await settingsToggle.click();
	await expect(settingsMenu).toBeVisible({ timeout: 10000 });
	await settingsMenu
		.getByRole('menuitem', { name: /report.*issue|issue.*report|problem.*melden/i })
		.first()
		.click();
	await expect(page.getByTestId('report-issue-form')).toBeVisible({ timeout: 10000 });
}

// ─── Test ────────────────────────────────────────────────────────────────────

// contract-test: direct surface=gui.web assertions=chat-share-settings.generated-link-controls,chat-share-settings.shared-link-open
test('creates and shares a chat link with QR code and fallback link', async ({
	page,
	browser
}: {
	page: any;
	browser: any;
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

	// ── Step 3: Send a deterministic chat with a real search embed ─────────
	const sharedChatMarker = "Search on the web for 'Berlin weather'";
	await sendMessage(
		page,
		withMockMarker(sharedChatMarker, 'share_embed_flow'),
		logCheckpoint,
		takeStepScreenshot,
		'share-chat'
	);

	// ── Step 4: Wait for AI response ───────────────────────────────────────
	logCheckpoint('Waiting for assistant response...');
	await waitForAssistantMessage(page, { which: 'last', logCheckpoint });
	await expect(
		page.locator('[data-testid="embed-preview"][data-app-id="web"][data-skill-id="search"]').first()
	).toBeVisible({ timeout: 45000 });
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
		await expect(page.getByTestId('settings-menu')).toHaveAttribute('data-active-view', /^chats\/[a-zA-Z0-9-]+$/, {
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

	await expect(page.getByTestId('share-short-link-copy')).toHaveCount(0);
	await expect(page.getByTestId('share-short-link-url')).toHaveCount(0);
	await page.getByTestId('chat-settings-share-show-qr').dispatchEvent('click');
	const qrCode = page.getByTestId('chat-settings-share-qr');
	await expect(qrCode.locator('img')).toBeVisible({ timeout: 10000 });
	await expect(qrCode).toBeFocused({ timeout: 10000 });
	await expect(async () => {
		const centerDistance = await getVerticalCenterDistanceToViewport(page, qrCode);
		expect(centerDistance).toBeLessThan(160);
	}).toPass({ timeout: 10000 });
	await page.getByTestId('chat-settings-share-show-url').dispatchEvent('click');
	const longUrlBox = page.locator('[data-share-url-kind="long"]');
	await expect(longUrlBox).toBeVisible({ timeout: 10000 });
	const selectableUrl = page.getByTestId('chat-settings-share-url');
	await expect(selectableUrl).toHaveCSS('user-select', 'text');
	const longUrl = (await longUrlBox.textContent())?.trim() ?? '';
	const expirationText = (await page.getByTestId('chat-settings-share-generated').textContent())?.trim() ?? '';

	expect(longUrl).toContain(`/share/chat/${activeChatId}#key=`);
	expect(expirationText).toMatch(/Auto expire(?: in|:)\s+never/i);

	const apiUrl = process.env.PLAYWRIGHT_TEST_API_URL || 'https://api.dev.openmates.org';
	const sharedMessagesResponse = await page.request.get(`${apiUrl}/v1/share/chat/${activeChatId}/messages?limit=10`);
	expect(sharedMessagesResponse.ok()).toBe(true);
	const sharedMessages = await sharedMessagesResponse.json();
	expect(sharedMessages.messages?.length ?? 0).toBeGreaterThan(0);
	expect(sharedMessages.messages?.some((message: any) => String(message.message_id || '').startsWith('dummy-'))).toBe(false);
	logCheckpoint('Generated chat share link, QR code, and revealed URL verified in browser automation.');

	// ── Step 6: Generate a report-context link from the Report Issue form ──
	// Storage and worker delivery are covered by report-issue-flow.spec.ts in
	// the isolated object-storage profile. This AI-fixture profile keeps the
	// report endpoint local to the browser so it can prove that the exact link
	// produced by the report form decrypts both messages and embeds.
	const reportPayloads: Array<Record<string, unknown>> = [];
	await page.route('**/v1/settings/issues', async (route: any) => {
		if (route.request().method() !== 'POST') {
			await route.continue();
			return;
		}
		reportPayloads.push(route.request().postDataJSON());
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({
				success: true,
				message: 'Issue report submitted successfully',
				issue_id: '00000000-0000-4000-8000-000000000001',
				short_issue_id: 'ABCDE',
				screenshot_uploaded: false,
			}),
		});
	});
	await navigateToReportIssue(page);
	await expect(page.locator('#share-chat-toggle')).toBeChecked();
	await page.getByTestId('report-issue-title').fill('Shared chat decryption verification');
	await page.evaluate((marker: string) => {
		console.warn(
			'[ReportIssueRedactionProbe]',
			marker,
			'https://app.example/share/chat/example#key=secret-report-share-key-material',
		);
	}, sharedChatMarker);
	const reportMetadataResponsePromise = page.waitForResponse(
		(response: any) =>
			response.url().includes('/v1/share/chat/metadata') &&
			response.request().method() === 'POST',
		{ timeout: 30000 }
	);
	await page.getByTestId('report-issue-submit').click();
	const reportMetadataResponse = await reportMetadataResponsePromise;
	expect(reportMetadataResponse.ok()).toBe(true);
	await expect(page.getByTestId('report-issue-confirmation')).toBeVisible({ timeout: 10000 });
	expect(reportPayloads).toHaveLength(1);
	const reportPayload = reportPayloads[0];
	const reportShareUrl = String(reportPayload.chat_or_embed_url ?? '');
	expect(reportShareUrl).toContain(`/share/chat/${activeChatId}#key=`);
	expect(String(reportPayload.last_messages_html ?? '')).toContain(sharedChatMarker);
	expect(String(reportPayload.console_logs ?? '')).not.toContain(sharedChatMarker);
	expect(String(reportPayload.console_logs ?? '')).not.toContain('secret-report-share-key-material');
	expect(String(reportPayload.console_logs ?? '')).toContain('[CHAT-CONTENT-REDACTED]');
	expect(String(reportPayload.console_logs ?? '')).toContain('[SHARE-KEY-REDACTED]');

	const viewerContext = await browser.newContext();
	try {
		const viewerPage = await viewerContext.newPage();
		await viewerPage.goto(reportShareUrl, { waitUntil: 'domcontentloaded' });
		await expect(viewerPage).toHaveURL(new RegExp(`#chat-id=${activeChatId}(?:&|$)`), {
			timeout: 45000,
		});
		await expect(
			viewerPage.getByTestId('message-user').filter({ hasText: sharedChatMarker }),
		).toBeVisible({ timeout: 45000 });
		await expect(viewerPage.getByText('[Content decryption failed]')).toHaveCount(0);
		await expect(
			viewerPage.locator('[data-testid="embed-preview"][data-app-id="web"][data-skill-id="search"]').first(),
		).toBeVisible({ timeout: 45000 });
		await expect(viewerPage.getByTestId('embed-error-banner')).toHaveCount(0);
		logCheckpoint('Report-generated share link decrypted messages and embeds in a fresh browser.');
	} finally {
		await viewerContext.close();
	}

	// ── Step 7: Explicit opt-out omits every plaintext/chat-link field ────
	await page.getByTestId('report-issue-submit-another').click();
	const shareChatToggle = page.locator('#share-chat-toggle');
	await expect(shareChatToggle).toBeChecked();
	await shareChatToggle.uncheck();
	await expect(shareChatToggle).not.toBeChecked();
	await page.getByTestId('report-issue-title').fill('Report without shared chat context');
	await page.getByTestId('report-issue-submit').click();
	await expect(page.getByTestId('report-issue-confirmation')).toBeVisible({ timeout: 10000 });
	expect(reportPayloads).toHaveLength(2);
	expect(reportPayloads[1].chat_or_embed_url).toBeNull();
	expect(reportPayloads[1].last_messages_html).toBeNull();
	logCheckpoint('Report opt-out omitted both the shared URL and rendered message HTML.');

	logCheckpoint('Share chat flow test completed successfully.');
});
