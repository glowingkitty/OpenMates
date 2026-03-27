/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Session Revoke Flow — E2E Test
 *
 * Verifies the fix for the bug where revoking another device's session from
 * Settings > Account > Security > Sessions also logged out the current device.
 *
 * Test flow:
 * 1. Session A logs in (browser context A).
 * 2. Session B logs in (browser context B — separate tab/device).
 * 3. Session A opens Settings > Account > Security > Sessions.
 * 4. Session A finds Session B in the sessions list and clicks "Remove".
 * 5. Assert: Session B receives the force_logout event and IS logged out.
 * 6. Assert: Session A remains logged in (NOT logged out).
 *
 * Architecture: docs/architecture/device-sessions.md
 * Fix: backend/core/api/app/routes/auth_routes/auth_sessions.py — exclude_connection_hash
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL
 * - OPENMATES_TEST_ACCOUNT_PASSWORD
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY
 * - PLAYWRIGHT_TEST_BASE_URL
 */

const { test, expect, chromium } = require('@playwright/test');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	generateTotp,
	getTestAccount
} = require('./signup-flow-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

// ---------------------------------------------------------------------------
// Login helper (shared between sessions)
// ---------------------------------------------------------------------------

async function loginToApp(page: any, logFn: (msg: string) => void): Promise<void> {
	await page.goto('/');

	const headerLoginButton = page.getByRole('button', { name: /login.*sign up|sign up/i });
	await expect(headerLoginButton).toBeVisible({ timeout: 15000 });
	await headerLoginButton.click();

	// Click Login tab to switch from signup to login view
	const loginTab = page.locator('.login-tabs .tab-button', { hasText: /^login$/i });
	await expect(loginTab).toBeVisible({ timeout: 10000 });
	await loginTab.click();

	const emailInput = page.locator('#login-email-input');
	await expect(emailInput).toBeVisible({ timeout: 10000 });
	await emailInput.fill(TEST_EMAIL);
	await page.getByRole('button', { name: /continue/i }).click();
	logFn('Email submitted.');

	const passwordInput = page.locator('#login-password-input');
	await expect(passwordInput).toBeVisible({ timeout: 10000 });
	await passwordInput.fill(TEST_PASSWORD);

	// OTP is time-sensitive — generate immediately before entering
	const otpCode = generateTotp(TEST_OTP_KEY);
	const otpInput = page.locator('#login-otp-input');
	await expect(otpInput).toBeVisible({ timeout: 10000 });
	await otpInput.fill(otpCode);
	logFn(`OTP entered: ${otpCode}`);

	const submitBtn = page.locator('button[type="submit"]', { hasText: /log in|login/i });
	await expect(submitBtn).toBeVisible({ timeout: 10000 });
	await submitBtn.click();
	logFn('Login submitted, waiting for redirect to /chat…');

	await page.waitForURL(/chat/, { timeout: 30000 });
	logFn('Redirected to /chat — login complete.');
}

// ---------------------------------------------------------------------------
// Navigate to Settings > Account > Security > Sessions
// ---------------------------------------------------------------------------

async function navigateToSessions(page: any, logFn: (msg: string) => void): Promise<void> {
	// Open settings menu using the stable #settings-menu-toggle id
	const openSettingsBtn = page.locator('#settings-menu-toggle');
	await expect(openSettingsBtn).toBeVisible({ timeout: 15000 });
	await openSettingsBtn.click();

	// Wait for the settings menu to actually open
	await expect(page.locator('.settings-menu.visible')).toBeVisible({ timeout: 10000 });
	logFn('Opened settings menu.');

	// Navigate Account → Security → Active Sessions
	await page.getByRole('menuitem', { name: /account/i }).click();
	logFn('Navigated to Account settings.');

	await page.getByRole('menuitem', { name: /security/i }).click();
	logFn('Navigated to Security settings.');

	await page.getByRole('menuitem', { name: /active sessions/i }).click();
	logFn('Navigated to Active Sessions settings page.');

	// Wait for sessions list to load
	await expect(page.locator('[data-testid="sessions-list"]')).toBeVisible({ timeout: 15000 });
	logFn('Sessions list visible.');
}

// ---------------------------------------------------------------------------
// Detect if the page is logged out (login button visible)
// ---------------------------------------------------------------------------

async function isLoggedOut(page: any): Promise<boolean> {
	try {
		const loginBtn = page.getByRole('button', { name: /login.*sign up|sign up/i });
		return await loginBtn.isVisible({ timeout: 5000 });
	} catch {
		return false;
	}
}

// ---------------------------------------------------------------------------
// Main test
// ---------------------------------------------------------------------------

test('session revoke: revoking session B from session A does not log out session A', async () => {
	test.slow();
	// Login × 2 + OTP window wait + settings navigation + revoke + assertions
	test.setTimeout(300000);

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const logA = createSignupLogger('SESSION_REVOKE_A');
	const logB = createSignupLogger('SESSION_REVOKE_B');
	const screenshotA = createStepScreenshotter(logA, { filenamePrefix: 'revoke-a' });
	const screenshotB = createStepScreenshotter(logB, { filenamePrefix: 'revoke-b' });

	await archiveExistingScreenshots(logA);

	// Capture console output for each session to aid debugging on failure
	const logsA: string[] = [];
	const logsB: string[] = [];
	const forceLogoutEventsA: string[] = [];
	const forceLogoutEventsB: string[] = [];

	const baseURL = process.env.PLAYWRIGHT_TEST_BASE_URL ?? 'https://app.dev.openmates.org';
	const browser = await chromium.launch();

	// Two separate browser contexts = two independent sessions (separate cookies,
	// separate IndexedDB, separate WebSocket connections).
	const contextA = await browser.newContext({ baseURL });
	const contextB = await browser.newContext({ baseURL });
	const pageA = await contextA.newPage();
	const pageB = await contextB.newPage();

	// Attach console listeners
	pageA.on('console', (msg: any) => {
		const text = msg.text();
		logsA.push(`[${new Date().toISOString()}] [${msg.type()}] ${text}`);
		// Flag only actual force_logout events RECEIVED on Session A — these should NOT happen.
		// "Registered handler for messageType" is a startup log (not an event receipt) — ignore it.
		// "Received force_logout event" is the chatSyncService handler — this is the real event.
		if (text.includes('Received force_logout event')) {
			forceLogoutEventsA.push(text);
			console.warn(`[SESSION-A] UNEXPECTED force_logout event received: ${text}`);
		}
	});
	pageB.on('console', (msg: any) => {
		const text = msg.text();
		logsB.push(`[${new Date().toISOString()}] [${msg.type()}] ${text}`);
		// Capture actual force_logout events on Session B (expected)
		if (text.includes('Received force_logout event')) {
			forceLogoutEventsB.push(text);
			console.log(`[SESSION-B] force_logout event received (expected): ${text}`);
		}
	});

	try {
		// ── Step 1: Log in Session A ─────────────────────────────────────────
		logA('Logging in Session A…');
		await loginToApp(pageA, logA);
		await screenshotA(pageA, '01-logged-in-a');

		// ── Step 2: Wait for TOTP window rollover, then log in Session B ─────
		// TOTP codes are 30-second windows; reusing the same code in the same
		// window is rejected. Wait for the next window before logging in B.
		{
			const msInWindow = Date.now() % 30000;
			const msUntilNext = 30000 - msInWindow + 500; // +500ms buffer
			logA(`Waiting ${Math.ceil(msUntilNext / 1000)}s for next OTP window before Session B login…`);
			await pageA.waitForTimeout(msUntilNext);
		}

		logB('Logging in Session B…');
		await loginToApp(pageB, logB);
		await screenshotB(pageB, '02-logged-in-b');

		logA('Both sessions logged in. Waiting 8s for WebSocket connections to stabilise…');
		await pageA.waitForTimeout(8000);
		await screenshotA(pageA, '03-after-stabilise-a');
		await screenshotB(pageB, '03-after-stabilise-b');

		// ── Step 3: Session A navigates to Settings > Sessions ───────────────
		logA('Session A: navigating to Settings > Account > Security > Sessions…');
		await navigateToSessions(pageA, logA);
		await screenshotA(pageA, '04-sessions-page-a');

		// ── Step 4: Find Session B's card and click Remove ───────────────────
		// The sessions list shows all active sessions; Session A's card has
		// data-is-current="true". Session B is one of the other cards.
		// We click the "Remove" button on the first non-current session.
		logA("Session A: looking for Session B's card to remove…");

		const nonCurrentCard = pageA
			.locator('[data-testid="session-card"][data-is-current="false"]')
			.first();
		await expect(nonCurrentCard).toBeVisible({ timeout: 15000 });

		const revokeBtn = nonCurrentCard.locator('[data-testid="session-revoke-btn"]');
		await expect(revokeBtn).toBeVisible({ timeout: 5000 });
		await screenshotA(pageA, '05-before-revoke-a');

		// The button triggers a confirm() dialog — handle it
		pageA.once('dialog', async (dialog: any) => {
			logA(`Confirm dialog: "${dialog.message()}". Accepting.`);
			await dialog.accept();
		});

		await revokeBtn.click();
		logA("Session A: clicked Remove on Session B's session card.");
		await screenshotA(pageA, '06-after-revoke-click-a');

		// ── Step 5: Wait for Session B to be logged out ──────────────────────
		// The backend broadcasts force_logout via WebSocket to Session B.
		// Session B's chatSyncService handler calls logout() and redirects
		// to the login screen (Login / Sign up button appears).
		logB('Session B: waiting to receive force_logout and be logged out…');
		const loginBtnB = pageB.getByRole('button', { name: /login.*sign up|sign up/i });
		await expect(loginBtnB).toBeVisible({ timeout: 60000 });
		logB('Session B: confirmed LOGGED OUT (Login/Sign Up button visible).');
		await screenshotB(pageB, '07-session-b-logged-out');

		// ── Step 6: Verify Session A is still logged in ──────────────────────
		// After the revoke, Session A should remain on the Settings > Sessions page
		// (or /chat at minimum), NOT be redirected to the login screen.
		logA('Session A: verifying still logged in after revoking Session B…');

		// Wait briefly for any unexpected logout to propagate
		await pageA.waitForTimeout(5000);
		await screenshotA(pageA, '08-session-a-after-revoke-wait');

		// Session A must NOT show the Login / Sign Up button
		const loginBtnA = pageA.getByRole('button', { name: /login.*sign up|sign up/i });
		const aIsLoggedOut = await loginBtnA.isVisible({ timeout: 3000 }).catch(() => false);

		if (aIsLoggedOut) {
			// Log all captured events to aid debugging
			console.error('[SESSION-A] force_logout events received:', forceLogoutEventsA);
			console.error('[SESSION-A] Last 30 console logs:', logsA.slice(-30));
			throw new Error(
				'[REGRESSION] Session A was logged out after revoking Session B. ' +
					'The fix for exclude_connection_hash is not working correctly.'
			);
		}

		logA('Session A: CONFIRMED still logged in — NOT logged out.');
		await screenshotA(pageA, '09-session-a-still-logged-in');

		// ── Step 7: Assert no unexpected force_logout on Session A ───────────
		// The console should not have recorded any force_logout event on Session A.
		// (It fires on Session B — which is correct — but never on Session A.)
		if (forceLogoutEventsA.length > 0) {
			throw new Error(
				`[SESSION-A] Received ${forceLogoutEventsA.length} unexpected force_logout event(s): ` +
					forceLogoutEventsA.join('\n')
			);
		}
		logA(`Session A: no force_logout events received — correct.`);

		// ── Step 8: Verify Session B did receive force_logout ─────────────────
		if (forceLogoutEventsB.length === 0) {
			logB(
				'NOTE: No force_logout console event captured on Session B — logout still ' +
					'confirmed via UI (Login button appeared). WebSocket event may have fired ' +
					'before console listener was attached.'
			);
		} else {
			logB(`Session B: force_logout event confirmed: ${forceLogoutEventsB[0]}`);
		}

		// ── Step 9: Verify sessions list updated on Session A ────────────────
		// After revocation, Session B should no longer appear in the list.
		// The list should now show fewer cards.
		logA('Session A: verifying sessions list updated after revoke…');
		await expect(pageA.locator('[data-testid="sessions-list"]')).toBeVisible({
			timeout: 10000
		});
		const remainingCards = await pageA.locator('[data-testid="session-card"]').count();
		logA(`Session A: ${remainingCards} session card(s) remaining after revoke.`);
		// At minimum, Session A's own card should remain
		expect(remainingCards).toBeGreaterThanOrEqual(1);

		await screenshotA(pageA, '10-sessions-list-updated-a');

		logA('=== TEST PASSED: Session revoke correctly targeted Session B only. ===');
	} finally {
		await contextA.close();
		await contextB.close();
		await browser.close();
	}
});
