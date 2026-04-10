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
 * Focus mode activation test (happy path): Verify the "Career insights" focus mode
 * from the Jobs app activates when the user expresses career frustration.
 *
 * Send message -> focus mode embed appears -> countdown -> activates -> AI responds
 * with career content -> embed persists after continuation response.
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL: Email of an existing test account.
 * - OPENMATES_TEST_ACCOUNT_PASSWORD: Password for the test account.
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY: 2FA OTP secret (base32) for the test account.
 * - PLAYWRIGHT_TEST_BASE_URL: Base URL for the deployed web app under test.
 */

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

// ---------------------------------------------------------------------------
// Selectors: Based on FocusModeActivationEmbed.svelte CSS classes
// The Svelte component uses 'focus-mode-bar' as the main class.
// The renderer sets data-embed-type, data-focus-id, data-app-id on the container.
// ---------------------------------------------------------------------------
const SELECTORS = {
	/** Focus mode bar (inner Svelte component) with app-specific filter */
	focusModeBar: '[data-testid="focus-mode-bar"][data-app-id="jobs"]',
	/** Focus mode bar in activated state */
	focusModeBarActivated: '[data-testid="focus-mode-bar"].activated[data-app-id="jobs"]',
	/** Focus mode bar during countdown (not yet activated) */
	focusModeBarCounting: '[data-testid="focus-mode-bar"].counting[data-app-id="jobs"]',
	/** Status label (focus mode display name) */
	statusLabel: '[data-testid="focus-status-label"]',
	/** Status value (countdown text or "Focus activated") */
	statusValue: '[data-testid="focus-status-value"]',
	/** Status value in activated state */
	statusValueActive: '[data-testid="focus-status-value"].active-status',
	/** Progress bar container (visible during countdown only) */
	progressBar: '[data-testid="focus-progress-bar"]',
	/** Reject hint text below the bar (visible during countdown only) */
	rejectHint: '[data-testid="focus-reject-hint"]',
	/** Chat context menu focus mode indicator */
	contextMenuFocusIndicator: '[data-testid="focus-mode-indicator"]',
	contextMenuFocusLabel: '[data-testid="focus-mode-label"]',
	// -----------------------------------------------------------------------
	// New selectors for additional requirements
	// -----------------------------------------------------------------------
	/** Focus pill shown above message input when focus mode is active */
	focusActiveBanner: '[data-testid="focus-pill"]',
	/** Label text inside the focus pill */
	focusActiveBannerText: '[data-testid="focus-pill"] [data-testid="focus-pill-label"]',
	/** Focus mode badge on Chat.svelte entry (bottom-right of category circle) */
	focusModeBadge: '[data-testid="focus-mode-badge"]',
	/** Mention dropdown shown when user types @ in the message editor */
	mentionDropdown: '[data-testid="mention-dropdown"]',
	/** Focus mode items inside the mention dropdown */
	mentionDropdownFocusItem: '[data-testid="mention-result"][role="option"]',
	/** Context menu Stop button (shown after focus mode is activated) */
	contextMenuStop: '[data-testid="focus-context-stop"]',
	/** Context menu Details link (deep-links to focus mode settings page) */
	contextMenuDetails: '[data-testid="focus-context-details"]',
	/** FocusModeContextMenu container */
	focusModeContextMenu: '[data-testid="focus-mode-context-menu"]',
	/** Focus mode details settings page process/summary bullets */
	focusModeDetailsBullets: '[data-testid="focus-process-bullet"]',
	/** Focus mode details page show-full-instruction toggle button */
	focusModeDetailsShowFull: '[data-testid="focus-instructions-toggle"]'
};

// ---------------------------------------------------------------------------
// Shared helpers (same pattern as web-search-flow.spec.ts)
// ---------------------------------------------------------------------------

/**
 * Open the sidebar (activity history panel) if it's not already visible.
 * The toggle button is `button.icon_menu` inside `.menu-button-container`.
 * It's hidden when the sidebar is already open (class:hidden applied).
 */
async function ensureSidebarOpen(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void
): Promise<void> {
	// Check if sidebar is already open by looking for the activity history wrapper
	const sidebar = page.getByTestId('activity-history-wrapper');
	if (await sidebar.isVisible({ timeout: 1000 }).catch(() => false)) {
		logCheckpoint('Sidebar already open.');
		return;
	}

	// Try clicking the hamburger menu button to open the sidebar
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

/**
 * Wait for the focus mode activation embed to appear and return the locator.
 */
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

	// Verify the focus mode ID contains "career_insights"
	const focusId = await focusModeEmbed.first().getAttribute('data-focus-id');
	logCheckpoint(`Focus mode ID: "${focusId}"`);
	expect(focusId).toContain('career_insights');

	return focusModeEmbed;
}

/**
 * Helper to set up console/network logging on a page.
 */
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
// Test 1: Career insights focus mode activation (happy path)
// ---------------------------------------------------------------------------

test('career frustration message triggers Career insights focus mode', async ({
	page
}: {
	page: any;
}) => {
	setupPageListeners(page);

	test.slow();
	// Focus mode activation involves AI preprocessing + main processing + streaming + cleanup.
	test.setTimeout(180000);

	const logCheckpoint = createSignupLogger('FOCUS_MODE_CAREER');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'focus-mode-career'
	});

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	await archiveExistingScreenshots(logCheckpoint);
	logCheckpoint('Starting career insights focus mode test.', { email: TEST_EMAIL });

	// ======================================================================
	// STEP 1: Login and start a new chat
	// ======================================================================
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	await startNewChat(page, logCheckpoint);

	// ======================================================================
	// STEP 2: Send a message expressing career frustration
	// ======================================================================
	const careerMessage =
		"I've been feeling really frustrated and stuck in my current job for the past year. " +
		"I don't feel like I'm growing anymore and I'm not sure what direction to take my career. " +
		'Can you help me figure out what I should do next?';

	await sendMessage(page, withMockMarker(careerMessage, 'focus_career_1'), logCheckpoint, takeStepScreenshot, 'career-advice');

	// ======================================================================
	// STEP 3: Wait for assistant response
	// ======================================================================
	logCheckpoint('Waiting for assistant response...');
	const assistantMessage = page.getByTestId('message-assistant');
	await expect(assistantMessage.first()).toBeVisible({ timeout: 45000 });
	logCheckpoint('Assistant response wrapper is visible.');

	// ======================================================================
	// STEP 4: Check for focus mode activation embed
	// ======================================================================
	const focusModeEmbed = await waitForFocusModeEmbed(
		page,
		logCheckpoint,
		takeStepScreenshot,
		'focus-mode'
	);

	// ======================================================================
	// STEP 5: Verify focus mode card content
	// ======================================================================
	const focusName = focusModeEmbed.first().locator(SELECTORS.statusLabel);
	await expect(focusName).toBeVisible({ timeout: 5000 });
	const focusNameText = await focusName.textContent();
	logCheckpoint(`Focus mode name displayed: "${focusNameText}"`);
	expect(focusNameText?.toLowerCase()).toContain('career');

	const focusStatus = focusModeEmbed.first().locator(SELECTORS.statusValue);
	await expect(focusStatus).toBeVisible({ timeout: 5000 });
	const statusText = await focusStatus.textContent();
	logCheckpoint(`Focus mode status text: "${statusText}"`);

	await takeStepScreenshot(page, 'focus-mode-card-verified');

	// ======================================================================
	// STEP 6: Wait for focus mode to activate (4-second countdown)
	// ======================================================================
	logCheckpoint('Waiting for focus mode to activate (4-second countdown)...');

	const activatedEmbed = page.locator(SELECTORS.focusModeBarActivated);
	await expect(activatedEmbed.first()).toBeVisible({ timeout: 15000 });
	logCheckpoint('Focus mode has been activated!');

	// Verify the activated status text
	const activatedStatus = activatedEmbed.first().locator(SELECTORS.statusValueActive);
	await expect(activatedStatus).toBeVisible({ timeout: 5000 });
	const activatedStatusText = await activatedStatus.textContent();
	logCheckpoint(`Activated status text: "${activatedStatusText}"`);
	expect(activatedStatusText?.toLowerCase()).toContain('activat');

	// Progress bar should be hidden after activation
	const progressBar = activatedEmbed.first().locator(SELECTORS.progressBar);
	await expect(progressBar).not.toBeVisible({ timeout: 5000 });
	logCheckpoint('Progress bar is hidden after activation.');

	// Reject hint should be hidden after activation
	const rejectHint = page.locator(SELECTORS.rejectHint);
	await expect(rejectHint).not.toBeVisible({ timeout: 5000 });
	logCheckpoint('Reject hint is hidden after activation.');

	await takeStepScreenshot(page, 'focus-mode-activated');

	// ======================================================================
	// STEP 7: Verify the AI response contains career-related content
	// ======================================================================
	logCheckpoint('Waiting for AI response with career advice content...');

	await expect(async () => {
		const allAssistantMessages = page.getByTestId('message-assistant');
		const lastMessage = allAssistantMessages.last();
		const text = await lastMessage.textContent();
		const lowerText = text?.toLowerCase() ?? '';
		logCheckpoint(`Checking assistant response text length: ${text?.length ?? 0}`);
		const hasCareerContent =
			lowerText.includes('career') ||
			lowerText.includes('job') ||
			lowerText.includes('work') ||
			lowerText.includes('role') ||
			lowerText.includes('experience') ||
			lowerText.includes('skill') ||
			lowerText.includes('interest') ||
			lowerText.includes('frustrat');
		expect(hasCareerContent).toBeTruthy();
	}).toPass({ timeout: 45000 });

	logCheckpoint('Assistant response contains career-related content.');
	await takeStepScreenshot(page, 'career-response-verified');

	// ======================================================================
	// STEP 7b: Verify the focus mode embed STILL exists after continuation response
	// This validates Bug 2 fix: the continuation stream must NOT replace the
	// original embed content. The embed should remain visible in the first
	// assistant message even after the follow-up AI text has streamed in.
	// ======================================================================
	logCheckpoint('Re-verifying focus mode embed is still visible after AI continuation...');

	const embedAfterContinuation = page.locator(SELECTORS.focusModeBarActivated);
	await expect(embedAfterContinuation.first()).toBeVisible({ timeout: 10000 });
	logCheckpoint(
		'Focus mode embed is STILL visible after continuation response — Bug 2 fix verified.'
	);

	// Also verify the embed still has the correct focus ID
	const focusIdAfter = await embedAfterContinuation.first().getAttribute('data-focus-id');
	logCheckpoint(`Focus mode ID after continuation: "${focusIdAfter}"`);
	expect(focusIdAfter).toContain('career_insights');

	await takeStepScreenshot(page, 'embed-persists-after-continuation');

	logCheckpoint('All focus mode assertions passed. Attempting cleanup...');

	// Verify no missing translations on the focus mode chat page
	await assertNoMissingTranslations(page);
	logCheckpoint('No missing translations detected.');

	// ======================================================================
	// STEP 8: Delete the chat (cleanup, best-effort)
	// ======================================================================
	await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'career-cleanup');
	logCheckpoint('Career insights focus mode test completed successfully.');
});
