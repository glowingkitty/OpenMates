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
 * Recovery key SETTINGS test — validates the "Regenerate Recovery Key" feature
 * in Settings > Account > Security > Recovery Key.
 *
 * ARCHITECTURE NOTES:
 * - Uses the existing test account (must have password + 2FA configured).
 * - Phase 1: Logs in with password + OTP.
 * - Phase 2: Navigates to Settings > Security > Recovery Key.
 * - Phase 3: Clicks "Regenerate", authenticates via SecurityAuth.
 * - Phase 4: Waits for key generation, copies key via "Copy" button.
 * - Phase 5: Verifies key format (24 chars, valid characters).
 * - Phase 6: Toggles confirm, clicks Continue, verifies success message.
 *
 * This does NOT test login with recovery key (see recovery-key-login-flow.spec.ts).
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL: Email of the existing test account.
 * - OPENMATES_TEST_ACCOUNT_PASSWORD: Password for the test account.
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY: 2FA secret key for the test account.
 */

const OPENMATES_TEST_ACCOUNT_EMAIL = process.env.OPENMATES_TEST_ACCOUNT_EMAIL;
const OPENMATES_TEST_ACCOUNT_PASSWORD = process.env.OPENMATES_TEST_ACCOUNT_PASSWORD;
const OPENMATES_TEST_ACCOUNT_OTP_KEY = process.env.OPENMATES_TEST_ACCOUNT_OTP_KEY;

test('regenerates recovery key via Settings > Security > Recovery Key', async ({
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

	const logCheckpoint = createSignupLogger('RECOVERY_KEY_SETTINGS');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'recovery-key-settings'
	});

	await archiveExistingScreenshots(logCheckpoint);

	// Validate required environment variables
	test.skip(!OPENMATES_TEST_ACCOUNT_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!OPENMATES_TEST_ACCOUNT_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');
	test.skip(!OPENMATES_TEST_ACCOUNT_OTP_KEY, 'OPENMATES_TEST_ACCOUNT_OTP_KEY is required.');

	// Grant clipboard permissions for reading the recovery key after "Copy" action
	await context.grantPermissions(['clipboard-read', 'clipboard-write']);

	logCheckpoint('Starting recovery key settings test.', {
		email: OPENMATES_TEST_ACCOUNT_EMAIL
	});

	// ========================================================================
	// PHASE 1: Login with password + OTP
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

	// Enter password — password+TFA is a single combined form
	const passwordInput = page.locator('input[type="password"]');
	await expect(passwordInput.first()).toBeVisible({ timeout: 15000 });
	await passwordInput.first().fill(OPENMATES_TEST_ACCOUNT_PASSWORD);
	logCheckpoint('Filled password.');

	// Enter OTP code (TFA input already visible alongside password)
	const tfaInput = page.locator('input[autocomplete="one-time-code"]');
	await expect(tfaInput.first()).toBeVisible({ timeout: 15000 });
	const otpCode = generateTotp(OPENMATES_TEST_ACCOUNT_OTP_KEY);
	await tfaInput.first().fill(otpCode);
	await takeStepScreenshot(page, 'otp-entered');
	logCheckpoint('Entered OTP code.');

	// Submit login (password + OTP together)
	const submitLoginButton = page.locator('button[type="submit"].login-button');
	await expect(submitLoginButton).toBeVisible();
	await submitLoginButton.click();
	logCheckpoint('Submitted login with password + OTP.');

	// Wait for successful login - redirect to chat
	await page.waitForURL(/chat/, { timeout: 60000 });
	await takeStepScreenshot(page, 'logged-in');
	logCheckpoint('Login successful.');

	// ========================================================================
	// PHASE 2: Navigate to Settings > Security > Recovery Key
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

	// ========================================================================
	// PHASE 3: Click "Regenerate" and authenticate
	// ========================================================================

	// Click "Regenerate Recovery Key" (or "Create Recovery Key" if first time)
	const regenerateButton = page.locator('button.primary-button');
	await expect(regenerateButton).toBeVisible({ timeout: 10000 });
	await regenerateButton.click();
	await takeStepScreenshot(page, 'regenerate-clicked');
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

	// ========================================================================
	// PHASE 4: Wait for key generation and copy the key
	// ========================================================================

	// Wait for the save container to appear (generating step may flash briefly)
	const saveContainer = page.locator('.save-container');
	await expect(saveContainer).toBeVisible({ timeout: 30000 });
	await takeStepScreenshot(page, 'recovery-key-save');
	logCheckpoint('Recovery key generated, save step visible.');

	// Click "Copy" button to copy the recovery key to clipboard
	const copyButton = page.locator('button.save-button').filter({ hasText: /copy/i });
	await expect(copyButton).toBeVisible();
	await copyButton.click();
	logCheckpoint('Clicked Copy button for recovery key.');

	// Verify copy button shows "used" state (checkmark)
	await expect(copyButton).toHaveClass(/used/, { timeout: 5000 });
	logCheckpoint('Copy button shows used/checkmark state.');

	// ========================================================================
	// PHASE 5: Verify key format
	// ========================================================================

	// Read the recovery key from clipboard
	const recoveryKey = await page.evaluate(() => navigator.clipboard.readText());
	expect(recoveryKey, 'Expected recovery key to be copied to clipboard.').toBeTruthy();
	expect(recoveryKey.length, 'Recovery key should be 24 characters.').toBe(24);

	// Verify it contains valid characters (alphanumeric + special chars from generateSecureRecoveryKey)
	expect(recoveryKey).toMatch(/^[A-Za-z0-9\-_#=+&%$]{24}$/);
	logCheckpoint('Verified recovery key format.', {
		length: recoveryKey.length,
		firstChars: `${recoveryKey.slice(0, 4)}****`
	});
	await takeStepScreenshot(page, 'recovery-key-copied');

	// ========================================================================
	// PHASE 6: Confirm storage and verify success
	// ========================================================================

	// Toggle the confirmation switch
	const confirmToggle = page.locator('#confirm-storage-toggle');
	await setToggleChecked(confirmToggle, true);
	logCheckpoint('Confirmed recovery key storage.');

	// Click "Continue" button
	const continueButton = page.locator('.save-container button.primary-button');
	await expect(continueButton).toBeEnabled({ timeout: 5000 });
	await continueButton.click();
	logCheckpoint('Clicked Continue to save recovery key.');

	// Wait for success - back to overview with success message
	const successMessage = page.locator('.success-message');
	await expect(successMessage).toBeVisible({ timeout: 30000 });
	await takeStepScreenshot(page, 'recovery-key-success');
	logCheckpoint('Success message visible. Recovery key regeneration complete.');

	// Verify we're back on the overview (regenerate button should be visible again)
	await expect(regenerateButton).toBeVisible({ timeout: 5000 });
	logCheckpoint('Back on Recovery Key overview. Test complete.');
});
