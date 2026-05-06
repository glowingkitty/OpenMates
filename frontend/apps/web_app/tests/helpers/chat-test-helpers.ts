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
	// Wait for all resources (scripts + hydration) to load before checking buttons.
	await page.waitForLoadState('load');

	// Clear any rate-limit flags from previous test runs that would hide the login form
	await page.evaluate(() => {
		localStorage.removeItem('emailLookupRateLimit');
		localStorage.removeItem('loginRateLimit');
		localStorage.removeItem('passwordTfaRateLimit');
	});

	await takeStepScreenshot(page, 'home');

	// The intro banner on the home page hides the header login button and shows its own.
	await openSignupInterface(page, 30000);
	await takeStepScreenshot(page, 'signup-interface-opened');

	// Click the "Login" tab in the login/signup tab bar to switch to the login form
	const loginTab = page.getByTestId('tab-login');
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
		await page.waitForLoadState('load');
		await openSignupInterface(page, 30000);
		const retryLoginTab = page.getByTestId('tab-login');
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

	// Submit password first — OTP field only appears after backend confirms 2FA is required
	// (anti-enumeration: OTP is never shown upfront, only after first login attempt).
	const submitLoginButton = page.locator('button[type="submit"]', { hasText: /log in|login/i });
	await expect(submitLoginButton).toBeVisible();
	await submitLoginButton.click();
	logCheckpoint('Submitted password — waiting for 2FA prompt or direct login.');

	// Positive auth signal: ActiveChat.svelte sets data-authenticated="true" on the
	// container div when authStore.isAuthenticated becomes true. This is the most
	// reliable login success detector because it's driven directly by the canonical
	// auth state, not by UI visibility heuristics (which can race with animations).
	const authSignal = page.locator('[data-authenticated="true"]');
	const otpInput = page.locator('#login-otp-input');

	// Race: either OTP field appears (2FA required) or login succeeds immediately
	// (2FA not configured for this account). Some test accounts may have lost their
	// encrypted_tfa_secret, causing the backend to bypass 2FA entirely.
	const otpOrAuth = await Promise.race([
		otpInput.waitFor({ state: 'visible', timeout: 15000 }).then(() => 'otp' as const),
		authSignal.waitFor({ state: 'visible', timeout: 15000 }).then(() => 'auth' as const),
	]);

	let loginSuccess = false;

	if (otpOrAuth === 'auth') {
		// Login succeeded without 2FA — backend determined tfa_enabled=false
		loginSuccess = true;
		logCheckpoint('Login successful without 2FA — data-authenticated="true" detected.');
	} else {
		// OTP field appeared — proceed with TOTP entry
		logCheckpoint('2FA prompt visible — entering OTP.');

		const errorMessage = page
			.getByTestId('error-message')
			.filter({ hasText: /wrong|invalid|incorrect/i });

		// OTP retry strategy: try current window, then adjacent windows to handle GHA clock drift.
		// GHA runners can have 1-2s clock skew from the server, causing the TOTP code to be
		// rejected. By cycling through window offsets [0, -1, 1, 0, -1] across 5 attempts,
		// we cover the current window and both adjacent windows.
		const MAX_OTP_ATTEMPTS = 5;
		const WINDOW_OFFSETS = [0, -1, 1, 0, -1];

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
		const messageEditor = page.getByTestId('message-editor');
		await expect(messageEditor).toBeVisible({ timeout: 20000 });
		logCheckpoint('Chat interface loaded - message editor visible.');
	} else {
		logCheckpoint('Login complete (skipping editor wait).');
		await page.waitForTimeout(1000);
	}
}

/**
 * Submit password and handle OTP if required. For use by specs with inline login code.
 *
 * After filling the password input and calling this function, it will:
 * 1. Click the submit button
 * 2. Race: wait for either OTP field or data-authenticated="true"
 * 3. If OTP field appears: fill OTP with TOTP retry logic and submit
 * 4. If auth signal appears: login succeeded without 2FA
 *
 * @param page      - Playwright Page
 * @param otpKey    - TOTP secret key for generating OTP codes
 * @param log       - Optional log function
 */
async function submitPasswordAndHandleOtp(
	page: any,
	otpKey: string,
	log: (msg: string) => void = () => {}
): Promise<void> {
	const submitBtn = page.locator('button[type="submit"]', { hasText: /log in|login/i });
	await expect(submitBtn).toBeVisible();
	await submitBtn.click();
	log('Submitted password — waiting for 2FA prompt or direct login.');

	const authSignal = page.locator('[data-authenticated="true"]');
	const otpInput = page.locator('#login-otp-input');

	const otpOrAuth = await Promise.race([
		otpInput.waitFor({ state: 'visible', timeout: 15000 }).then(() => 'otp' as const),
		authSignal.waitFor({ state: 'visible', timeout: 15000 }).then(() => 'auth' as const),
	]);

	if (otpOrAuth === 'auth') {
		log('Login successful without 2FA.');
		// Brief settle for post-auth navigation (URL change, WebSocket connect).
		// Auth signal fires before the router navigates to the chat view.
		await page.waitForTimeout(2000);
		return;
	}

	log('2FA prompt visible — entering OTP.');
	const MAX_OTP_ATTEMPTS = 5;
	const WINDOW_OFFSETS = [0, -1, 1, 0, -1];

	for (let attempt = 1; attempt <= MAX_OTP_ATTEMPTS; attempt++) {
		const nowSec = Math.floor(Date.now() / 1000);
		const secondsIntoWindow = nowSec % 30;
		if (secondsIntoWindow >= 25) {
			await page.waitForTimeout((30 - secondsIntoWindow) * 1000 + 2000);
		}

		const otpCode = generateTotp(otpKey, WINDOW_OFFSETS[attempt - 1]);
		await otpInput.fill(otpCode);
		log(`OTP attempt ${attempt}, offset ${WINDOW_OFFSETS[attempt - 1]}.`);

		await expect(submitBtn).toBeVisible();
		await submitBtn.click();

		try {
			await expect(authSignal).toBeVisible({ timeout: 15000 });
			log('Login successful — data-authenticated="true" detected.');
			return;
		} catch {
			if (attempt === MAX_OTP_ATTEMPTS) {
				throw new Error(`Login failed after ${MAX_OTP_ATTEMPTS} OTP attempts`);
			}
			log(`OTP attempt ${attempt} failed, retrying...`);
			await page.waitForTimeout(attempt <= 2 ? 3000 : 5000);
		}
	}
}

/**
 * Start a new chat session by clicking the new chat button.
 * Uses data-testid and data-action for stable selectors.
 */
async function startNewChat(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void = noopLog
): Promise<void> {
	await page.waitForTimeout(1000);

	const currentUrl = page.url();
	logCheckpoint(`Current URL before starting new chat: ${currentUrl}`);

	// If the editor has focus, the adjacent new-chat CTA is intentionally hidden.
	// Blur before probing selectors so we do not create fake draft state just to
	// reveal the button.
	await page.keyboard.press('Escape').catch(() => undefined);
	await page.locator('body').click({ position: { x: 1, y: 1 }, timeout: 1000 }).catch(() => undefined);
	await page.waitForTimeout(300);

	// Try stable selectors in priority order
	const newChatButton = page.getByTestId('new-chat-button');
	let clicked = false;

	if (await newChatButton.isVisible({ timeout: 3000 }).catch(() => false)) {
		logCheckpoint('Found New Chat button via data-testid');
		await newChatButton.click();
		clicked = true;
		await page.waitForTimeout(2000);
	}

	if (!clicked) {
		// Fallback: try data-action attribute
		const actionButton = page.locator('[data-action="new-chat"]').first();
		if (await actionButton.isVisible({ timeout: 3000 }).catch(() => false)) {
			logCheckpoint('Found New Chat button via data-action');
			await actionButton.click();
			clicked = true;
			await page.waitForTimeout(2000);
		}
	}

	if (!clicked) {
		// Fallback: try aria-label
		const ariaButton = page.locator('button[aria-label*="New"], button[aria-label*="new"]').first();
		if (await ariaButton.isVisible({ timeout: 3000 }).catch(() => false)) {
			logCheckpoint('Found New Chat button via aria-label');
			await ariaButton.click();
			clicked = true;
			await page.waitForTimeout(2000);
		}
	}

	if (!clicked) {
		const messageEditor = page.getByTestId('message-editor');
		if (await messageEditor.isVisible({ timeout: 3000 }).catch(() => false)) {
			logCheckpoint('New Chat button not visible; editor is already ready, treating page as new chat.');
		} else {
			logCheckpoint('WARNING: Could not find New Chat button or ready message editor.');
		}
	}

	const newUrl = page.url();
	logCheckpoint(`URL after attempting to start new chat: ${newUrl}`);
}

/**
 * Send a message in the chat editor and wait for the send to complete.
 * Uses data-testid and data-action for stable selectors.
 */
async function sendMessage(
	page: any,
	message: string,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void = noopLog,
	takeStepScreenshot: (page: any, label: string) => Promise<void> = noopScreenshot,
	stepLabel: string = 'msg'
): Promise<void> {
	const messageEditor = page.getByTestId('message-editor');
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
		const sidebarToggle = page.getByTestId('sidebar-toggle');
		if (await sidebarToggle.isVisible()) {
			await sidebarToggle.click();
			await page.waitForTimeout(500);
		}

		const activeChatItem = page.locator('[data-testid="chat-item-wrapper"].active');

		if (!(await activeChatItem.isVisible({ timeout: 5000 }).catch(() => false))) {
			logCheckpoint('No active chat item visible - skipping cleanup.');
			return;
		}

		// Identify demo / legal chats by their chat_id prefix (see
		// frontend/packages/ui/src/demo_chats/convertToChat.ts:isDemoChat /
		// isLegalChat). Title-based detection used to false-match any legitimate
		// chat whose title happened to contain "OpenMates" (e.g. "Search OpenMates
		// AI assistant" from skill-web-search.spec.ts), which made the cleanup
		// return early and triggered a cascade console-monitor assertion failure.
		// The chat-item-wrapper carries data-chat-id — use that as the canonical
		// identity source.
		try {
			const chatId = await activeChatItem.getAttribute('data-chat-id');
			const chatTitle = await activeChatItem
				.getByTestId('chat-title')
				.textContent()
				.catch(() => null);
			logCheckpoint(
				`Active chat: id="${chatId ?? 'unknown'}" title="${chatTitle ?? 'unknown'}"`
			);

			if (chatId && (chatId.startsWith('demo-') || chatId.startsWith('legal-'))) {
				logCheckpoint(`Skipping deletion - ${chatId} is a demo/legal chat.`);
				return;
			}
		} catch {
			logCheckpoint('Could not read active chat identity.');
		}

		await activeChatItem.click({ button: 'right', timeout: 5000 });
		await takeStepScreenshot(page, `${stepLabel}-context-menu-open`);
		logCheckpoint('Opened chat context menu.');

		await page.waitForTimeout(300);
		const deleteButton = page.getByTestId('chat-context-delete');

		if (!(await deleteButton.isVisible({ timeout: 3000 }).catch(() => false))) {
			logCheckpoint('Delete button not visible in context menu - skipping cleanup.');
			await page.keyboard.press('Escape');
			return;
		}

		// Bound every click with an explicit 5s timeout. Without these, a flaky
		// context-menu render (button briefly obscured, overlay intercepts, etc.)
		// would cause .click() to wait up to the entire test timeout (240s+)
		// before throwing, eating all remaining budget and marking an otherwise-
		// successful test as timedOut during this non-fatal cleanup.
		await deleteButton.click({ timeout: 5000 });
		await takeStepScreenshot(page, `${stepLabel}-delete-confirm-mode`);
		logCheckpoint('Clicked delete, now in confirm mode.');

		await deleteButton.click({ timeout: 5000 });
		logCheckpoint('Confirmed chat deletion.');

		await expect(activeChatItem).not.toBeVisible({ timeout: 10000 });
		await takeStepScreenshot(page, `${stepLabel}-chat-deleted`);
		logCheckpoint('Verified chat deletion successfully.');
	} catch (error) {
		// Best-effort cleanup — never let a cleanup hang eat the test timeout.
		// Try to dismiss any stuck context menu so subsequent tests see a
		// clean state.
		logCheckpoint(`Cleanup failed (non-fatal): ${error}`);
		try {
			await page.keyboard.press('Escape');
		} catch {
			/* noop */
		}
	}
}

/**
 * Wait for an assistant message to appear in the chat.
 */
async function waitForAssistantResponse(page: any, timeout = 60000): Promise<any> {
	const assistantMessage = page.getByTestId('message-assistant');
	await expect(assistantMessage.first()).toBeVisible({ timeout });
	return assistantMessage;
}

/**
 * Wait for the chat UI to be ready for sending a message after login.
 *
 * Addresses a common flake: specs that send a message immediately after
 * `loginToTestAccount` occasionally race the initial WebSocket connect /
 * phased sync, causing the message to be sent before chatSyncService has
 * finished its startup handshake. The symptom downstream is that the
 * assistant response element never renders (or renders into a chat that
 * is then rehydrated and lost).
 *
 * Preconditions checked:
 *  1. `data-authenticated="true"` marker is present (set by ActiveChat.svelte
 *     when authStore.isAuthenticated flips to true).
 *  2. `message-editor` is visible.
 *  3. The send button is present in the DOM (proves MessageInput fully mounted).
 */
async function waitForChatReady(
	page: any,
	logCheckpoint: (message: string, metadata?: Record<string, unknown>) => void = noopLog,
	timeout = 30000
): Promise<void> {
	const start = Date.now();
	const budget = () => Math.max(1000, timeout - (Date.now() - start));

	await expect(page.locator('[data-authenticated="true"]')).toBeVisible({ timeout: budget() });
	await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: budget() });
	await expect(page.locator('[data-action="send-message"]')).toHaveCount(1, { timeout: budget() });

	// Small post-mount settle: the MessageInput mounts before chatSyncService finishes
	// its initial WS handshake. 1.5s matches the pattern in chat-flow.spec.ts which
	// passes reliably on nightly.
	await page.waitForTimeout(1500);

	logCheckpoint('Chat UI ready: authenticated + editor + send button mounted.');
}

/**
 * Robust wait for an assistant message. Replaces the fragile pattern
 *   `await expect(page.getByTestId('message-assistant').last()).toBeVisible({ timeout: 45000 })`
 * which was failing ~9 nightly specs whenever CI AI latency exceeded the hard-coded
 * timeout or when multiple messages were being rendered.
 *
 * Lifecycle modelled here:
 *  1. Stream-started gate: wait for either a `typing-indicator` or a new
 *     `message-assistant` element to appear (max 30s).
 *  2. Visibility: wait for the targeted `message-assistant.{first|last|nth}` to be visible.
 *  3. Optional text anchor (`contains`) — same mechanism `chat-flow.spec.ts` uses
 *     (await expect(msg).toContainText('Berlin', { timeout })).
 *
 * Defaults to a generous 120s total timeout to cover slow GitHub Actions AI latency
 * while remaining well under the 6-minute Playwright default.
 *
 * @param opts.which  'first' | 'last' (default 'last')
 * @param opts.nth    Zero-based index; overrides `which` when provided.
 * @param opts.contains  Text that must appear in the message body.
 * @param opts.timeout  Total budget in ms (default 120000).
 * @returns The Playwright Locator for the matched assistant message.
 */
async function waitForAssistantMessage(
	page: any,
	opts: {
		which?: 'first' | 'last';
		nth?: number;
		contains?: string | RegExp;
		timeout?: number;
		logCheckpoint?: (message: string, metadata?: Record<string, unknown>) => void;
	} = {}
): Promise<any> {
	const {
		which = 'last',
		nth,
		contains,
		timeout = 120000,
		logCheckpoint = noopLog
	} = opts;

	const start = Date.now();
	const budget = () => Math.max(1000, timeout - (Date.now() - start));

	// Stage 1 — stream-started gate.
	// Wait for any evidence that the AI pipeline has accepted the message.
	// Either the typing-indicator appears, or an assistant message begins rendering.
	const streamStartGate = page.locator(
		'[data-testid="typing-indicator"], [data-testid="message-assistant"]'
	);
	const gateTimeout = Math.min(30000, budget());
	try {
		await expect(streamStartGate.first()).toBeVisible({ timeout: gateTimeout });
		logCheckpoint('Assistant stream started (typing indicator or message bubble appeared).');
	} catch (err) {
		throw new Error(
			`waitForAssistantMessage: stream never started within ${gateTimeout}ms ` +
				`(neither typing-indicator nor message-assistant appeared). Original: ${err}`
		);
	}

	// Stage 2 — target the specific assistant message and wait for it to render.
	const assistantMessages = page.getByTestId('message-assistant');
	const target =
		typeof nth === 'number'
			? assistantMessages.nth(nth)
			: which === 'first'
				? assistantMessages.first()
				: assistantMessages.last();

	await expect(target).toBeVisible({ timeout: budget() });
	logCheckpoint(`Assistant message visible (${nth !== undefined ? `nth=${nth}` : which}).`);

	// Stage 3 — optional text anchor.
	if (contains !== undefined) {
		await expect(target).toContainText(contains, { timeout: budget() });
		logCheckpoint(`Assistant message contains expected text: ${String(contains)}`);
	}

	return target;
}

/**
 * Returns true if the login/signup interface can be opened (either the banner button
 * or the header button is visible). Use instead of checking `header-login-signup-btn`
 * directly — that button is intentionally hidden while the intro banner is visible.
 */
async function isSignupInterfaceVisible(page: any, timeout = 5000): Promise<boolean> {
	const bannerBtn = page.getByTestId('banner-signup-button');
	const headerBtn = page.getByTestId('header-login-signup-btn');
	const bannerVisible = await bannerBtn.isVisible({ timeout }).catch(() => false);
	if (bannerVisible) return true;
	return headerBtn.isVisible({ timeout: 1000 }).catch(() => false);
}

/**
 * Open the login/signup dialog.
 *
 * When the intro banner is in the viewport (the app hides the header button to avoid
 * a duplicate CTA), clicks the banner's own signup button instead. Falls back to the
 * header button once the banner has scrolled out of view.
 *
 * Use this instead of `page.getByTestId('header-login-signup-btn')` + `toBeVisible()`
 * directly — the header button is intentionally hidden while the banner is visible.
 */
async function openSignupInterface(page: any, timeout = 15000): Promise<void> {
	const bannerBtn = page.getByTestId('banner-signup-button');
	const headerBtn = page.getByTestId('header-login-signup-btn');
	const bannerVisible = await bannerBtn.isVisible({ timeout: 8000 }).catch(() => false);
	if (bannerVisible) {
		await bannerBtn.click();
	} else {
		await expect(headerBtn).toBeVisible({ timeout });
		await headerBtn.click();
	}
}

module.exports = {
	loginToTestAccount,
	submitPasswordAndHandleOtp,
	openSignupInterface,
	isSignupInterfaceVisible,
	startNewChat,
	sendMessage,
	deleteActiveChat,
	waitForAssistantResponse,
	waitForChatReady,
	waitForAssistantMessage
};
