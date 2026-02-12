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
 * Focus mode test: Verify that the "Career insights" focus mode from the Jobs app
 * is triggered when the user expresses frustration with their current job and asks
 * for career advice.
 *
 * The test:
 * 1. Logs in with an existing test account
 * 2. Starts a new chat
 * 3. Sends a message expressing job frustration and asking for career advice
 * 4. Waits for the AI to respond and checks that a focus mode activation embed
 *    appears with focus-id "jobs-career_insights"
 * 5. Verifies the focus mode card renders correctly (countdown, name)
 * 6. Waits for the focus mode to activate (countdown completes)
 * 7. Verifies the activated state
 * 8. Deletes the chat
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
 * Start a new chat session by clicking the new chat button.
 */
async function startNewChat(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void
): Promise<void> {
	await page.waitForTimeout(1000);

	const currentUrl = page.url();
	logCheckpoint(`Current URL before starting new chat: ${currentUrl}`);

	const newChatButtonSelectors = [
		'.new-chat-cta-button',
		'.icon_create',
		'button[aria-label*="New"]',
		'button[aria-label*="new"]'
	];

	let clicked = false;
	for (const selector of newChatButtonSelectors) {
		const button = page.locator(selector).first();
		if (await button.isVisible({ timeout: 3000 }).catch(() => false)) {
			logCheckpoint(`Found New Chat button with selector: ${selector}`);
			await button.click();
			clicked = true;
			await page.waitForTimeout(2000);
			break;
		}
	}

	if (!clicked) {
		logCheckpoint('New Chat button not initially visible, trying to trigger it...');
		const messageEditor = page.locator('.editor-content.prose');
		if (await messageEditor.isVisible({ timeout: 3000 }).catch(() => false)) {
			await messageEditor.click();
			await page.keyboard.type(' ');
			await page.waitForTimeout(500);

			for (const selector of newChatButtonSelectors) {
				const button = page.locator(selector).first();
				if (await button.isVisible({ timeout: 3000 }).catch(() => false)) {
					logCheckpoint(`Found New Chat button after typing: ${selector}`);
					await button.click();
					clicked = true;
					await page.waitForTimeout(2000);
					break;
				}
			}

			if (clicked) {
				const newEditor = page.locator('.editor-content.prose');
				if (await newEditor.isVisible({ timeout: 2000 }).catch(() => false)) {
					await newEditor.click();
					await page.keyboard.press('Control+A');
					await page.keyboard.press('Backspace');
				}
			}
		}
	}

	if (!clicked) {
		logCheckpoint('WARNING: Could not find New Chat button with any selector.');
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
 */
async function deleteActiveChat(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void,
	takeStepScreenshot: (page: any, label: string) => Promise<void>,
	stepLabel: string
): Promise<void> {
	logCheckpoint('Attempting to delete the chat (best-effort cleanup)...');

	try {
		const sidebarToggle = page.locator('.sidebar-toggle-button');
		if (await sidebarToggle.isVisible()) {
			await sidebarToggle.click();
			await page.waitForTimeout(500);
		}

		const activeChatItem = page.locator('.chat-item-wrapper.active');

		if (!(await activeChatItem.isVisible({ timeout: 5000 }).catch(() => false))) {
			logCheckpoint('No active chat item visible - skipping cleanup.');
			return;
		}

		try {
			const chatTitle = await activeChatItem.locator('.chat-title').textContent();
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
			logCheckpoint('Could not get active chat title.');
		}

		await activeChatItem.click({ button: 'right' });
		await takeStepScreenshot(page, `${stepLabel}-context-menu-open`);
		logCheckpoint('Opened chat context menu.');

		await page.waitForTimeout(300);
		const deleteButton = page.locator('.menu-item.delete');

		if (!(await deleteButton.isVisible({ timeout: 3000 }).catch(() => false))) {
			logCheckpoint('Delete button not visible in context menu - skipping cleanup.');
			await page.keyboard.press('Escape');
			return;
		}

		await deleteButton.click();
		await takeStepScreenshot(page, `${stepLabel}-delete-confirm-mode`);
		logCheckpoint('Clicked delete, now in confirm mode.');

		await deleteButton.click();
		logCheckpoint('Confirmed chat deletion.');

		await expect(activeChatItem).not.toBeVisible({ timeout: 10000 });
		await takeStepScreenshot(page, `${stepLabel}-chat-deleted`);
		logCheckpoint('Verified chat deletion successfully.');
	} catch (error) {
		logCheckpoint(`Cleanup failed (non-fatal): ${error}`);
	}
}

// ---------------------------------------------------------------------------
// Test: Career insights focus mode activation
// ---------------------------------------------------------------------------

test('career frustration message triggers Career insights focus mode', async ({
	page
}: {
	page: any;
}) => {
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

	test.slow();
	// Focus mode activation involves AI preprocessing + main processing + streaming.
	// Allow up to 5 minutes for the full flow.
	test.setTimeout(300000);

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
	// STEP 2: Send a message expressing career frustration and asking for advice
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
	// The embed has data-embed-type="focus-mode-activation" and data-focus-id
	// containing "career_insights". The focus ID format is "jobs-career_insights".
	// ======================================================================
	logCheckpoint('Waiting for focus mode activation embed to appear...');

	// Look for the focus mode activation element by its data attributes.
	// The component renders with class "focus-mode-activation" and data-focus-id.
	const focusModeEmbed = page.locator('.focus-mode-activation[data-app-id="jobs"]');

	await expect(focusModeEmbed.first()).toBeVisible({ timeout: 90000 });
	logCheckpoint('Focus mode activation embed is visible!');
	await takeStepScreenshot(page, 'focus-mode-embed-visible');

	// Verify the focus mode ID contains "career_insights"
	const focusId = await focusModeEmbed.first().getAttribute('data-focus-id');
	logCheckpoint(`Focus mode ID: "${focusId}"`);
	expect(focusId).toContain('career_insights');

	// ======================================================================
	// STEP 5: Verify focus mode card content
	// ======================================================================
	// Check the focus mode name is displayed
	const focusName = focusModeEmbed.first().locator('.focus-name');
	await expect(focusName).toBeVisible({ timeout: 5000 });
	const focusNameText = await focusName.textContent();
	logCheckpoint(`Focus mode name displayed: "${focusNameText}"`);
	// The name should be "Career insights" (English)
	expect(focusNameText?.toLowerCase()).toContain('career');

	// Check the status text is visible (should show countdown or activated)
	const focusStatus = focusModeEmbed.first().locator('.focus-status');
	await expect(focusStatus).toBeVisible({ timeout: 5000 });
	const statusText = await focusStatus.textContent();
	logCheckpoint(`Focus mode status text: "${statusText}"`);

	await takeStepScreenshot(page, 'focus-mode-card-verified');

	// ======================================================================
	// STEP 6: Wait for focus mode to activate (countdown completes in 4 seconds)
	// ======================================================================
	logCheckpoint('Waiting for focus mode to activate (4-second countdown)...');

	// The activated state adds the "activated" class to the card
	const activatedEmbed = page.locator('.focus-mode-activation.activated[data-app-id="jobs"]');
	await expect(activatedEmbed.first()).toBeVisible({ timeout: 15000 });
	logCheckpoint('Focus mode has been activated!');

	// Verify the activated status text
	const activatedStatus = activatedEmbed.first().locator('.focus-status.active-status');
	await expect(activatedStatus).toBeVisible({ timeout: 5000 });
	const activatedStatusText = await activatedStatus.textContent();
	logCheckpoint(`Activated status text: "${activatedStatusText}"`);
	// Should say "Focus activated" or similar
	expect(activatedStatusText?.toLowerCase()).toContain('activat');

	// The progress bar should no longer be visible after activation
	const progressBar = activatedEmbed.first().locator('.progress-bar-container');
	await expect(progressBar).not.toBeVisible({ timeout: 5000 });
	logCheckpoint('Progress bar is hidden after activation.');

	// The reject hint should also be hidden after activation
	const rejectHint = page.locator('.reject-hint');
	await expect(rejectHint).not.toBeVisible({ timeout: 5000 });
	logCheckpoint('Reject hint is hidden after activation.');

	await takeStepScreenshot(page, 'focus-mode-activated');

	// ======================================================================
	// STEP 7: Verify the AI response contains career-related content
	// After focus mode activates, the AI should respond with career advice
	// ======================================================================
	logCheckpoint('Waiting for AI response with career advice content...');

	// Wait for the assistant response to contain some career-related keywords
	// The AI should ask about the user's situation, interests, etc.
	await expect(async () => {
		const allAssistantMessages = page.locator('.message-wrapper.assistant');
		const lastMessage = allAssistantMessages.last();
		const text = await lastMessage.textContent();
		const lowerText = text?.toLowerCase() ?? '';
		logCheckpoint(`Checking assistant response text length: ${text?.length ?? 0}`);
		// The response should contain at least one career-related keyword
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
	// STEP 8: Delete the chat (cleanup)
	// ======================================================================
	await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'career-cleanup');
	logCheckpoint('Career insights focus mode test completed successfully.');
});
