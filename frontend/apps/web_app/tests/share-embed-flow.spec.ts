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

	const emailInput = page.locator('input[name="username"][type="email"]');
	await expect(emailInput).toBeVisible();
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

	const passwordInput = page.locator('input[type="password"]');
	await expect(passwordInput).toBeVisible({ timeout: 15000 });
	await passwordInput.fill(TEST_PASSWORD);

	const otpInput = page.locator('input[autocomplete="one-time-code"]');
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
			const menuToggle = page.locator('.icon_menu');
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
