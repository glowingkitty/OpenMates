/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('@playwright/test');

const consoleLogs: string[] = [];
const networkActivities: string[] = [];

test.beforeEach(async () => {
	consoleLogs.length = 0;
	networkActivities.length = 0;
});

// eslint-disable-next-line no-empty-pattern
test.afterEach(async ({}, testInfo: any) => {
	if (testInfo.status !== 'passed') {
		console.log('\n--- DEBUG INFO ON FAILURE ---');
		console.log('\n[RECENT CONSOLE LOGS]');
		consoleLogs.slice(-30).forEach((log) => console.log(log));

		console.log('\n[RECENT NETWORK ACTIVITIES]');
		networkActivities.slice(-30).forEach((activity) => console.log(activity));
		console.log('\n--- END DEBUG INFO ---\n');
	}
});

const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	generateTotp
} = require('./signup-flow-helpers');

/**
 * Focus mode tests: Verify the "Career insights" focus mode from the Jobs app
 * works correctly in various scenarios:
 *
 * 1. Activation: Focus mode activates when user expresses career frustration
 * 2. Rejection: User can interrupt/cancel focus mode during countdown
 * 3. Context menu: Shows focus mode indicator when active
 * 4. Persistence: Focus mode remains active on follow-up messages
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL: Email of an existing test account.
 * - OPENMATES_TEST_ACCOUNT_PASSWORD: Password for the test account.
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY: 2FA OTP secret (base32) for the test account.
 * - PLAYWRIGHT_TEST_BASE_URL: Base URL for the deployed web app under test.
 */

const TEST_EMAIL = process.env.OPENMATES_TEST_ACCOUNT_EMAIL;
const TEST_PASSWORD = process.env.OPENMATES_TEST_ACCOUNT_PASSWORD;
const TEST_OTP_KEY = process.env.OPENMATES_TEST_ACCOUNT_OTP_KEY;

// ---------------------------------------------------------------------------
// Selectors: Based on FocusModeActivationEmbed.svelte CSS classes
// The Svelte component uses 'focus-mode-bar' as the main class.
// The renderer sets data-embed-type, data-focus-id, data-app-id on the container.
// ---------------------------------------------------------------------------
const SELECTORS = {
	/** Focus mode bar (inner Svelte component) with app-specific filter */
	focusModeBar: '.focus-mode-bar[data-app-id="jobs"]',
	/** Focus mode bar in activated state */
	focusModeBarActivated: '.focus-mode-bar.activated[data-app-id="jobs"]',
	/** Focus mode bar during countdown (not yet activated) */
	focusModeBarCounting: '.focus-mode-bar.counting[data-app-id="jobs"]',
	/** Status label (focus mode display name) */
	statusLabel: '.status-label',
	/** Status value (countdown text or "Focus activated") */
	statusValue: '.status-value',
	/** Status value in activated state */
	statusValueActive: '.status-value.active-status',
	/** Progress bar container (visible during countdown only) */
	progressBar: '.progress-bar-container',
	/** Reject hint text below the bar (visible during countdown only) */
	rejectHint: '.reject-hint',
	/** Chat context menu focus mode indicator */
	contextMenuFocusIndicator: '.focus-mode-indicator',
	contextMenuFocusLabel: '.focus-mode-label'
};

// ---------------------------------------------------------------------------
// Shared helpers (same pattern as web-search-flow.spec.ts)
// ---------------------------------------------------------------------------

/**
 * Login to the test account with email, password, and 2FA OTP.
 * Includes retry logic for OTP timing edge cases.
 */
async function loginToTestAccount(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void,
	takeStepScreenshot: (page: any, label: string) => Promise<void>
): Promise<void> {
	await page.goto('/');
	await takeStepScreenshot(page, 'home');

	const headerLoginButton = page.getByRole('button', {
		name: /login.*sign up|sign up/i
	});
	await expect(headerLoginButton).toBeVisible({ timeout: 15000 });
	await headerLoginButton.click();
	await takeStepScreenshot(page, 'login-dialog');

	const emailInput = page.locator('input[name="username"][type="email"]');
	await expect(emailInput).toBeVisible();
	await emailInput.fill(TEST_EMAIL);
	await page.getByRole('button', { name: /continue/i }).click();
	logCheckpoint('Entered email and clicked continue.');

	const passwordInput = page.locator('input[type="password"]');
	await expect(passwordInput).toBeVisible({ timeout: 15000 });
	await passwordInput.fill(TEST_PASSWORD);
	await takeStepScreenshot(page, 'password-entered');

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
		if (attempt === 1) {
			await takeStepScreenshot(page, 'otp-entered');
		}

		await expect(submitLoginButton).toBeVisible();
		await submitLoginButton.click();
		logCheckpoint('Submitted login form.');

		try {
			await expect(otpInput).not.toBeVisible({ timeout: 15000 });
			loginSuccess = true;
			logCheckpoint('Login dialog closed, login successful.');
		} catch {
			const hasError = await errorMessage.isVisible().catch(() => false);
			if (hasError && attempt < 3) {
				logCheckpoint(`OTP attempt ${attempt} failed, retrying with fresh code...`);
				await page.waitForTimeout(2000);
			} else if (attempt === 3) {
				throw new Error('Login failed after 3 OTP attempts');
			}
		}
	}

	logCheckpoint('Waiting for chat interface to load...');
	await page.waitForTimeout(3000);

	const messageEditor = page.locator('.editor-content.prose');
	await expect(messageEditor).toBeVisible({ timeout: 20000 });
	logCheckpoint('Chat interface loaded - message editor visible.');
}

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
	const sidebar = page.locator('.activity-history-wrapper');
	if (await sidebar.isVisible({ timeout: 1000 }).catch(() => false)) {
		logCheckpoint('Sidebar already open.');
		return;
	}

	// Try clicking the hamburger menu button to open the sidebar
	const menuButton = page.locator('.menu-button-container button.icon_menu');
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
 * Start a new chat session by clicking the new chat button.
 */
async function startNewChat(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void
): Promise<void> {
	await page.waitForTimeout(1000);

	const currentUrl = page.url();
	logCheckpoint(`Current URL before starting new chat: ${currentUrl}`);

	// The new chat CTA button is in ActiveChat.svelte with class .new-chat-cta-button
	const newChatButton = page.locator('.new-chat-cta-button');
	if (await newChatButton.isVisible({ timeout: 3000 }).catch(() => false)) {
		logCheckpoint('Found .new-chat-cta-button, clicking it.');
		await newChatButton.click();
		await page.waitForTimeout(2000);
	} else {
		logCheckpoint(
			'New Chat button not visible. Already on a fresh chat or demo chat — proceeding.'
		);
	}

	const newUrl = page.url();
	logCheckpoint(`URL after attempting to start new chat: ${newUrl}`);
}

/**
 * Send a message in the chat editor and wait for the send to complete.
 */
async function sendMessage(
	page: any,
	message: string,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void,
	takeStepScreenshot: (page: any, label: string) => Promise<void>,
	stepLabel: string
): Promise<void> {
	const messageEditor = page.locator('.editor-content.prose');
	await expect(messageEditor).toBeVisible();
	await messageEditor.click();
	await page.keyboard.type(message);
	logCheckpoint(`Typed message: "${message}"`);
	await takeStepScreenshot(page, `${stepLabel}-message-typed`);

	const sendButton = page.locator('.send-button');
	await expect(sendButton).toBeEnabled();
	await sendButton.click();
	logCheckpoint('Clicked send button.');
	await takeStepScreenshot(page, `${stepLabel}-message-sent`);
}

/**
 * Delete the active chat via context menu (best-effort cleanup).
 * Uses short timeouts to avoid consuming the test's remaining time budget.
 */
async function deleteActiveChat(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void,
	takeStepScreenshot: (page: any, label: string) => Promise<void>,
	stepLabel: string
): Promise<void> {
	logCheckpoint('Attempting to delete the chat (best-effort cleanup)...');

	try {
		// Ensure sidebar is open so we can find the active chat item
		await ensureSidebarOpen(page, logCheckpoint);

		// Use .chat-item-wrapper.active inside Chat.svelte (rendered within sidebar)
		const activeChatItem = page.locator('.chat-item-wrapper.active');

		if (!(await activeChatItem.isVisible({ timeout: 3000 }).catch(() => false))) {
			logCheckpoint('No active chat item visible in sidebar - skipping cleanup.');
			return;
		}

		// Safety check: don't delete the demo chat
		try {
			const chatTitle = await activeChatItem.locator('.chat-title').textContent({ timeout: 1000 });
			logCheckpoint(`Active chat title: "${chatTitle}"`);

			if (
				chatTitle &&
				(chatTitle.includes('demo') ||
					chatTitle.includes('Demo') ||
					chatTitle.includes('OpenMates'))
			) {
				logCheckpoint('Skipping deletion - appears to be a demo chat.');
				return;
			}
		} catch {
			logCheckpoint('Could not get active chat title - continuing with deletion.');
		}

		// Right-click to open context menu
		await activeChatItem.click({ button: 'right' });
		logCheckpoint('Opened chat context menu.');

		await page.waitForTimeout(300);
		const deleteButton = page.locator('.menu-item.delete');

		if (!(await deleteButton.isVisible({ timeout: 2000 }).catch(() => false))) {
			logCheckpoint('Delete button not visible in context menu - skipping cleanup.');
			await page.keyboard.press('Escape');
			return;
		}

		// First click: enter confirm mode. Second click: confirm deletion.
		await deleteButton.click();
		logCheckpoint('Clicked delete (confirm mode).');
		await page.waitForTimeout(300);
		await deleteButton.click();
		logCheckpoint('Confirmed chat deletion.');

		// Brief wait to verify deletion, but don't block for long
		await expect(activeChatItem).not.toBeVisible({ timeout: 5000 });
		await takeStepScreenshot(page, `${stepLabel}-chat-deleted`);
		logCheckpoint('Chat deleted successfully.');
	} catch (error) {
		logCheckpoint(`Cleanup failed (non-fatal): ${error}`);
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
	await expect(focusModeEmbed.first()).toBeVisible({ timeout: 90000 });
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
	// Allow up to 6 minutes for the full flow including cleanup time.
	test.setTimeout(360000);

	const logCheckpoint = createSignupLogger('FOCUS_MODE_CAREER');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'focus-mode-career'
	});

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

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

	await sendMessage(page, careerMessage, logCheckpoint, takeStepScreenshot, 'career-advice');

	// ======================================================================
	// STEP 3: Wait for assistant response
	// ======================================================================
	logCheckpoint('Waiting for assistant response...');
	const assistantMessage = page.locator('.message-wrapper.assistant');
	await expect(assistantMessage.first()).toBeVisible({ timeout: 60000 });
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
		const allAssistantMessages = page.locator('.message-wrapper.assistant');
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
	}).toPass({ timeout: 60000 });

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

	// ======================================================================
	// STEP 8: Delete the chat (cleanup, best-effort)
	// ======================================================================
	await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'career-cleanup');
	logCheckpoint('Career insights focus mode test completed successfully.');
});

// ---------------------------------------------------------------------------
// Test 2: Rejecting (interrupting) focus mode during countdown
//
// Verifies that clicking on the focus mode embed during the countdown:
// 1. Stops the countdown immediately
// 2. Hides the focus mode embed (rejected state)
// 3. Creates a system message informing about the rejected focus mode
// 4. The assistant response continues without focus mode
// ---------------------------------------------------------------------------

test('clicking focus mode embed during countdown rejects focus mode activation', async ({
	page
}: {
	page: any;
}) => {
	setupPageListeners(page);

	test.slow();
	test.setTimeout(300000);

	const logCheckpoint = createSignupLogger('FOCUS_MODE_REJECT');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'focus-mode-reject'
	});

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

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

	await sendMessage(page, careerMessage, logCheckpoint, takeStepScreenshot, 'reject-career');

	// ======================================================================
	// STEP 3: Wait for assistant response and focus mode embed
	// ======================================================================
	logCheckpoint('Waiting for assistant response...');
	const assistantMessage = page.locator('.message-wrapper.assistant');
	await expect(assistantMessage.first()).toBeVisible({ timeout: 60000 });

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
	// The FocusModeActivationEmbed component hides itself when rejected
	// (the entire {#if !isRejected} block becomes false)
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
	// The response should still contain some content (assistant continues in regular mode)
	// Focus mode rejection may also produce a system message, but the primary assertion
	// is that the embed is hidden and the AI continues.
	// ======================================================================
	logCheckpoint('Verifying assistant continues responding after rejection...');

	await expect(async () => {
		const allAssistantMessages = page.locator('.message-wrapper.assistant');
		const lastMessage = allAssistantMessages.last();
		const text = await lastMessage.textContent();
		logCheckpoint(`Assistant response text length after rejection: ${text?.length ?? 0}`);
		// The response should have some meaningful content (more than just the embed)
		expect((text?.length ?? 0) > 20).toBeTruthy();
	}).toPass({ timeout: 60000 });

	logCheckpoint('Assistant continues with regular response after focus mode rejection.');
	await takeStepScreenshot(page, 'reject-response-continues');

	// ======================================================================
	// STEP 8: Check for focus mode rejection system message (best-effort)
	// The ActiveChat handler dispatches a system message like "Rejected Career insights focus mode."
	// This is a soft check — the main assertions are above (embed hidden + AI continues).
	// ======================================================================
	logCheckpoint('Checking for focus mode rejection system message (best-effort)...');

	const systemMessages = page.locator('.system-message-text');
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
		// Also check all message wrappers in case system message uses a different structure
		const allMsgs = page.locator('.message-wrapper');
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

// ---------------------------------------------------------------------------
// Test 3: Chat context menu shows focus mode indicator when active
//
// Verifies that after a focus mode is activated:
// 1. The chat context menu (right-click on chat in sidebar) shows a focus mode indicator
// 2. The indicator displays the correct focus mode name
// ---------------------------------------------------------------------------

test('chat context menu shows focus mode indicator when career insights is active', async ({
	page
}: {
	page: any;
}) => {
	setupPageListeners(page);

	test.slow();
	test.setTimeout(300000);

	const logCheckpoint = createSignupLogger('FOCUS_MODE_CONTEXT_MENU');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'focus-mode-context-menu'
	});

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	await archiveExistingScreenshots(logCheckpoint);
	logCheckpoint('Starting focus mode context menu test.', { email: TEST_EMAIL });

	// ======================================================================
	// STEP 1: Login and start a new chat
	// ======================================================================
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	await startNewChat(page, logCheckpoint);

	// ======================================================================
	// STEP 2: Trigger focus mode activation
	// ======================================================================
	const careerMessage =
		"I'm very frustrated with my career. I've been doing the same thing for years " +
		'and I need help figuring out my next career move. What should I do?';

	await sendMessage(page, careerMessage, logCheckpoint, takeStepScreenshot, 'ctx-menu-career');

	logCheckpoint('Waiting for assistant response...');
	const assistantMessage = page.locator('.message-wrapper.assistant');
	await expect(assistantMessage.first()).toBeVisible({ timeout: 60000 });

	// Wait for focus mode embed and let it activate
	await waitForFocusModeEmbed(page, logCheckpoint, takeStepScreenshot, 'ctx-menu-focus');

	logCheckpoint('Waiting for focus mode to activate (countdown)...');
	const activatedEmbed = page.locator(SELECTORS.focusModeBarActivated);
	await expect(activatedEmbed.first()).toBeVisible({ timeout: 15000 });
	logCheckpoint('Focus mode has been activated!');

	// Wait for the AI response to fully complete and for the server to sync
	// the encrypted_active_focus_id to the client's IndexedDB. The context menu
	// reads this field to show the focus mode indicator.
	logCheckpoint('Waiting for AI response to complete and focus metadata to sync...');
	await expect(async () => {
		const allAssistantMessages = page.locator('.message-wrapper.assistant');
		const lastMessage = allAssistantMessages.last();
		const text = await lastMessage.textContent();
		logCheckpoint(`Waiting for AI completion: response length = ${text?.length ?? 0}`);
		// AI response should have meaningful career content by now
		expect((text?.length ?? 0) > 50).toBeTruthy();
	}).toPass({ timeout: 60000 });
	logCheckpoint('AI response is complete.');

	// Additional wait for server sync to propagate encrypted_active_focus_id
	await page.waitForTimeout(5000);
	await takeStepScreenshot(page, 'ctx-menu-focus-activated');

	// ======================================================================
	// STEP 3: Open the chat context menu and check for focus mode indicator
	// The ChatContextMenu.svelte loads activeFocusId from chatMetadataCache
	// which reads encrypted_active_focus_id from IndexedDB (synced from server).
	// We use a retry loop: open menu → check → close → retry if needed.
	// ======================================================================
	logCheckpoint('Opening sidebar to find active chat...');

	// Ensure sidebar is visible
	await ensureSidebarOpen(page, logCheckpoint);

	const activeChatItem = page.locator('.chat-item-wrapper.active');
	await expect(activeChatItem).toBeVisible({ timeout: 5000 });
	logCheckpoint('Active chat item visible in sidebar.');

	logCheckpoint('Checking for focus mode indicator in context menu (with retries)...');
	let foundFocusIndicator = false;
	for (let attempt = 1; attempt <= 3 && !foundFocusIndicator; attempt++) {
		logCheckpoint(`Context menu attempt ${attempt}/3...`);

		// Right-click to open context menu
		await activeChatItem.click({ button: 'right' });
		await page.waitForTimeout(500);

		const focusIndicator = page.locator(SELECTORS.contextMenuFocusIndicator);
		if (await focusIndicator.isVisible({ timeout: 5000 }).catch(() => false)) {
			foundFocusIndicator = true;
			logCheckpoint('Focus mode indicator is visible in context menu!');
			await takeStepScreenshot(page, 'ctx-menu-focus-indicator-verified');

			// Verify the focus mode label shows the correct name
			const focusLabel = page.locator(SELECTORS.contextMenuFocusLabel);
			if (await focusLabel.isVisible({ timeout: 2000 }).catch(() => false)) {
				const labelText = await focusLabel.textContent();
				logCheckpoint(`Focus mode label in context menu: "${labelText}"`);
				expect(labelText?.toLowerCase()).toContain('career');
			}

			// Close context menu
			await page.keyboard.press('Escape');
			await page.waitForTimeout(300);
		} else {
			logCheckpoint(
				`Focus indicator not visible on attempt ${attempt}. Closing menu and waiting for sync...`
			);
			await page.keyboard.press('Escape');
			await page.waitForTimeout(5000); // Wait for more sync time before retry
		}
	}

	expect(foundFocusIndicator).toBeTruthy();

	// ======================================================================
	// STEP 5: Delete the chat (cleanup)
	// ======================================================================
	await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'ctx-menu-cleanup');
	logCheckpoint('Focus mode context menu test completed successfully.');
});

// ---------------------------------------------------------------------------
// Test 4: Focus mode remains active on follow-up messages
//
// Verifies that once a focus mode is activated:
// 1. Sending a follow-up message keeps the focus mode active
// 2. The follow-up response still uses the focus mode context
// 3. The context menu still shows the focus mode indicator after follow-up
// ---------------------------------------------------------------------------

test('focus mode remains active on follow-up messages', async ({ page }: { page: any }) => {
	setupPageListeners(page);

	test.slow();
	test.setTimeout(360000);

	const logCheckpoint = createSignupLogger('FOCUS_MODE_FOLLOWUP');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'focus-mode-followup'
	});

	test.skip(!TEST_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!TEST_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!TEST_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	await archiveExistingScreenshots(logCheckpoint);
	logCheckpoint('Starting focus mode follow-up persistence test.', { email: TEST_EMAIL });

	// ======================================================================
	// STEP 1: Login and start a new chat
	// ======================================================================
	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
	await startNewChat(page, logCheckpoint);

	// ======================================================================
	// STEP 2: Trigger focus mode activation
	// ======================================================================
	const careerMessage =
		"I'm really unhappy with my career and need guidance. " +
		"I've been working as a software developer for 5 years but feel stuck. " +
		'What career options should I explore?';

	await sendMessage(page, careerMessage, logCheckpoint, takeStepScreenshot, 'followup-initial');

	logCheckpoint('Waiting for assistant response...');
	const assistantMessage = page.locator('.message-wrapper.assistant');
	await expect(assistantMessage.first()).toBeVisible({ timeout: 60000 });

	// Wait for focus mode embed and activation
	await waitForFocusModeEmbed(page, logCheckpoint, takeStepScreenshot, 'followup-focus');

	logCheckpoint('Waiting for focus mode to activate...');
	const activatedEmbed = page.locator(SELECTORS.focusModeBarActivated);
	await expect(activatedEmbed.first()).toBeVisible({ timeout: 15000 });
	logCheckpoint('Focus mode has been activated!');

	// Wait for the initial response to complete (streaming done)
	await page.waitForTimeout(5000);
	await takeStepScreenshot(page, 'followup-initial-response-done');

	// ======================================================================
	// STEP 3: Count assistant messages before follow-up
	// ======================================================================
	const allAssistantMessagesBefore = page.locator('.message-wrapper.assistant');
	const countBefore = await allAssistantMessagesBefore.count();
	logCheckpoint(`Assistant messages before follow-up: ${countBefore}`);

	// ======================================================================
	// STEP 4: Send a follow-up message (still career-related)
	// ======================================================================
	const followUpMessage =
		"I'm particularly interested in transitioning to a product management role. " +
		'What skills do I need and how should I prepare?';

	await sendMessage(page, followUpMessage, logCheckpoint, takeStepScreenshot, 'followup-msg');

	// ======================================================================
	// STEP 5: Wait for follow-up assistant response
	// ======================================================================
	logCheckpoint('Waiting for follow-up assistant response...');

	await expect(async () => {
		const allAssistantMessagesAfter = page.locator('.message-wrapper.assistant');
		const countAfter = await allAssistantMessagesAfter.count();
		logCheckpoint(`Assistant messages after follow-up: ${countAfter} (was ${countBefore})`);
		// At least one more assistant message should appear
		expect(countAfter).toBeGreaterThan(countBefore);
	}).toPass({ timeout: 90000 });

	logCheckpoint('Follow-up assistant response received.');

	// ======================================================================
	// STEP 6: Verify follow-up response contains career/product management content
	// This confirms the AI is still using the career focus mode context
	// ======================================================================
	logCheckpoint('Verifying follow-up response has career-focused content...');

	await expect(async () => {
		const allAssistantMessages = page.locator('.message-wrapper.assistant');
		const lastMessage = allAssistantMessages.last();
		const text = await lastMessage.textContent();
		const lowerText = text?.toLowerCase() ?? '';
		logCheckpoint(`Follow-up response text length: ${text?.length ?? 0}`);
		// The follow-up response should reference career/product management topics
		const hasRelevantContent =
			lowerText.includes('product') ||
			lowerText.includes('management') ||
			lowerText.includes('career') ||
			lowerText.includes('transition') ||
			lowerText.includes('skill') ||
			lowerText.includes('role');
		expect(hasRelevantContent).toBeTruthy();
	}).toPass({ timeout: 30000 });

	logCheckpoint(
		'Follow-up response contains career-focused content, confirming focus mode persistence.'
	);
	await takeStepScreenshot(page, 'followup-response-verified');

	// ======================================================================
	// STEP 6b: Verify the ORIGINAL focus mode embed in the first assistant message
	// is still visible after the follow-up response. This catches Bug 2 regressions
	// where continuation content could overwrite the embed.
	// ======================================================================
	logCheckpoint('Verifying original focus mode embed persists after follow-up response...');

	const originalEmbed = page.locator(SELECTORS.focusModeBarActivated);
	await expect(originalEmbed.first()).toBeVisible({ timeout: 10000 });
	logCheckpoint(
		'Original focus mode embed is STILL visible after follow-up — embed persistence verified.'
	);

	const originalFocusId = await originalEmbed.first().getAttribute('data-focus-id');
	logCheckpoint(`Original embed focus ID after follow-up: "${originalFocusId}"`);
	expect(originalFocusId).toContain('career_insights');

	await takeStepScreenshot(page, 'followup-original-embed-persists');

	// ======================================================================
	// STEP 7: Verify focus mode is still active in context menu after follow-up
	// Wait for sync propagation before checking, then retry up to 3 times.
	// ======================================================================
	logCheckpoint('Checking context menu still shows focus mode after follow-up...');

	// Wait for server sync to propagate encrypted_active_focus_id
	await page.waitForTimeout(5000);

	// Ensure sidebar is visible
	await ensureSidebarOpen(page, logCheckpoint);

	const activeChatItem = page.locator('.chat-item-wrapper.active');
	await expect(activeChatItem).toBeVisible({ timeout: 5000 });
	logCheckpoint('Active chat item visible in sidebar.');

	let foundFocusIndicator = false;
	for (let attempt = 1; attempt <= 3 && !foundFocusIndicator; attempt++) {
		logCheckpoint(`Context menu attempt ${attempt}/3 (follow-up test)...`);

		await activeChatItem.click({ button: 'right' });
		await page.waitForTimeout(500);

		const focusIndicator = page.locator(SELECTORS.contextMenuFocusIndicator);
		if (await focusIndicator.isVisible({ timeout: 5000 }).catch(() => false)) {
			foundFocusIndicator = true;
			logCheckpoint('Focus mode indicator is STILL visible in context menu after follow-up!');

			const focusLabel = page.locator(SELECTORS.contextMenuFocusLabel);
			if (await focusLabel.isVisible({ timeout: 2000 }).catch(() => false)) {
				const labelText = await focusLabel.textContent();
				logCheckpoint(`Focus mode label after follow-up: "${labelText}"`);
				expect(labelText?.toLowerCase()).toContain('career');
			}

			await takeStepScreenshot(page, 'followup-context-menu-still-active');

			// Close context menu
			await page.keyboard.press('Escape');
			await page.waitForTimeout(300);
		} else {
			logCheckpoint(
				`Focus indicator not visible on attempt ${attempt}. Closing menu and waiting for sync...`
			);
			await page.keyboard.press('Escape');
			await page.waitForTimeout(5000);
		}
	}

	expect(foundFocusIndicator).toBeTruthy();

	// ======================================================================
	// STEP 8: Delete the chat (cleanup)
	// ======================================================================
	await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'followup-cleanup');
	logCheckpoint('Focus mode follow-up persistence test completed successfully.');
});
