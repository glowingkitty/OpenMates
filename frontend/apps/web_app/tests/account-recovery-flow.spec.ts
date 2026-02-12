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
		consoleLogs.slice(-20).forEach((log) => console.log(log));

		console.log('\n[RECENT NETWORK ACTIVITIES]');
		networkActivities.slice(-20).forEach((activity) => console.log(activity));
		console.log('\n--- END DEBUG INFO ---\n');
	}
});

const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	setToggleChecked,
	getSignupTestDomain,
	getMailosaurServerId,
	createMailosaurClient,
	generateTotp
} = require('./signup-flow-helpers');

/**
 * Account recovery flow test against a deployed web app.
 *
 * ARCHITECTURE NOTES:
 * - Uses the existing test account (created by signup-flow.spec.ts or manually).
 * - Tests the full recovery flow: request code, enter code, set up new password
 *   (same password for idempotency), complete reset, and verify login works.
 * - The recovery flow permanently deletes chats/settings/memories but preserves
 *   the account itself (credits, username, subscription).
 * - After recovery, the user must login with their new credentials.
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL: Email of the existing test account.
 * - OPENMATES_TEST_ACCOUNT_PASSWORD: Password for the test account.
 * - OPENMATES_TEST_ACCOUNT_OTP_KEY: 2FA secret key for the test account.
 * - MAILOSAUR_API_KEY: Mailosaur API key for test mailbox access.
 * - SIGNUP_TEST_EMAIL_DOMAINS: Used to derive Mailosaur server ID.
 * - MAILOSAUR_SERVER_ID: (optional) Mailosaur server ID if not derivable.
 */

const MAILOSAUR_API_KEY = process.env.MAILOSAUR_API_KEY;
const MAILOSAUR_SERVER_ID = process.env.MAILOSAUR_SERVER_ID;
const SIGNUP_TEST_EMAIL_DOMAINS = process.env.SIGNUP_TEST_EMAIL_DOMAINS;
const OPENMATES_TEST_ACCOUNT_EMAIL = process.env.OPENMATES_TEST_ACCOUNT_EMAIL;
const OPENMATES_TEST_ACCOUNT_PASSWORD = process.env.OPENMATES_TEST_ACCOUNT_PASSWORD;
const OPENMATES_TEST_ACCOUNT_OTP_KEY = process.env.OPENMATES_TEST_ACCOUNT_OTP_KEY;

test('completes full account recovery flow with same password', async ({
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
	// Allow extra time for email delivery and recovery process.
	test.setTimeout(300000);

	const logRecoveryCheckpoint = createSignupLogger('RECOVERY_FLOW');
	const takeStepScreenshot = createStepScreenshotter(logRecoveryCheckpoint, {
		filenamePrefix: 'recovery'
	});

	await archiveExistingScreenshots(logRecoveryCheckpoint);

	// Validate required environment variables
	const signupDomain = getSignupTestDomain(SIGNUP_TEST_EMAIL_DOMAINS);
	test.skip(!signupDomain, 'SIGNUP_TEST_EMAIL_DOMAINS must include a test domain.');
	test.skip(!MAILOSAUR_API_KEY, 'MAILOSAUR_API_KEY is required for email validation.');
	test.skip(!OPENMATES_TEST_ACCOUNT_EMAIL, 'OPENMATES_TEST_ACCOUNT_EMAIL is required.');
	test.skip(!OPENMATES_TEST_ACCOUNT_PASSWORD, 'OPENMATES_TEST_ACCOUNT_PASSWORD is required.');

	if (!signupDomain) {
		throw new Error('Missing signup test domain after skip guard.');
	}

	const mailosaurServerId = getMailosaurServerId(signupDomain, MAILOSAUR_SERVER_ID);
	if (!mailosaurServerId) {
		throw new Error(
			'MAILOSAUR_SERVER_ID is missing and could not be derived from the signup domain.'
		);
	}

	const { waitForMailosaurMessage, extractSixDigitCode } = createMailosaurClient({
		apiKey: MAILOSAUR_API_KEY,
		serverId: mailosaurServerId
	});

	// Grant clipboard permissions
	await context.grantPermissions(['clipboard-read', 'clipboard-write']);

	logRecoveryCheckpoint('Starting account recovery test.', {
		email: OPENMATES_TEST_ACCOUNT_EMAIL
	});

	// ========================================================================
	// Step 1: Navigate to the app and open the login dialog
	// ========================================================================
	await page.goto('/');
	await takeStepScreenshot(page, 'home');

	const headerLoginSignupButton = page.getByRole('button', {
		name: /login.*sign up|sign up/i
	});
	await expect(headerLoginSignupButton).toBeVisible();
	await headerLoginSignupButton.click();
	await takeStepScreenshot(page, 'login-dialog');
	logRecoveryCheckpoint('Opened login dialog.');

	// ========================================================================
	// Step 2: Enter email in the login form
	// ========================================================================
	// EmailLookup uses type="email" with autocomplete="username webauthn"
	const emailInput = page.locator('input[type="email"][name="username"]');
	await expect(emailInput).toBeVisible({ timeout: 10000 });
	await emailInput.fill(OPENMATES_TEST_ACCOUNT_EMAIL);
	logRecoveryCheckpoint('Filled email address.');

	// Submit email to trigger lookup (the "Continue" button)
	await page.getByRole('button', { name: /continue/i }).click();
	await takeStepScreenshot(page, 'email-submitted');
	logRecoveryCheckpoint('Submitted email for lookup.');

	// Wait for password step to appear
	const passwordInput = page.locator('input[type="password"]');
	await expect(passwordInput.first()).toBeVisible({ timeout: 15000 });
	await takeStepScreenshot(page, 'password-step');
	logRecoveryCheckpoint('Reached password step.');

	// ========================================================================
	// Step 3: Click "Can't login to my account" to enter recovery flow
	// ========================================================================
	const cantLoginButton = page.getByRole('button', { name: /can.*login|kann.*nicht.*anmelden/i });
	// Fallback: use the specific class if accessible name doesn't match
	const cantLoginFallback = page.locator('.cant-login-button');
	const cantLoginTarget = (await cantLoginButton.isVisible().catch(() => false))
		? cantLoginButton
		: cantLoginFallback;
	await cantLoginTarget.scrollIntoViewIfNeeded();
	await cantLoginTarget.click();
	await takeStepScreenshot(page, 'recovery-started');
	logRecoveryCheckpoint('Clicked "Can\'t login" button, entering recovery flow.');

	// ========================================================================
	// Step 4: Wait for recovery code to be sent and retrieve it from Mailosaur
	// ========================================================================
	// Record the time BEFORE clicking so we can filter Mailosaur messages
	const codeRequestedAt = new Date().toISOString();

	// Wait for the recovery UI to appear (the info text and code input)
	const codeInput = page.locator('input#verification-code');
	await expect(codeInput).toBeVisible({ timeout: 15000 });
	await takeStepScreenshot(page, 'recovery-code-input');
	logRecoveryCheckpoint('Recovery code input visible.');

	// Verify the code input is NOT disabled (this was the reported bug)
	const isDisabled = await codeInput.isDisabled();
	expect(isDisabled, 'Verification code input should NOT be disabled').toBe(false);
	logRecoveryCheckpoint('Verified code input is enabled (not blocked).');

	// Verify the code input accepts text input
	await codeInput.click();
	await codeInput.fill('123');
	const filledValue = await codeInput.inputValue();
	expect(filledValue).toBe('123');
	await codeInput.fill(''); // Clear it
	logRecoveryCheckpoint('Verified code input accepts text input.');

	// Poll Mailosaur for the recovery code email
	logRecoveryCheckpoint('Polling Mailosaur for recovery code email.');
	const recoveryEmail = await waitForMailosaurMessage({
		sentTo: OPENMATES_TEST_ACCOUNT_EMAIL,
		receivedAfter: codeRequestedAt,
		timeoutMs: 120000
	});
	const recoveryCode = extractSixDigitCode(recoveryEmail);
	expect(recoveryCode, 'Expected a 6-digit recovery code from email.').toBeTruthy();
	logRecoveryCheckpoint('Received recovery code from email.', {
		hasCode: !!recoveryCode
	});

	// ========================================================================
	// Step 5: Enter recovery code and acknowledge data loss
	// ========================================================================

	// First, toggle the data loss acknowledgment
	const dataLossToggle = page.locator('#acknowledge-data-loss');
	await setToggleChecked(dataLossToggle, true);
	await expect(dataLossToggle).toBeChecked();
	logRecoveryCheckpoint('Acknowledged data loss.');
	await takeStepScreenshot(page, 'data-loss-acknowledged');

	// Enter the recovery code - the input should auto-verify when 6 digits + toggle checked
	await codeInput.fill(recoveryCode);
	logRecoveryCheckpoint('Entered recovery code.');
	await takeStepScreenshot(page, 'code-entered');

	// ========================================================================
	// Step 6: Wait for code verification and select password method
	// ========================================================================
	// After auto-verify or clicking "Reset account", we should see the method selection
	const passwordOption = page.getByRole('button', { name: /password/i });

	// If auto-verify doesn't trigger, click the reset button manually
	try {
		await expect(passwordOption).toBeVisible({ timeout: 10000 });
	} catch {
		// Auto-verify didn't trigger; click the "Reset account" button
		logRecoveryCheckpoint('Auto-verify did not trigger, clicking Reset account button.');
		const resetButton = page.locator('button').filter({ hasText: /reset.*account/i });
		if (await resetButton.isVisible()) {
			await resetButton.click();
		}
		await expect(passwordOption).toBeVisible({ timeout: 15000 });
	}

	await takeStepScreenshot(page, 'method-selection');
	logRecoveryCheckpoint('Code verified, reached method selection.');

	// Select password method
	await passwordOption.click();
	logRecoveryCheckpoint('Selected password method.');

	// ========================================================================
	// Step 7: Set up the SAME password
	// ========================================================================
	const newPasswordInputs = page.locator('input[type="password"]');
	await expect(newPasswordInputs.first()).toBeVisible({ timeout: 10000 });
	await takeStepScreenshot(page, 'password-setup');

	// Fill password fields with the same password
	await newPasswordInputs.nth(0).fill(OPENMATES_TEST_ACCOUNT_PASSWORD);
	await newPasswordInputs.nth(1).fill(OPENMATES_TEST_ACCOUNT_PASSWORD);
	logRecoveryCheckpoint('Filled password fields with same password.');
	await takeStepScreenshot(page, 'password-filled');

	// Submit password - button text depends on whether 2FA setup is needed
	const continueOrCompleteButton = page.locator('.step-content button:not(.back-button)').filter({
		hasText: /continue|complete.*reset/i
	});
	await continueOrCompleteButton.click();
	logRecoveryCheckpoint('Submitted password.');

	// ========================================================================
	// Step 8: Handle 2FA setup if required
	// ========================================================================
	// The user already had 2FA, so the server preserves it and we go straight to reset.
	// If 2FA setup is shown, handle it.
	const tfaSetupVisible = await page
		.locator('.tfa-setup-header')
		.isVisible({ timeout: 5000 })
		.catch(() => false);

	if (tfaSetupVisible) {
		logRecoveryCheckpoint('2FA setup step detected, setting up new 2FA.');
		await takeStepScreenshot(page, '2fa-setup');

		// Get the 2FA secret from the page
		const secretKeyElement = page.locator('.secret-key');
		await expect(secretKeyElement).toBeVisible();
		const newTfaSecret = await secretKeyElement.textContent();
		expect(newTfaSecret, 'Expected a 2FA secret on the setup page.').toBeTruthy();
		logRecoveryCheckpoint('Got new 2FA secret from setup page.');

		// Generate and enter OTP code
		const otpCode = generateTotp(newTfaSecret.trim());
		const tfaCodeInput = page.locator('#tfa-code');
		await tfaCodeInput.fill(otpCode);
		logRecoveryCheckpoint('Entered 2FA verification code.');

		// Select a 2FA app
		const appButton = page.locator('.app-item').first();
		await appButton.click();
		logRecoveryCheckpoint('Selected 2FA app.');
		await takeStepScreenshot(page, '2fa-completed');

		// Click "Complete reset"
		const completeResetButton = page.locator('.step-content button:not(.back-button)').filter({
			hasText: /complete.*reset/i
		});
		await completeResetButton.click();
		logRecoveryCheckpoint('Clicked complete reset with 2FA.');
	} else {
		logRecoveryCheckpoint('No 2FA setup needed (user already had 2FA configured).');
	}

	// ========================================================================
	// Step 9: Wait for reset to complete
	// ========================================================================
	// We should see either a loading/resetting screen followed by success,
	// or directly the success message
	const successMessage = page.locator('.success-icon, .step-content h3').filter({
		hasText: /reset.*complete|account.*reset/i
	});
	await expect(successMessage).toBeVisible({ timeout: 60000 });
	await takeStepScreenshot(page, 'reset-complete');
	logRecoveryCheckpoint('Account reset completed successfully!');

	// ========================================================================
	// Step 10: Navigate back to login and verify login with new password
	// ========================================================================
	const goToLoginButton = page.getByRole('button', { name: /go to login|login/i });
	await goToLoginButton.click();
	logRecoveryCheckpoint('Clicked "Go to login" button.');

	// Wait for the login interface to reset to email step
	await page.waitForTimeout(2000);
	await takeStepScreenshot(page, 'back-to-login');

	// Re-enter email
	const loginEmailInput = page.locator('input[type="email"][name="username"]');
	await expect(loginEmailInput).toBeVisible({ timeout: 15000 });
	await loginEmailInput.fill(OPENMATES_TEST_ACCOUNT_EMAIL);
	logRecoveryCheckpoint('Re-entered email for login verification.');

	// Submit email (the "Continue" button)
	await page.getByRole('button', { name: /continue/i }).click();

	// Wait for password input
	const loginPasswordInput = page.locator('input[type="password"]');
	await expect(loginPasswordInput.first()).toBeVisible({ timeout: 15000 });
	await takeStepScreenshot(page, 'login-password-step');

	// Enter the same password
	await loginPasswordInput.first().fill(OPENMATES_TEST_ACCOUNT_PASSWORD);
	logRecoveryCheckpoint('Entered password for login.');

	// If 2FA is required, handle it
	// First submit the form to see if 2FA appears
	const loginButton = page.getByRole('button', { name: /login/i }).last();
	await loginButton.click();
	logRecoveryCheckpoint('Clicked login button.');

	// Wait for either 2FA input to appear or successful login (redirect to chat)
	await page.waitForTimeout(3000);
	await takeStepScreenshot(page, 'after-login-click');

	// Check if 2FA input appeared
	const tfaInput = page.locator('input[autocomplete="one-time-code"]');
	const tfaVisible = await tfaInput
		.first()
		.isVisible()
		.catch(() => false);

	if (tfaVisible && OPENMATES_TEST_ACCOUNT_OTP_KEY) {
		logRecoveryCheckpoint('2FA required for login, entering OTP.');
		const loginOtp = generateTotp(OPENMATES_TEST_ACCOUNT_OTP_KEY);
		await tfaInput.first().fill(loginOtp);
		await takeStepScreenshot(page, 'login-2fa-entered');

		// Submit login with 2FA
		await loginButton.click();
		logRecoveryCheckpoint('Submitted login with 2FA.');
	}

	// Wait for successful login - should redirect to chat
	await page.waitForURL(/chat|demo/, { timeout: 60000 });
	await takeStepScreenshot(page, 'login-success');
	logRecoveryCheckpoint('Login successful after account recovery! Test complete.');
});
