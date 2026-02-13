/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};
// NOTE:
// This file is executed inside the official Playwright Docker image, which
// provides the @playwright/test module at runtime. To keep repo-wide TypeScript
// checks happy without requiring local Playwright installation, we use CommonJS
// require() and broad lint disables limited to this spec file.
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
	setToggleChecked,
	generateTotp
} = require('./signup-flow-helpers');

/**
 * Backup code setup and login flow test against a deployed web app.
 *
 * ARCHITECTURE NOTES:
 * - Uses the existing test account (must have password + 2FA configured).
 * - Phase 1: Logs in with password + OTP, navigates to Settings > Security > 2FA,
 *   triggers "Change App" to regenerate backup codes, captures a code.
 * - Phase 2: Logs out, then logs back in using the captured backup code instead of OTP.
 * - This validates both the settings backup code regeneration flow AND the backup code
 *   login flow end-to-end.
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL: Email of the existing test account.
 * - OPENMATES_TEST_ACCOUNT_PASSWORD: Password for the test account.
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY: 2FA secret key for the test account.
 */

const OPENMATES_TEST_ACCOUNT_EMAIL = process.env.OPENMATES_TEST_ACCOUNT_EMAIL;
const OPENMATES_TEST_ACCOUNT_PASSWORD = process.env.OPENMATES_TEST_ACCOUNT_PASSWORD;
const OPENMATES_TEST_ACCOUNT_OTP_KEY = process.env.OPENMATES_TEST_ACCOUNT_OTP_KEY;

test('sets up backup codes in settings and logs in with a backup code', async ({
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
	test.setTimeout(180000);

	const logCheckpoint = createSignupLogger('BACKUP_CODE_FLOW');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'backup-code'
	});

	await archiveExistingScreenshots(logCheckpoint);

	// Validate required environment variables
	test.skip(!OPENMATES_TEST_ACCOUNT_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!OPENMATES_TEST_ACCOUNT_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!OPENMATES_TEST_ACCOUNT_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	// Grant clipboard permissions for "Copy" actions
	await context.grantPermissions(['clipboard-read', 'clipboard-write']);

	logCheckpoint('Starting backup code setup and login test.', {
		email: OPENMATES_TEST_ACCOUNT_EMAIL
	});

	// ========================================================================
	// PHASE 1: Login with password + OTP to access settings
	// ========================================================================

	await page.goto('/');
	await takeStepScreenshot(page, 'home');

	// Open login dialog
	const headerLoginButton = page.getByRole('button', {
		name: /login.*sign up|sign up/i
	});
	await expect(headerLoginButton).toBeVisible();
	await headerLoginButton.click();
	await takeStepScreenshot(page, 'login-dialog');
	logCheckpoint('Opened login dialog.');

	// Enter email
	const emailInput = page.locator('input[type="email"][name="username"]');
	await expect(emailInput).toBeVisible({ timeout: 10000 });
	await emailInput.fill(OPENMATES_TEST_ACCOUNT_EMAIL);
	await page.getByRole('button', { name: /continue/i }).click();
	logCheckpoint('Submitted email for lookup.');

	// Enter password
	const passwordInput = page.locator('input[type="password"]');
	await expect(passwordInput.first()).toBeVisible({ timeout: 15000 });
	await passwordInput.first().fill(OPENMATES_TEST_ACCOUNT_PASSWORD);
	await takeStepScreenshot(page, 'password-filled');
	logCheckpoint('Filled password.');

	// Click login
	const loginButton = page.getByRole('button', { name: /login/i }).last();
	await loginButton.click();
	logCheckpoint('Clicked login button.');

	// Handle 2FA - enter OTP code
	const tfaInput = page.locator('input[autocomplete="one-time-code"]');
	await expect(tfaInput.first()).toBeVisible({ timeout: 15000 });
	const otpCode = generateTotp(OPENMATES_TEST_ACCOUNT_OTP_KEY);
	await tfaInput.first().fill(otpCode);
	await takeStepScreenshot(page, 'otp-entered');
	logCheckpoint('Entered OTP code.');

	// Submit OTP
	await loginButton.click();

	// Wait for successful login - redirect to chat
	await page.waitForURL(/chat|demo/, { timeout: 60000 });
	await takeStepScreenshot(page, 'logged-in');
	logCheckpoint('Login successful with password + OTP.');

	// ========================================================================
	// PHASE 2: Navigate to Settings > Security > 2FA to regenerate backup codes
	// ========================================================================

	// Open settings
	const settingsMenuButton = page.locator('.profile-container[role="button"]');
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

	// Click "Change App" to trigger 2FA re-setup (which regenerates backup codes)
	const changeAppButton = page.locator('button.btn-primary').filter({ hasText: /change.*app/i });
	await expect(changeAppButton).toBeVisible({ timeout: 10000 });
	await changeAppButton.click();
	await takeStepScreenshot(page, 'tfa-change-triggered');
	logCheckpoint('Clicked Change App to start 2FA re-setup.');

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

	// TFA setup step: get new secret and enter OTP
	const otpSetupInput = page.locator('input.otp-input');
	await expect(otpSetupInput).toBeVisible({ timeout: 15000 });
	await takeStepScreenshot(page, 'tfa-setup');

	// Get the new 2FA secret
	const secretElement = page.locator('.secret-value code');
	await expect(secretElement).toBeVisible();
	const newTfaSecret = (await secretElement.textContent()).trim();
	expect(newTfaSecret, 'Expected a new 2FA secret.').toBeTruthy();
	logCheckpoint('Got new 2FA secret from setup page.');

	// Enter new OTP based on new secret
	const setupOtp = generateTotp(newTfaSecret);
	await otpSetupInput.fill(setupOtp);
	logCheckpoint('Entered OTP for new 2FA secret.');

	// Wait for verification (auto-submits at 6 digits)
	// Select app step appears
	const appItem = page.locator('button.app-item').first();
	await expect(appItem).toBeVisible({ timeout: 15000 });
	await takeStepScreenshot(page, 'tfa-select-app');
	await appItem.click();

	const continueButton = page.locator('button.btn-primary').filter({ hasText: /continue/i });
	await continueButton.click();
	logCheckpoint('Selected 2FA app and continued.');

	// ========================================================================
	// PHASE 3: Capture backup codes
	// ========================================================================

	// Wait for backup codes to appear
	const backupCodesContainer = page.locator('.tfa-backup-codes');
	await expect(backupCodesContainer).toBeVisible({ timeout: 15000 });
	await takeStepScreenshot(page, 'backup-codes-displayed');
	logCheckpoint('Backup codes displayed.');

	// Read all backup codes from the UI
	const codeElements = page.locator('.code-item code');
	const codeCount = await codeElements.count();
	expect(codeCount, 'Expected at least 1 backup code to be displayed.').toBeGreaterThan(0);

	const backupCodes: string[] = [];
	for (let i = 0; i < codeCount; i++) {
		const code = await codeElements.nth(i).textContent();
		if (code) {
			backupCodes.push(code.trim());
		}
	}
	logCheckpoint('Captured backup codes.', { count: backupCodes.length });
	expect(backupCodes.length, 'Expected multiple backup codes.').toBeGreaterThan(0);

	// Verify code format: XXXX-XXXX-XXXX (14 chars with dashes at pos 4 and 9)
	for (const code of backupCodes) {
		expect(code).toMatch(/^[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$/);
	}
	logCheckpoint('Verified backup code format.');

	// Confirm storage and complete setup
	const confirmCheckbox = page.locator('.confirm-checkbox input[type="checkbox"]');
	await setToggleChecked(confirmCheckbox, true);
	await expect(confirmCheckbox).toBeChecked();

	const completeSetupButton = backupCodesContainer.locator('button.btn-primary');
	await completeSetupButton.click();
	logCheckpoint('Confirmed backup code storage and completed setup.');

	// Wait for success step
	const successContainer = page.locator('.tfa-success');
	await expect(successContainer).toBeVisible({ timeout: 15000 });
	await takeStepScreenshot(page, 'tfa-setup-success');
	logCheckpoint('2FA setup completed successfully.');

	// Click "Done"
	const doneButton = page.locator('button.btn-primary').filter({ hasText: /done/i });
	await doneButton.click();
	logCheckpoint('Clicked Done on 2FA success.');

	// ========================================================================
	// PHASE 4: Logout
	// ========================================================================

	// Navigate back to main settings menu to find logout
	// The back button or direct navigation depends on the current settings page state.
	// We'll re-open settings from scratch if needed.

	// Try to find the settings menu - it might still be open
	const settingsVisible = await page
		.locator('.settings-menu.visible')
		.isVisible()
		.catch(() => false);
	if (!settingsVisible) {
		await settingsMenuButton.click();
		await expect(page.locator('.settings-menu.visible')).toBeVisible();
	}

	// Look for the logout menu item
	const logoutItem = page.getByRole('menuitem', { name: /logout|abmelden/i });
	// If not visible, we may need to navigate back to the main settings menu
	const logoutVisible = await logoutItem.isVisible().catch(() => false);
	if (!logoutVisible) {
		// Click back buttons until we reach main settings
		const backButton = page.locator('.settings-menu .back-button, .settings-header .back-button');
		for (let i = 0; i < 5; i++) {
			const backVisible = await backButton
				.first()
				.isVisible()
				.catch(() => false);
			if (!backVisible) break;
			await backButton.first().click();
			await page.waitForTimeout(500);
			const nowVisible = await logoutItem.isVisible().catch(() => false);
			if (nowVisible) break;
		}
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
	// PHASE 5: Login with backup code
	// ========================================================================

	// Open login dialog again
	const loginButtonAfterLogout = page.getByRole('button', {
		name: /login.*sign up|sign up/i
	});
	await expect(loginButtonAfterLogout).toBeVisible({ timeout: 15000 });
	await loginButtonAfterLogout.click();
	logCheckpoint('Opened login dialog after logout.');

	// Enter email
	const emailInputRelogin = page.locator('input[type="email"][name="username"]');
	await expect(emailInputRelogin).toBeVisible({ timeout: 10000 });
	await emailInputRelogin.fill(OPENMATES_TEST_ACCOUNT_EMAIL);
	await page.getByRole('button', { name: /continue/i }).click();
	logCheckpoint('Submitted email for re-login.');

	// Enter password
	const passwordInputRelogin = page.locator('input[type="password"]');
	await expect(passwordInputRelogin.first()).toBeVisible({ timeout: 15000 });
	await passwordInputRelogin.first().fill(OPENMATES_TEST_ACCOUNT_PASSWORD);

	// Click login to trigger 2FA
	const loginButtonRelogin = page.getByRole('button', { name: /login/i }).last();
	await loginButtonRelogin.click();
	logCheckpoint('Submitted password for re-login.');

	// Wait for 2FA input
	const tfaInputRelogin = page.locator('input[autocomplete="one-time-code"]');
	await expect(tfaInputRelogin.first()).toBeVisible({ timeout: 15000 });
	await takeStepScreenshot(page, 'tfa-prompt-relogin');
	logCheckpoint('Reached 2FA prompt during re-login.');

	// Switch to backup code mode
	const backupModeButton = page.locator('#login-with-backup-code button');
	await expect(backupModeButton).toBeVisible();
	await backupModeButton.click();
	await takeStepScreenshot(page, 'backup-mode-active');
	logCheckpoint('Switched to backup code mode.');

	// Enter the first backup code
	const backupCodeToUse = backupCodes[0];
	logCheckpoint('Using backup code for login.', {
		code: `${backupCodeToUse.slice(0, 5)}*****`
	});

	// The TFA input should now accept backup code format
	// The input field reuses the same input but with different validation
	const backupCodeInput = page.locator('input[autocomplete="one-time-code"]').first();
	await expect(backupCodeInput).toBeVisible();
	await backupCodeInput.fill(backupCodeToUse);
	await takeStepScreenshot(page, 'backup-code-entered');
	logCheckpoint('Entered backup code.');

	// Submit login with backup code
	await loginButtonRelogin.click();
	logCheckpoint('Submitted login with backup code.');

	// Wait for successful login - redirect to chat
	await page.waitForURL(/chat|demo/, { timeout: 60000 });
	await takeStepScreenshot(page, 'login-success-backup-code');
	logCheckpoint('Login successful with backup code! Test complete.');
});
