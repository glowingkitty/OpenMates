/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const consoleLogs: string[] = [];
const networkActivities: string[] = [];

test.beforeEach(async () => {
	consoleLogs.length = 0;
	networkActivities.length = 0;
});

test.afterEach(async ({ page }: { page: any }, testInfo: any) => {
	if (testInfo.status !== 'passed') {
		console.log('\n--- DEBUG INFO ON FAILURE ---');
		console.log('\n[RECENT CONSOLE LOGS]');
		consoleLogs.slice(-30).forEach((log) => console.log(log));

		console.log('\n[RECENT NETWORK ACTIVITIES]');
		networkActivities.slice(-30).forEach((activity) => console.log(activity));
		console.log('\n--- END DEBUG INFO ---\n');
	}

	// Always attempt to delete the active chat after every test (including failures),
	// so that test account chats don't accumulate between runs.
	// deleteActiveChat is best-effort and will not throw on any cleanup error.
	if (page) {
		const noop = () => {};
		const noopScreenshot = async () => {};
		await deleteActiveChat(page, noop, noopScreenshot, 'afterEach-cleanup').catch(noop);
	}
});

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

const { loginToTestAccount, startNewChat, sendMessage, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

/**
 * Focus mode UI checks after activation: ONE login, ONE AI call to activate
 * focus mode, then ALL UI assertions run sequentially within a single test.
 *
 * Combines: banner, context menu indicator, badge, follow-up persistence,
 * details link, and stop button — in that order (stop is last since it
 * deactivates focus mode).
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL: Email of an existing test account.
 * - OPENMATES_TEST_ACCOUNT_PASSWORD: Password for the test account.
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY: 2FA OTP secret (base32) for the test account.
 * - PLAYWRIGHT_TEST_BASE_URL: Base URL for the deployed web app under test.
 */

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

// ---------------------------------------------------------------------------
// Selectors
// ---------------------------------------------------------------------------
const SELECTORS = {
	focusModeBar: '[data-testid="focus-mode-bar"][data-app-id="jobs"]',
	focusModeBarActivated: '[data-testid="focus-mode-bar"].activated[data-app-id="jobs"]',
	focusModeBarCounting: '[data-testid="focus-mode-bar"].counting[data-app-id="jobs"]',
	statusLabel: '[data-testid="focus-status-label"]',
	statusValue: '[data-testid="focus-status-value"]',
	statusValueActive: '[data-testid="focus-status-value"].active-status',
	progressBar: '[data-testid="focus-progress-bar"]',
	rejectHint: '[data-testid="focus-reject-hint"]',
	contextMenuFocusIndicator: '[data-testid="focus-mode-indicator"]',
	contextMenuFocusLabel: '[data-testid="focus-mode-label"]',
	focusActiveBanner: '[data-testid="focus-pill"]',
	focusActiveBannerText: '[data-testid="focus-pill"] [data-testid="focus-pill-label"]',
	focusModeBadge: '[data-testid="focus-mode-badge"]',
	mentionDropdown: '[data-testid="mention-dropdown"]',
	mentionDropdownFocusItem: '[data-testid="mention-result"][role="option"]',
	contextMenuStop: '[data-testid="focus-context-stop"]',
	contextMenuDetails: '[data-testid="focus-context-details"]',
	focusModeContextMenu: '[data-testid="focus-mode-context-menu"]',
	focusModeDetailsBullets: '[data-testid="focus-process-bullet"]',
	focusModeDetailsShowFull: '[data-testid="focus-instructions-toggle"]'
};

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

async function ensureSidebarOpen(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void
): Promise<void> {
	const sidebar = page.getByTestId('activity-history-wrapper');
	if (await sidebar.isVisible({ timeout: 1000 }).catch(() => false)) {
		logCheckpoint('Sidebar already open.');
		return;
	}

	const menuButton = page.locator('[data-testid="sidebar-toggle"]');
	if (await menuButton.isVisible({ timeout: 2000 }).catch(() => false)) {
		await menuButton.click();
		logCheckpoint('Clicked hamburger menu to open sidebar.');
		await page.waitForTimeout(500);
	} else {
		logCheckpoint(
			'Hamburger menu button not visible (sidebar may already be open or layout is wide).'
		);
	}
}

async function waitForFocusModeEmbed(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void,
	takeStepScreenshot: (page: any, label: string) => Promise<void>,
	stepLabel: string
): Promise<any> {
	logCheckpoint('Waiting for focus mode activation embed to appear...');

	const focusModeEmbed = page.locator(SELECTORS.focusModeBar);
	await expect(focusModeEmbed.first()).toBeVisible({ timeout: 60000 });
	logCheckpoint('Focus mode activation embed is visible!');
	await takeStepScreenshot(page, `${stepLabel}-embed-visible`);

	const focusId = await focusModeEmbed.first().getAttribute('data-focus-id');
	logCheckpoint(`Focus mode ID: "${focusId}"`);
	expect(focusId).toContain('career_insights');

	return focusModeEmbed;
}

function setupPageListeners(page: any): void {
	page.on('console', (msg: any) => {
		const timestamp = new Date().toISOString();
		consoleLogs.push(`[${timestamp}] [${msg.type()}] ${msg.text()}`);
	});
	page.on('request', (request: any) => {
		const timestamp = new Date().toISOString();
		networkActivities.push(`[${timestamp}] >> ${request.method()} ${request.url()}`);
	});
	page.on('response', (response: any) => {
		const timestamp = new Date().toISOString();
		networkActivities.push(`[${timestamp}] << ${response.status()} ${response.url()}`);
	});
}

// ---------------------------------------------------------------------------
// Combined UI test: ONE activation, then all UI checks sequentially
// ---------------------------------------------------------------------------

test('focus mode UI elements work correctly after activation', async ({
	page
}: {
	page: any;
}) => {
	setupPageListeners(page);

	test.slow();
	// Combined flow: activation + banner + context menu + badge + follow-up + details + stop
	test.setTimeout(240000);

	const logCheckpoint = createSignupLogger('FOCUS_UI_COMBINED');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'focus-ui-combined'
	});

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	await archiveExistingScreenshots(logCheckpoint);
	logCheckpoint('Starting combined focus mode UI test.');

	// ======================================================================
	// SETUP: Login, start chat, activate focus mode (done ONCE)
	// ======================================================================
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	await startNewChat(page, logCheckpoint);

	const careerMessage =
		"I've been stuck in my career for years and need help deciding what to do next professionally. Can you help me?";

	await sendMessage(page, withMockMarker(careerMessage, 'focus_career_6'), logCheckpoint, takeStepScreenshot, 'ui-career');

	logCheckpoint('Waiting for assistant response...');
	await expect(page.getByTestId('message-assistant').first()).toBeVisible({ timeout: 45000 });

	await waitForFocusModeEmbed(page, logCheckpoint, takeStepScreenshot, 'ui-focus');

	logCheckpoint('Waiting for focus mode to activate (countdown)...');
	const activatedEmbed = page.locator(SELECTORS.focusModeBarActivated);
	await expect(activatedEmbed.first()).toBeVisible({ timeout: 15000 });
	logCheckpoint('Focus mode has been activated!');

	// Wait for AI streaming to fully complete
	logCheckpoint('Waiting for AI streaming to complete (send button enabled)...');
	await expect(page.locator('[data-action="send-message"]')).toBeEnabled({ timeout: 45000 });
	logCheckpoint('Streaming complete — send button is enabled again.');

	// Wait for sync to propagate encrypted_active_focus_id to IndexedDB
	await page.waitForTimeout(3000);

	// ======================================================================
	// CHECK 1: Banner visible (test 5)
	// ======================================================================
	await test.step('Focus active banner is visible', async () => {
		logCheckpoint('Checking for focus active banner...');
		const banner = page.locator(SELECTORS.focusActiveBanner);
		await expect(banner).toBeVisible({ timeout: 10000 });
		logCheckpoint('Focus active banner is visible!');

		const bannerText = page.locator(SELECTORS.focusActiveBannerText);
		await expect(bannerText).toBeVisible({ timeout: 5000 });
		const bannerTextContent = await bannerText.textContent();
		logCheckpoint(`Banner text: "${bannerTextContent}"`);
		expect(bannerTextContent?.toLowerCase()).toContain('focus');

		await takeStepScreenshot(page, 'ui-banner-visible');
	});

	// ======================================================================
	// CHECK 2: Context menu indicator (test 3)
	// ======================================================================
	await test.step('Context menu shows focus mode indicator', async () => {
		logCheckpoint('Opening sidebar to find active chat...');
		await ensureSidebarOpen(page, logCheckpoint);

		const activeChatItem = page.locator('[data-testid="chat-item-wrapper"].active');
		await expect(activeChatItem).toBeVisible({ timeout: 5000 });
		logCheckpoint('Active chat item visible in sidebar.');

		logCheckpoint('Checking for focus mode indicator in context menu (with retries)...');
		let foundFocusIndicator = false;
		for (let attempt = 1; attempt <= 3 && !foundFocusIndicator; attempt++) {
			logCheckpoint(`Context menu attempt ${attempt}/3...`);

			await activeChatItem.click({ button: 'right' });
			await page.waitForTimeout(500);

			const focusIndicator = page.locator(SELECTORS.contextMenuFocusIndicator);
			if (await focusIndicator.isVisible({ timeout: 5000 }).catch(() => false)) {
				foundFocusIndicator = true;
				logCheckpoint('Focus mode indicator is visible in context menu!');
				await takeStepScreenshot(page, 'ui-ctx-menu-indicator');

				const focusLabel = page.locator(SELECTORS.contextMenuFocusLabel);
				if (await focusLabel.isVisible({ timeout: 2000 }).catch(() => false)) {
					const labelText = await focusLabel.textContent();
					logCheckpoint(`Focus mode label in context menu: "${labelText}"`);
					expect(labelText?.toLowerCase()).toContain('career');
				}

				await page.keyboard.press('Escape');
				await page.waitForTimeout(300);
			} else {
				logCheckpoint(
					`Focus indicator not visible on attempt ${attempt}. Closing menu and waiting for sync...`
				);
				await page.keyboard.press('Escape');
				await page.waitForTimeout(2000);
			}
		}

		expect(foundFocusIndicator).toBeTruthy();
	});

	// ======================================================================
	// CHECK 3: Badge in sidebar (test 9)
	// ======================================================================
	await test.step('Chat entry shows focus mode badge', async () => {
		logCheckpoint('Looking for focus mode badge on active chat entry...');
		await ensureSidebarOpen(page, logCheckpoint);

		const activeChatItem = page.locator('[data-testid="chat-item-wrapper"].active');
		await expect(activeChatItem).toBeVisible({ timeout: 5000 });

		const focusBadge = activeChatItem.locator(SELECTORS.focusModeBadge);
		let badgeVisible = await focusBadge.isVisible({ timeout: 5000 }).catch(() => false);
		logCheckpoint(`Focus mode badge visible on active chat item: ${badgeVisible}`);

		if (!badgeVisible) {
			logCheckpoint('Badge not visible on first check — waiting 3 more seconds...');
			await page.waitForTimeout(3000);
			badgeVisible = await focusBadge.isVisible({ timeout: 5000 }).catch(() => false);
			logCheckpoint(`Focus mode badge visible after retry: ${badgeVisible}`);
		}

		expect(badgeVisible).toBeTruthy();
		await takeStepScreenshot(page, 'ui-badge-visible');
	});

	// ======================================================================
	// CHECK 4: Follow-up persistence (test 4)
	// ======================================================================
	await test.step('Focus mode persists on follow-up messages', async () => {
		const allAssistantMessagesBefore = page.getByTestId('message-assistant');
		const countBefore = await allAssistantMessagesBefore.count();
		logCheckpoint(`Assistant messages before follow-up: ${countBefore}`);

		const followUpMessage =
			"I'm particularly interested in transitioning to a product management role. " +
			'What skills do I need and how should I prepare?';

		await sendMessage(page, withMockMarker(followUpMessage, 'focus_career_5'), logCheckpoint, takeStepScreenshot, 'ui-followup');

		logCheckpoint('Waiting for follow-up assistant response...');
		await expect(async () => {
			const allAssistantMessagesAfter = page.getByTestId('message-assistant');
			const countAfter = await allAssistantMessagesAfter.count();
			logCheckpoint(`Assistant messages after follow-up: ${countAfter} (was ${countBefore})`);
			expect(countAfter).toBeGreaterThan(countBefore);
		}).toPass({ timeout: 60000 });

		logCheckpoint('Follow-up assistant response received.');

		// Verify follow-up response contains career content
		await expect(async () => {
			const allAssistantMessages = page.getByTestId('message-assistant');
			const lastMessage = allAssistantMessages.last();
			const text = await lastMessage.textContent();
			const lowerText = text?.toLowerCase() ?? '';
			logCheckpoint(`Follow-up response text length: ${text?.length ?? 0}`);
			const hasRelevantContent =
				lowerText.includes('product') ||
				lowerText.includes('management') ||
				lowerText.includes('career') ||
				lowerText.includes('transition') ||
				lowerText.includes('skill') ||
				lowerText.includes('role');
			expect(hasRelevantContent).toBeTruthy();
		}).toPass({ timeout: 30000 });

		logCheckpoint('Follow-up response contains career-focused content.');

		// Verify original embed persists
		const originalEmbed = page.locator(SELECTORS.focusModeBarActivated);
		await expect(originalEmbed.first()).toBeVisible({ timeout: 10000 });
		logCheckpoint('Original focus mode embed persists after follow-up.');

		const originalFocusId = await originalEmbed.first().getAttribute('data-focus-id');
		expect(originalFocusId).toContain('career_insights');

		// Wait for streaming to complete before next steps
		await expect(page.locator('[data-action="send-message"]')).toBeEnabled({ timeout: 45000 });
		await takeStepScreenshot(page, 'ui-followup-verified');
	});

	// ======================================================================
	// CHECK 5: Details link (test 8)
	// ======================================================================
	await test.step('Details link opens focus mode settings page', async () => {
		logCheckpoint('Clicking activated embed to open context menu...');
		const activatedEmbedNow = page.locator(SELECTORS.focusModeBarActivated);
		await activatedEmbedNow.first().click();
		await page.waitForTimeout(500);
		await takeStepScreenshot(page, 'ui-details-context-menu');

		const detailsButton = page.locator(SELECTORS.contextMenuDetails);
		await expect(detailsButton).toBeVisible({ timeout: 5000 });
		await detailsButton.click();
		logCheckpoint('Clicked Details link in context menu.');
		await page.waitForTimeout(1000);
		await takeStepScreenshot(page, 'ui-details-settings-opened');

		// Verify focus mode details page content
		const focusModeHeading = page.locator('[data-testid="focus-mode-details"] h1, [data-testid="focus-mode-header"] h1');
		const headingVisible = await focusModeHeading.isVisible({ timeout: 8000 }).catch(() => false);

		if (headingVisible) {
			const headingText = await focusModeHeading.textContent();
			logCheckpoint(`Focus mode details heading: "${headingText}"`);
			expect(headingText?.toLowerCase()).toContain('career');

			const bullets = page.locator(SELECTORS.focusModeDetailsBullets);
			const bulletCount = await bullets.count();
			logCheckpoint(`Process bullet count: ${bulletCount}`);
			expect(bulletCount).toBeGreaterThan(0);

			const showFullButton = page.locator(SELECTORS.focusModeDetailsShowFull);
			const showFullVisible = await showFullButton.isVisible({ timeout: 3000 }).catch(() => false);
			logCheckpoint(`Show full instruction button visible: ${showFullVisible}`);
			expect(showFullVisible).toBeTruthy();

			await takeStepScreenshot(page, 'ui-details-page-verified');
		} else {
			const settingsContent = page.locator('[data-testid="settings-menu"], [data-testid="settings-panel"]');
			const isAnySettingsOpen = await settingsContent
				.first()
				.isVisible({ timeout: 5000 })
				.catch(() => false);
			logCheckpoint(`Settings panel visible (fallback check): ${isAnySettingsOpen}`);
			expect(isAnySettingsOpen).toBeTruthy();
		}

		// Close settings
		await page.keyboard.press('Escape');
		await page.waitForTimeout(500);
	});

	// ======================================================================
	// CHECK 6: Stop button deactivates focus mode (test 7) — MUST BE LAST
	// ======================================================================
	await test.step('Stop button deactivates focus mode', async () => {
		logCheckpoint('Clicking activated embed to open context menu for Stop...');
		const activatedEmbedNow = page.locator(SELECTORS.focusModeBarActivated);
		await activatedEmbedNow.first().click();
		await page.waitForTimeout(500);
		await takeStepScreenshot(page, 'ui-stop-context-menu');

		const contextMenu = page.locator(SELECTORS.focusModeContextMenu);
		const isContextMenuVisible = await contextMenu.isVisible({ timeout: 3000 }).catch(() => false);
		logCheckpoint(`Context menu visible: ${isContextMenuVisible}`);

		const stopButton = page.locator(SELECTORS.contextMenuStop);
		await expect(stopButton).toBeVisible({ timeout: 5000 });
		const stopButtonText = await stopButton.textContent();
		logCheckpoint(`Stop button text: "${stopButtonText}"`);

		await stopButton.click();
		logCheckpoint('Clicked Stop button.');
		await takeStepScreenshot(page, 'ui-stop-clicked');

		// Context menu should close
		await expect(page.locator(SELECTORS.focusModeContextMenu)).not.toBeVisible({ timeout: 3000 });
		logCheckpoint('Context menu closed after Stop.');

		// Banner should disappear
		const banner = page.locator(SELECTORS.focusActiveBanner);
		await expect(banner).not.toBeVisible({ timeout: 8000 });
		logCheckpoint('Focus active banner is hidden after Stop — deactivation verified.');

		// Check for stop system message (best-effort)
		logCheckpoint('Checking for stopped system message (best-effort)...');
		const systemMessages = page.getByTestId('system-message-text');
		const systemCount = await systemMessages.count();
		let foundStopMessage = false;
		for (let i = 0; i < systemCount && !foundStopMessage; i++) {
			const text = (await systemMessages.nth(i).textContent()) ?? '';
			if (text.toLowerCase().includes('stopped') && text.toLowerCase().includes('focus')) {
				foundStopMessage = true;
				logCheckpoint(`Found stop system message: "${text.trim()}"`);
			}
		}
		if (foundStopMessage) {
			logCheckpoint('Stop system message verified.');
		} else {
			logCheckpoint(
				'Stop system message not found — non-fatal (system message may use different element).'
			);
		}
		await takeStepScreenshot(page, 'ui-stop-final-state');
	});

	// ======================================================================
	// CLEANUP
	// ======================================================================
	await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'ui-combined-cleanup');
	logCheckpoint('Combined focus mode UI test completed successfully.');
});
