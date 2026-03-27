/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};
// NOTE:
// This file is executed inside the official Playwright Docker image, which
// provides the @playwright/test module at runtime. To keep repo-wide TypeScript
// checks happy without requiring local Playwright installation, we use CommonJS
// require() and broad lint disables limited to this spec file.
const { test, expect } = require('@playwright/test');
const { skipWithoutCredentials } = require('./helpers/env-guard');

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
	setToggleChecked,
	generateTotp,
	assertNoMissingTranslations,
	getTestAccount,
	getE2EDebugUrl
} = require('./signup-flow-helpers');

const { loginToTestAccount } = require('./helpers/chat-test-helpers');

/**
 * Backup codes SETTINGS test — validates the standalone "Reset Backup Codes"
 * feature in Settings > Account > Security > Two-Factor Authentication.
 *
 * ARCHITECTURE NOTES:
 * - Uses the existing test account (must have password + 2FA configured).
 * - Phase 1: Logs in with password + OTP.
 * - Phase 2: Navigates to Settings > Security > 2FA, clicks "Reset Backup Codes".
 * - Phase 3: Authenticates via SecurityAuth (password + OTP).
 * - Phase 4: Verifies new backup codes are displayed (count, format XXXX-XXXX-XXXX).
 * - Phase 5: Confirms codes stored, verifies success message on overview.
 *
 * This does NOT test login with backup codes (see backup-code-login-flow.spec.ts).
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL: Email of the existing test account.
 * - OPENMATES_TEST_ACCOUNT_PASSWORD: Password for the test account.
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY: 2FA secret key for the test account.
 */

const {
	email: OPENMATES_TEST_ACCOUNT_EMAIL,
	password: OPENMATES_TEST_ACCOUNT_PASSWORD,
	otpKey: OPENMATES_TEST_ACCOUNT_OTP_KEY
} = getTestAccount();

test('resets backup codes via Settings > Security > 2FA', async ({
	page,
	context
}: {
	page: any;
	context: any;
}) => {
	// Listen for console logs
	page.on('console', (msg: any) => {
		const timestamp = new Date().toISOString();
		consoleLogs.push(`[${timestamp}] [${msg.type()}] ${msg.text()}`);
	});

	// Listen for network requests
	page.on('request', (request: any) => {
		const timestamp = new Date().toISOString();
		networkActivities.push(`[${timestamp}] >> ${request.method()} ${request.url()}`);
	});

	// Listen for network responses
	page.on('response', (response: any) => {
		const timestamp = new Date().toISOString();
		networkActivities.push(`[${timestamp}] << ${response.status()} ${response.url()}`);
	});

	test.slow();
	test.setTimeout(120000);

	const logCheckpoint = createSignupLogger('BACKUP_CODES_SETTINGS');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'backup-codes-settings'
	});

	await archiveExistingScreenshots(logCheckpoint);

	// Validate required environment variables
	skipWithoutCredentials(test, OPENMATES_TEST_ACCOUNT_EMAIL, OPENMATES_TEST_ACCOUNT_PASSWORD, OPENMATES_TEST_ACCOUNT_OTP_KEY);

	// Grant clipboard permissions for "Copy" actions
	await context.grantPermissions(['clipboard-read', 'clipboard-write']);

	logCheckpoint('Starting backup codes settings test.', {
		email: OPENMATES_TEST_ACCOUNT_EMAIL
	});

	// ========================================================================
	// PHASE 1: Login with password + OTP (via shared helper with clock-drift compensation)
	// ========================================================================

	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot, { waitForEditor: false });
	logCheckpoint('Login successful.');
	await takeStepScreenshot(page, 'logged-in');

	// ========================================================================
	// PHASE 2: Navigate to Settings > Security > 2FA
	// ========================================================================

	// Open settings
	const settingsMenuButton = page.locator('#settings-menu-toggle');
	await settingsMenuButton.click();
	await expect(page.locator('.settings-menu.visible')).toBeVisible();
	await takeStepScreenshot(page, 'settings-open');
	logCheckpoint('Opened settings menu.');

	// Navigate: Account -> Security -> Two-Factor Authentication
	await page.getByRole('menuitem', { name: /account/i }).click();
	logCheckpoint('Navigated to Account settings.');

	await page.getByRole('menuitem', { name: /security/i }).click();
	logCheckpoint('Navigated to Security settings.');

	await page.getByRole('menuitem', { name: /two-factor|2fa/i }).click();
	await takeStepScreenshot(page, 'tfa-overview');
	logCheckpoint('Navigated to 2FA settings.');

	// ========================================================================
	// PHASE 3: Click "Reset Backup Codes" and authenticate
	// ========================================================================

	// Click "Reset Backup Codes" button (secondary button in action-buttons)
	const resetCodesButton = page
		.locator('button.btn-secondary')
		.filter({ hasText: /reset.*backup.*codes/i });
	await expect(resetCodesButton).toBeVisible({ timeout: 10000 });
	await resetCodesButton.click();
	await takeStepScreenshot(page, 'reset-codes-clicked');
	logCheckpoint('Clicked Reset Backup Codes button.');

	// SecurityAuth modal: enter password
	const authModal = page.locator('[role="dialog"]');
	await expect(authModal).toBeVisible({ timeout: 10000 });
	const authPasswordInput = authModal.locator('.password-input, input[type="password"]');
	await expect(authPasswordInput).toBeVisible();
	await authPasswordInput.fill(OPENMATES_TEST_ACCOUNT_PASSWORD);
	await authModal.locator('.auth-btn').click();
	await takeStepScreenshot(page, 'auth-password');
	logCheckpoint('Submitted password in SecurityAuth.');

	// If 2FA required in SecurityAuth, enter OTP
	const authTfaInput = authModal.locator('.tfa-input');
	const authTfaVisible = await authTfaInput.isVisible({ timeout: 5000 }).catch(() => false);
	if (authTfaVisible) {
		const authOtp = generateTotp(OPENMATES_TEST_ACCOUNT_OTP_KEY);
		await authTfaInput.fill(authOtp);
		// Auto-submits on 6 digits
		logCheckpoint('Entered OTP in SecurityAuth.');
	}

	// ========================================================================
	// PHASE 4: Verify backup codes are displayed
	// ========================================================================

	// Wait for backup codes container to appear
	const backupCodesContainer = page.locator('.tfa-backup-codes');
	await expect(backupCodesContainer).toBeVisible({ timeout: 20000 });
	await takeStepScreenshot(page, 'backup-codes-displayed');
	logCheckpoint('Backup codes displayed after reset.');

	// Read all backup codes from the UI
	const codeElements = page.locator('.code-item code');
	const codeCount = await codeElements.count();
	expect(codeCount, 'Expected 5 backup codes to be displayed.').toBe(5);
	logCheckpoint('Verified 5 backup codes displayed.', { count: codeCount });

	// Verify code format: XXXX-XXXX-XXXX
	const backupCodes: string[] = [];
	for (let i = 0; i < codeCount; i++) {
		const code = await codeElements.nth(i).textContent();
		if (code) {
			const trimmed = code.trim();
			backupCodes.push(trimmed);
			expect(trimmed, `Backup code ${i + 1} should match XXXX-XXXX-XXXX format.`).toMatch(
				/^[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$/
			);
		}
	}
	logCheckpoint('Verified all backup code formats.', { codes: backupCodes.length });

	// ========================================================================
	// PHASE 5: Confirm codes stored and verify success
	// ========================================================================

	// Check the confirmation checkbox
	const confirmCheckbox = page.locator('.confirm-checkbox input[type="checkbox"]');
	await setToggleChecked(confirmCheckbox, true);
	await expect(confirmCheckbox).toBeChecked();
	logCheckpoint('Checked confirmation checkbox.');

	// Click "Done" button (reset flow uses "Done" instead of "Complete Setup")
	const doneButton = backupCodesContainer.locator('button.btn-primary');
	await expect(doneButton).toBeEnabled();
	await doneButton.click();
	logCheckpoint('Clicked Done to confirm codes stored.');

	// Wait for return to overview with success message
	const successMessage = page.locator('.success-message');
	await expect(successMessage).toBeVisible({ timeout: 10000 });
	await takeStepScreenshot(page, 'reset-codes-success');
	logCheckpoint('Success message visible on overview.');

	// Verify we're back on the overview (Change App button should be visible)
	const changeAppButton = page.locator('button.btn-primary').filter({ hasText: /change.*app/i });
	await expect(changeAppButton).toBeVisible({ timeout: 5000 });
	logCheckpoint('Back on 2FA overview with Change App button.');

	// ========================================================================
	// PHASE 6: Logout
	// ========================================================================

	// Navigate back to main settings where the logout item lives.
	// Click the settings header back button repeatedly until logout is visible.
	const logoutItem = page.getByRole('menuitem', { name: /logout|abmelden/i });
	const settingsBackButton = page.locator('#settings-back-button');
	for (let i = 0; i < 5; i++) {
		const logoutNowVisible = await logoutItem.isVisible().catch(() => false);
		if (logoutNowVisible) break;
		const backVisible = await settingsBackButton.isVisible().catch(() => false);
		if (!backVisible) break;
		const backDisabled =
			(await settingsBackButton.getAttribute('aria-disabled').catch(() => 'true')) === 'true';
		if (backDisabled) break;
		await settingsBackButton.click();
		await page.waitForTimeout(500);
	}

	await expect(logoutItem).toBeVisible({ timeout: 10000 });
	await logoutItem.click();
	await takeStepScreenshot(page, 'logged-out');
	logCheckpoint('Logged out.');

	// Wait for redirect to demo chat (logged out state)
	await page.waitForFunction(() => window.location.hash.includes('demo-for-everyone'), null, {
		timeout: 30000
	});
	logCheckpoint('Redirected to demo chat after logout.');

	// ========================================================================
	// PHASE 7: Login with one of the new backup codes
	// ========================================================================

	// Open login dialog again
	const loginButtonAfterLogout = page.getByRole('button', {
		name: /login.*sign up|sign up/i
	});
	await expect(loginButtonAfterLogout).toBeVisible({ timeout: 15000 });
	await loginButtonAfterLogout.click();
	logCheckpoint('Opened login dialog after logout.');

	// Enter email
	const emailInputRelogin = page.locator('#login-email-input');
	await expect(emailInputRelogin).toBeVisible({ timeout: 10000 });
	await emailInputRelogin.fill(OPENMATES_TEST_ACCOUNT_EMAIL);
	await page.locator('#login-continue-button').click();
	logCheckpoint('Submitted email for re-login.');

	// Enter password
	const passwordInputRelogin = page.locator('#login-password-input');
	await expect(passwordInputRelogin).toBeVisible({ timeout: 15000 });
	await passwordInputRelogin.fill(OPENMATES_TEST_ACCOUNT_PASSWORD);
	logCheckpoint('Filled password for re-login.');

	// The TFA input should already be visible (tfa_enabled=true from lookup)
	const tfaInputRelogin = page.locator('#login-otp-input');
	await expect(tfaInputRelogin).toBeVisible({ timeout: 15000 });
	await takeStepScreenshot(page, 'tfa-prompt-relogin');

	// Switch to backup code mode using the toggle button
	const backupModeButton = page.locator('#login-with-backup-code button');
	await expect(backupModeButton).toBeVisible();
	await backupModeButton.click();
	await takeStepScreenshot(page, 'backup-mode-active');
	logCheckpoint('Switched to backup code mode.');

	// Enter the first backup code from the ones we captured in Phase 4
	const backupCodeToUse = backupCodes[0];
	logCheckpoint('Using backup code for login.', {
		code: `${backupCodeToUse.slice(0, 5)}*****`
	});

	const backupCodeInput = page.locator('#login-otp-input');
	await expect(backupCodeInput).toBeVisible();
	await backupCodeInput.fill(backupCodeToUse);
	await takeStepScreenshot(page, 'backup-code-entered');
	logCheckpoint('Entered backup code.');

	// Submit login with password + backup code
	const loginSubmitButton = page.locator('#login-submit-button');
	await expect(loginSubmitButton).toBeVisible();
	await loginSubmitButton.click();
	logCheckpoint('Submitted login with backup code.');

	// Wait for successful login - verify authenticated state
	const authIndicatorRelogin = page.locator('.chat-container.authenticated');
	await expect(authIndicatorRelogin).toBeVisible({ timeout: 60000 });
	await takeStepScreenshot(page, 'login-success-backup-code');
	logCheckpoint('Login successful with new backup code! Test complete.');

	// Verify no missing translations on the settings page
	await assertNoMissingTranslations(page);
	logCheckpoint('No missing translations detected.');
});
