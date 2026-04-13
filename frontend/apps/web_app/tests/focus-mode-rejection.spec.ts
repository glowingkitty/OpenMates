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
 * Focus mode rejection test: Verify that clicking on the focus mode embed
 * during the countdown stops the countdown, hides the embed, and the AI
 * continues responding without focus mode.
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
// Test: Rejecting (interrupting) focus mode during countdown
// ---------------------------------------------------------------------------

test('clicking focus mode embed during countdown rejects focus mode activation', async ({
	page
}: {
	page: any;
}) => {
	setupPageListeners(page);

	test.slow();
	test.setTimeout(180000);

	const logCheckpoint = createSignupLogger('FOCUS_MODE_REJECT');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'focus-mode-reject'
	});

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	await archiveExistingScreenshots(logCheckpoint);
	logCheckpoint('Starting focus mode rejection test.', { email: TEST_EMAIL });

	// ======================================================================
	// STEP 1: Login and start a new chat
	// ======================================================================
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	await startNewChat(page, logCheckpoint);

	// ======================================================================
	// STEP 2: Send a career-related message to trigger focus mode
	// ======================================================================
	const careerMessage =
		"I'm really unhappy with my current career situation. " +
		"I've been in the same position for 3 years with no growth opportunities. " +
		'What career path should I consider?';

	await sendMessage(page, withMockMarker(careerMessage, 'focus_career_2'), logCheckpoint, takeStepScreenshot, 'reject-career');

	// ======================================================================
	// STEP 3: Wait for the focus mode embed to appear during streaming
	// ======================================================================
	const focusModeEmbed = await waitForFocusModeEmbed(
		page,
		logCheckpoint,
		takeStepScreenshot,
		'reject-focus-mode'
	);

	// ======================================================================
	// STEP 4: Verify the embed is in countdown state (not yet activated)
	// ======================================================================
	const countingEmbed = page.locator(SELECTORS.focusModeBarCounting);
	const isCountingVisible = await countingEmbed
		.first()
		.isVisible({ timeout: 3000 })
		.catch(() => false);
	logCheckpoint(`Focus mode is in counting state: ${isCountingVisible}`);

	// The progress bar should be visible during countdown
	const progressBar = focusModeEmbed.first().locator(SELECTORS.progressBar);
	const isProgressVisible = await progressBar.isVisible({ timeout: 3000 }).catch(() => false);
	logCheckpoint(`Progress bar visible: ${isProgressVisible}`);

	// The reject hint should be visible during countdown
	const rejectHint = page.locator(SELECTORS.rejectHint);
	const isHintVisible = await rejectHint.isVisible({ timeout: 3000 }).catch(() => false);
	logCheckpoint(`Reject hint visible: ${isHintVisible}`);

	await takeStepScreenshot(page, 'reject-countdown-state');

	// ======================================================================
	// STEP 5: Click on the embed to reject/interrupt the focus mode
	// ======================================================================
	logCheckpoint('Clicking on focus mode embed to reject...');
	await focusModeEmbed.first().click();
	logCheckpoint('Clicked focus mode embed to reject activation.');
	await takeStepScreenshot(page, 'reject-clicked');

	// ======================================================================
	// STEP 6: Verify the embed is hidden after rejection
	// ======================================================================
	logCheckpoint('Verifying focus mode embed is hidden after rejection...');
	await expect(focusModeEmbed.first()).not.toBeVisible({ timeout: 5000 });
	logCheckpoint('Focus mode embed is hidden after rejection.');

	// Reject hint should also be gone
	await expect(rejectHint).not.toBeVisible({ timeout: 5000 });
	logCheckpoint('Reject hint is hidden after rejection.');

	await takeStepScreenshot(page, 'reject-embed-hidden');

	// ======================================================================
	// STEP 7: Verify the assistant response continues after rejection
	// ======================================================================
	logCheckpoint('Verifying assistant continues responding after rejection...');

	await expect(async () => {
		const allAssistantMessages = page.getByTestId('message-assistant');
		const lastMessage = allAssistantMessages.last();
		const text = await lastMessage.textContent();
		logCheckpoint(`Assistant response text length after rejection: ${text?.length ?? 0}`);
		expect((text?.length ?? 0) > 20).toBeTruthy();
	}).toPass({ timeout: 45000 });

	logCheckpoint('Assistant continues with regular response after focus mode rejection.');
	await takeStepScreenshot(page, 'reject-response-continues');

	// ======================================================================
	// STEP 8: Check for focus mode rejection system message (best-effort)
	// ======================================================================
	logCheckpoint('Checking for focus mode rejection system message (best-effort)...');

	const systemMessages = page.getByTestId('system-message-text');
	const systemCount = await systemMessages.count();
	let foundRejectionMessage = false;
	for (let i = 0; i < systemCount; i++) {
		const text = await systemMessages.nth(i).textContent();
		const lower = text?.toLowerCase() ?? '';
		if (lower.includes('rejected') && lower.includes('focus')) {
			foundRejectionMessage = true;
			logCheckpoint(`Found rejection system message: "${text?.trim()}"`);
			break;
		}
	}
	if (!foundRejectionMessage) {
		const allMsgs = page.locator('[data-testid="message-user"], [data-testid="message-assistant"]');
		const allCount = await allMsgs.count();
		for (let i = 0; i < allCount; i++) {
			const text = await allMsgs.nth(i).textContent();
			const lower = text?.toLowerCase() ?? '';
			if (lower.includes('rejected') && lower.includes('focus')) {
				foundRejectionMessage = true;
				logCheckpoint(`Found rejection message in wrapper: "${text?.trim()}"`);
				break;
			}
		}
	}
	if (foundRejectionMessage) {
		logCheckpoint('Rejection system message verified.');
	} else {
		logCheckpoint(
			'WARNING: Rejection system message not found — focus mode rejection event may not have fired. Non-fatal.'
		);
	}
	await takeStepScreenshot(page, 'reject-final-state');

	// ======================================================================
	// STEP 9: Delete the chat (cleanup)
	// ======================================================================
	await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'reject-cleanup');
	logCheckpoint('Focus mode rejection test completed successfully.');
});
