/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Shared chat test helpers for Playwright E2E tests.
 *
 * Extracted from web-search-flow.spec.ts (the most robust implementations).
 * Provides login, new chat, send message, and delete chat helpers.
 *
 * Usage:
 *   const { loginToTestAccount, startNewChat, sendMessage, deleteActiveChat } = require('./helpers/chat-test-helpers');
 *
 * Architecture context: docs/architecture/e2e-testing.md
 */
export {};

const { expect } = require('@playwright/test');
const {
	generateTotp,
	getTestAccount,
	getE2EDebugUrl
} = require('../signup-flow-helpers');

/** No-op screenshot function for when screenshots aren't needed */
const noopScreenshot = async (_page: any, _label: string): Promise<void> => {};

/** No-op log function for when logging isn't needed */
const noopLog = (_message: string, _metadata?: Record<string, unknown>): void => {};

/**
 * Login to the test account with email, password, and 2FA OTP.
 * Checks "Stay logged in" so keys are persisted to IndexedDB.
 * Includes retry logic for OTP timing edge cases and 429 rate limits.
 */
async function loginToTestAccount(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void = noopLog,
	takeStepScreenshot: (page: any, label: string) => Promise<void> = noopScreenshot,
	options: { waitForEditor?: boolean } = {}
): Promise<void> {
	const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

	// Monitor for 429 rate limit responses during login flow
	let hit429 = false;
	const on429 = (response: any) => {
		if (response.status() === 429) {
			hit429 = true;
		}
	};
	page.on('response', on429);

	await page.goto(getE2EDebugUrl('/'));

	// Clear any rate-limit flags from previous test runs that would hide the login form
	await page.evaluate(() => {
		localStorage.removeItem('emailLookupRateLimit');
		localStorage.removeItem('loginRateLimit');
		localStorage.removeItem('passwordTfaRateLimit');
	});

	await takeStepScreenshot(page, 'home');

	// Header button now opens the signup interface (not login directly).
	// Click it, then switch to the Login tab before entering credentials.
	const headerSignupButton = page.getByRole('button', {
		name: /login.*sign up|sign up/i
	});
	await expect(headerSignupButton).toBeVisible({ timeout: 15000 });
	await headerSignupButton.click();
	await takeStepScreenshot(page, 'signup-interface-opened');

	// Click the "Login" tab in the login/signup tab bar to switch to the login form
	const loginTab = page.locator('.login-tabs .tab-button', { hasText: /^login$/i });
	await expect(loginTab).toBeVisible({ timeout: 10000 });
	await loginTab.click();
	logCheckpoint('Clicked Login tab to switch from signup to login view.');
	await takeStepScreenshot(page, 'login-dialog');

	const emailInput = page.locator('#login-email-input');
	await expect(emailInput).toBeVisible({ timeout: 15000 });
	await emailInput.fill(TEST_EMAIL);

	// Click "Stay logged in" toggle so keys survive any page navigation during the test.
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
		} else {
			logCheckpoint('"Stay logged in" toggle was already on.');
		}
	} catch {
		logCheckpoint('Could not find "Stay logged in" toggle — proceeding without it.');
	}

	await page.getByRole('button', { name: /continue/i }).click();
	logCheckpoint('Entered email and clicked continue.');

	// Retry if 429 hit on lookup — the EmailLookup component hides the form
	// and shows a rate-limit message for 120s. To retry, we must clear the
	// rate-limit flag from localStorage and reload the login interface so the
	// form reappears. Max 3 retries with increasing back-off.
	for (let retryCount = 0; retryCount < 3 && hit429; retryCount++) {
		const waitSec = 5 + retryCount * 5;
		logCheckpoint(`Hit 429 rate limit on lookup, waiting ${waitSec}s before retry ${retryCount + 1}...`);
		hit429 = false;
		await page.waitForTimeout(waitSec * 1000);

		// Clear the client-side rate-limit flag so the form reappears
		await page.evaluate(() => {
			localStorage.removeItem('emailLookupRateLimit');
			localStorage.removeItem('loginRateLimit');
		});

		// Reload the page to reset the EmailLookup component state
		await page.goto(getE2EDebugUrl('/'));
		const retrySignupBtn = page.getByRole('button', { name: /login.*sign up|sign up/i });
		await expect(retrySignupBtn).toBeVisible({ timeout: 15000 });
		await retrySignupBtn.click();
		const retryLoginTab = page.locator('.login-tabs .tab-button', { hasText: /^login$/i });
		await expect(retryLoginTab).toBeVisible({ timeout: 10000 });
		await retryLoginTab.click();

		const retryEmailInput = page.locator('#login-email-input');
		await expect(retryEmailInput).toBeVisible({ timeout: 15000 });
		await retryEmailInput.fill(TEST_EMAIL);
		await page.getByRole('button', { name: /continue/i }).click();
		logCheckpoint(`Retry ${retryCount + 1}: re-entered email and clicked continue.`);
	}

	const passwordInput = page.locator('#login-password-input');
	await expect(passwordInput).toBeVisible({ timeout: 15000 });
	await passwordInput.fill(TEST_PASSWORD);
	await takeStepScreenshot(page, 'password-entered');

	const otpInput = page.locator('#login-otp-input');
	await expect(otpInput).toBeVisible({ timeout: 15000 });

	const submitLoginButton = page.locator('button[type="submit"]', { hasText: /log in|login/i });
	const errorMessage = page
		.locator('.error-message, [class*="error"]')
		.filter({ hasText: /wrong|invalid|incorrect/i });

	// OTP retry strategy: try current window, then adjacent windows to handle GHA clock drift.
	// GHA runners can have 1-2s clock skew from the server, causing the TOTP code to be
	// rejected. By cycling through window offsets [0, -1, 1, 0, -1] across 5 attempts,
	// we cover the current window and both adjacent windows.
	const MAX_OTP_ATTEMPTS = 5;
	const WINDOW_OFFSETS = [0, -1, 1, 0, -1];

	// Positive auth signal: ActiveChat.svelte sets data-authenticated="true" on the
	// container div when authStore.isAuthenticated becomes true. This is the most
	// reliable login success detector because it's driven directly by the canonical
	// auth state, not by UI visibility heuristics (which can race with animations).
	const authSignal = page.locator('[data-authenticated="true"]');

	let loginSuccess = false;
	for (let attempt = 1; attempt <= MAX_OTP_ATTEMPTS && !loginSuccess; attempt++) {
		// Avoid TOTP window boundary race: if we're in the last 5s of a 30s window,
		// wait for the next window so the generated code is valid long enough.
		const nowSec = Math.floor(Date.now() / 1000);
		const secondsIntoWindow = nowSec % 30;
		if (secondsIntoWindow >= 25) {
			const waitMs = (30 - secondsIntoWindow) * 1000 + 2000;
			logCheckpoint(`Near TOTP window boundary (${secondsIntoWindow}s in), waiting ${waitMs}ms...`);
			await page.waitForTimeout(waitMs);
		}

		const windowOffset = WINDOW_OFFSETS[attempt - 1];
		const otpCode = generateTotp(TEST_OTP_KEY, windowOffset);
		await otpInput.fill(otpCode);
		logCheckpoint(`Generated and entered OTP (attempt ${attempt}, window offset ${windowOffset}).`);
		if (attempt === 1) {
			await takeStepScreenshot(page, 'otp-entered');
		}

		await expect(submitLoginButton).toBeVisible();
		await submitLoginButton.click();
		logCheckpoint('Submitted login form.');

		try {
			// Primary success signal: data-authenticated="true" appears on the DOM.
			// This is set by ActiveChat.svelte when authStore.isAuthenticated becomes true,
			// which happens after setAuthenticatedState() runs in the login success chain.
			await expect(authSignal).toBeVisible({ timeout: 15000 });
			loginSuccess = true;
			logCheckpoint('Login successful — data-authenticated="true" detected.');
		} catch {
			const hasError = await errorMessage.isVisible().catch(() => false);
			if (hasError && attempt < MAX_OTP_ATTEMPTS) {
				logCheckpoint(`OTP attempt ${attempt} failed, retrying with different window offset...`);
				// Wait longer between retries to allow time window to advance.
				await page.waitForTimeout(attempt <= 2 ? 3000 : 5000);
			} else if (attempt === MAX_OTP_ATTEMPTS) {
				throw new Error(`Login failed after ${MAX_OTP_ATTEMPTS} OTP attempts`);
			}
		}
	}

	// Clean up 429 listener
	page.off('response', on429);

	const { waitForEditor = true } = options;
	if (waitForEditor) {
		logCheckpoint('Waiting for chat interface to load...');
		// Brief settle time for post-auth UI transitions (WebSocket connect, phased sync start).
		// Reduced from 3000ms — the auth state transition is now reliable (see fix in
		// PasswordAndTfaOtp.svelte handleSuccessfulLogin Phase 1/Phase 2 split).
		await page.waitForTimeout(1000);
		const messageEditor = page.locator('.editor-content.prose');
		await expect(messageEditor).toBeVisible({ timeout: 20000 });
		logCheckpoint('Chat interface loaded - message editor visible.');
	} else {
		logCheckpoint('Login complete (skipping editor wait).');
		await page.waitForTimeout(1000);
	}
}

/**
 * Start a new chat session by clicking the new chat button.
 * Handles sidebar-closed scenario with multiple fallback selectors.
 */
async function startNewChat(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void = noopLog
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
 * Uses [data-action="send-message"] for a stable selector.
 */
async function sendMessage(
	page: any,
	message: string,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void = noopLog,
	takeStepScreenshot: (page: any, label: string) => Promise<void> = noopScreenshot,
	stepLabel: string = 'msg'
): Promise<void> {
	const messageEditor = page.locator('.editor-content.prose');
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
	await takeStepScreenshot(page, `${stepLabel}-message-sent`);
}

/**
 * Delete the active chat via context menu (best-effort cleanup).
 * Does not fail the test if cleanup is not possible.
 */
async function deleteActiveChat(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void = noopLog,
	takeStepScreenshot: (page: any, label: string) => Promise<void> = noopScreenshot,
	stepLabel: string = 'cleanup'
): Promise<void> {
	logCheckpoint('Attempting to delete the chat (best-effort cleanup)...');

	try {
		const sidebarToggle = page.locator('[data-testid="sidebar-toggle"]');
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

/**
 * Wait for an assistant message to appear in the chat.
 */
async function waitForAssistantResponse(page: any, timeout = 60000): Promise<any> {
	const assistantMessage = page.locator('.message-wrapper.assistant');
	await expect(assistantMessage.first()).toBeVisible({ timeout });
	return assistantMessage;
}

module.exports = {
	loginToTestAccount,
	startNewChat,
	sendMessage,
	deleteActiveChat,
	waitForAssistantResponse
};
