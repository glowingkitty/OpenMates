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
	generateTotp,
	assertNoMissingTranslations
} = require('./signup-flow-helpers');

/**
 * Recovery key setup and login flow test against a deployed web app.
 *
 * ARCHITECTURE NOTES:
 * - Uses the existing test account (must have password + 2FA configured).
 * - Phase 1: Logs in with password + OTP, navigates to Settings > Security > Recovery Key,
 *   triggers regeneration and captures the recovery key via clipboard.
 * - Phase 2: Logs out, then logs back in using the recovery key (bypasses 2FA entirely).
 * - This validates both the settings recovery key regeneration flow AND the recovery key
 *   login flow end-to-end, including the critical key_iv field in the login response.
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL: Email of the existing test account.
 * - OPENMATES_TEST_ACCOUNT_PASSWORD: Password for the test account.
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY: 2FA secret key for the test account.
 */

const OPENMATES_TEST_ACCOUNT_EMAIL = process.env.OPENMATES_TEST_ACCOUNT_EMAIL;
const OPENMATES_TEST_ACCOUNT_PASSWORD = process.env.OPENMATES_TEST_ACCOUNT_PASSWORD;
const OPENMATES_TEST_ACCOUNT_OTP_KEY = process.env.OPENMATES_TEST_ACCOUNT_OTP_KEY;

test('sets up recovery key in settings and logs in with recovery key', async ({
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

	const logCheckpoint = createSignupLogger('RECOVERY_KEY_FLOW');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'recovery-key'
	});

	await archiveExistingScreenshots(logCheckpoint);

	// Validate required environment variables
	test.skip(!OPENMATES_TEST_ACCOUNT_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!OPENMATES_TEST_ACCOUNT_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!OPENMATES_TEST_ACCOUNT_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	// Grant clipboard permissions for reading the recovery key after "Copy" action
	await context.grantPermissions(['clipboard-read', 'clipboard-write']);

	logCheckpoint('Starting recovery key setup and login test.', {
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

	// Enter password — password+TFA is a single combined form.
	// Since tfa_enabled=true from lookup, the TFA input is already visible.
	const passwordInput = page.locator('input[type="password"]');
	await expect(passwordInput.first()).toBeVisible({ timeout: 15000 });
	await passwordInput.first().fill(OPENMATES_TEST_ACCOUNT_PASSWORD);
	await takeStepScreenshot(page, 'password-filled');
	logCheckpoint('Filled password.');

	// Handle 2FA - enter OTP code (TFA input is already visible alongside password)
	const tfaInput = page.locator('input[autocomplete="one-time-code"]');
	await expect(tfaInput.first()).toBeVisible({ timeout: 15000 });
	const otpCode = generateTotp(OPENMATES_TEST_ACCOUNT_OTP_KEY);
	await tfaInput.first().fill(otpCode);
	await takeStepScreenshot(page, 'otp-entered');
	logCheckpoint('Entered OTP code.');

	// Submit login (password + OTP together in one click)
	const submitLoginButton = page.locator('button[type="submit"].login-button');
	await expect(submitLoginButton).toBeVisible();
	await submitLoginButton.click();

	// Wait for successful login - redirect to chat
	await page.waitForURL(/chat|demo/, { timeout: 60000 });
	await takeStepScreenshot(page, 'logged-in');
	logCheckpoint('Login successful with password + OTP.');

	// ========================================================================
	// PHASE 2: Navigate to Settings > Security > Recovery Key to regenerate
	// ========================================================================

	// Open settings
	const settingsMenuButton = page.locator('.profile-container[role="button"]');
	await settingsMenuButton.click();
	await expect(page.locator('.settings-menu.visible')).toBeVisible();
	await takeStepScreenshot(page, 'settings-open');
	logCheckpoint('Opened settings menu.');

	// Navigate: Account -> Security -> Recovery Key
	await page.getByRole('menuitem', { name: /account/i }).click();
	logCheckpoint('Navigated to Account settings.');

	await page.getByRole('menuitem', { name: /security/i }).click();
	logCheckpoint('Navigated to Security settings.');

	await page.getByRole('menuitem', { name: /recovery.*key/i }).click();
	await takeStepScreenshot(page, 'recovery-key-overview');
	logCheckpoint('Navigated to Recovery Key settings.');

	// Click "Regenerate Recovery Key" (or "Create Recovery Key" if first time)
	const regenerateButton = page.locator('button.primary-button');
	await expect(regenerateButton).toBeVisible({ timeout: 10000 });
	await regenerateButton.click();
	await takeStepScreenshot(page, 'recovery-key-auth-prompt');
	logCheckpoint('Clicked regenerate recovery key button.');

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

	// Wait for generating step to pass and save step to appear
	const saveContainer = page.locator('.save-container');
	await expect(saveContainer).toBeVisible({ timeout: 30000 });
	await takeStepScreenshot(page, 'recovery-key-save');
	logCheckpoint('Recovery key generated, save step visible.');

	// ========================================================================
	// PHASE 3: Capture the recovery key via clipboard
	// ========================================================================

	// Click "Copy" button to copy the recovery key to clipboard
	const copyButton = page.locator('button.save-button').filter({ hasText: /copy/i });
	await expect(copyButton).toBeVisible();
	await copyButton.click();
	logCheckpoint('Clicked Copy button for recovery key.');

	// Verify copy button shows "used" state (checkmark)
	await expect(copyButton).toHaveClass(/used/, { timeout: 5000 });
	logCheckpoint('Copy button shows used/checkmark state.');

	// Read the recovery key from clipboard
	const recoveryKey = await page.evaluate(() => navigator.clipboard.readText());
	expect(recoveryKey, 'Expected recovery key to be copied to clipboard.').toBeTruthy();
	expect(recoveryKey.length, 'Recovery key should be 24 characters.').toBe(24);
	// Verify it contains valid characters (alphanumeric + special chars from generateSecureRecoveryKey)
	expect(recoveryKey).toMatch(/^[A-Za-z0-9\-_#=+&%$]{24}$/);
	logCheckpoint('Captured recovery key from clipboard.', {
		length: recoveryKey.length,
		firstChars: `${recoveryKey.slice(0, 4)}****`
	});
	await takeStepScreenshot(page, 'recovery-key-copied');

	// Toggle confirmation and continue
	const confirmToggle = page.locator('#confirm-storage-toggle');
	await setToggleChecked(confirmToggle, true);
	logCheckpoint('Confirmed recovery key storage.');

	const continueButton = page.locator('.save-container button.primary-button');
	await expect(continueButton).toBeEnabled({ timeout: 5000 });
	await continueButton.click();
	logCheckpoint('Clicked Continue to save recovery key.');

	// Wait for success - back to overview with success message
	const successMessage = page.locator('.success-message');
	await expect(successMessage).toBeVisible({ timeout: 30000 });
	await takeStepScreenshot(page, 'recovery-key-success');
	logCheckpoint('Recovery key saved successfully.');

	// ========================================================================
	// PHASE 4: Logout
	// ========================================================================

	// After saving the recovery key, the settings panel is still open on a sub-page.
	// We need to navigate back to the main settings menu where the logout item lives.
	// The back button in the settings header uses `.nav-button` with a visible
	// `.icon_back` child indicating it's active (not on the main menu).

	// Ensure the settings menu is open
	const settingsVisible = await page
		.locator('.settings-menu.visible')
		.isVisible()
		.catch(() => false);
	if (!settingsVisible) {
		await settingsMenuButton.click();
		await expect(page.locator('.settings-menu.visible')).toBeVisible();
	}

	// Navigate back to main settings by clicking the header back button repeatedly.
	const logoutItem = page.getByRole('menuitem', { name: /logout|abmelden/i });
	const settingsBackButton = page.locator('.settings-header .nav-button .icon_back.visible');
	for (let i = 0; i < 5; i++) {
		const logoutNowVisible = await logoutItem.isVisible().catch(() => false);
		if (logoutNowVisible) break;
		const backVisible = await settingsBackButton.isVisible().catch(() => false);
		if (!backVisible) break;
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
	// PHASE 5: Login with recovery key
	// ========================================================================

	// Open login dialog
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

	// Enter password — the password+TFA form is a single combined step.
	// Since the account has tfa_enabled=true from /lookup, the TFA input is already
	// visible alongside the password field. We do NOT need to click login first.
	const passwordInputRelogin = page.locator('input[type="password"]');
	await expect(passwordInputRelogin.first()).toBeVisible({ timeout: 15000 });
	await passwordInputRelogin.first().fill(OPENMATES_TEST_ACCOUNT_PASSWORD);
	logCheckpoint('Filled password for re-login.');

	// The TFA input should already be visible (tfa_enabled=true from lookup)
	const tfaInputRelogin = page.locator('input[autocomplete="one-time-code"]');
	await expect(tfaInputRelogin.first()).toBeVisible({ timeout: 15000 });
	await takeStepScreenshot(page, 'tfa-prompt-relogin');
	logCheckpoint('TFA input visible alongside password (combined form).');

	// Click "Login with recovery key" to switch to recovery key mode
	const recoveryKeyButton = page.locator('#login-with-recoverykey button');
	await expect(recoveryKeyButton).toBeVisible();
	await recoveryKeyButton.click();
	await takeStepScreenshot(page, 'recovery-key-mode');
	logCheckpoint('Switched to recovery key login mode.');

	// Wait for the recovery key input to appear
	// EnterRecoveryKey.svelte renders an input with specific validation (24 chars)
	const recoveryKeyInput = page.locator('input[type="text"]').first();
	await expect(recoveryKeyInput).toBeVisible({ timeout: 10000 });

	// Enter the recovery key
	logCheckpoint('Entering recovery key for login.', {
		keyPreview: `${recoveryKey.slice(0, 4)}****`
	});
	await recoveryKeyInput.fill(recoveryKey);
	await takeStepScreenshot(page, 'recovery-key-entered');
	logCheckpoint('Entered recovery key.');

	// Submit recovery key login
	// The EnterRecoveryKey component has a form with a submit button
	const recoverySubmitButton = page.getByRole('button', { name: /login|verify|submit/i });
	await expect(recoverySubmitButton).toBeVisible();
	await recoverySubmitButton.click();
	logCheckpoint('Submitted recovery key login.');

	// Wait for successful login - redirect to chat
	// Recovery key login bypasses 2FA entirely, so it should go straight to chat
	await page.waitForURL(/chat|demo/, { timeout: 60000 });
	await takeStepScreenshot(page, 'login-success-recovery-key');
	logCheckpoint('Login successful with recovery key! Test complete.');

	// Verify we're actually authenticated (not on demo)
	// Check that the settings/profile icon shows (authenticated state indicator)
	const profileIndicator = page.locator('.profile-container[role="button"]');
	await expect(profileIndicator).toBeVisible({ timeout: 15000 });
	logCheckpoint('Verified authenticated state - profile indicator visible.');

	// Verify no missing translations after recovery key login
	await assertNoMissingTranslations(page);
	logCheckpoint('No missing translations detected.');
});
