/*
@privacy-promise: cryptographic-erasure
Purpose: Verifies password signup, re-login with password only, and account deletion via email OTP.
Architecture: Covers the signup route state machine and auth login flow from the deployed web app.
Architecture Doc: See docs/architecture/app-skills.md for async auth-related flow context.
Tests: N/A (this file is the Playwright E2E test entrypoint)
*/
/* eslint-disable @typescript-eslint/no-require-imports */
export {};
const { test, expect } = require('./helpers/cookie-audit');
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
	buildSignupEmail,
	createEmailClient,
	checkEmailQuota,
	assertNoMissingTranslations,
	getE2EDebugUrl
} = require('./signup-flow-helpers');
const { openSignupInterface } = require('./helpers/chat-test-helpers');

const SIGNUP_TEST_EMAIL_DOMAINS = process.env.SIGNUP_TEST_EMAIL_DOMAINS;

test('completes password signup, login with password, and delete account via email OTP', async ({
	page,
	context
}: {
	page: any;
	context: any;
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
	// GHA runners are slower — increase from 360s to 480s for comfortable margin.
	test.setTimeout(480000);

	const logSignupCheckpoint = createSignupLogger('SIGNUP_PASSWORD_FLOW');
	const takeStepScreenshot = createStepScreenshotter(logSignupCheckpoint, {
		filenamePrefix: 'password-signup'
	});

	await archiveExistingScreenshots(logSignupCheckpoint);

	const signupDomain = getSignupTestDomain(SIGNUP_TEST_EMAIL_DOMAINS);
	test.skip(!signupDomain, 'SIGNUP_TEST_EMAIL_DOMAINS must include a test domain.');

	const emailClient = createEmailClient();
	test.skip(!emailClient, 'Email credentials required (GMAIL_* or MAILOSAUR_*).');

	const quota = await checkEmailQuota();
	test.skip(!quota.available, `Email quota reached (${quota.current}/${quota.limit}).`);

	if (!signupDomain) {
		throw new Error('Missing signup test domain after skip guard.');
	}

	const { waitForMailosaurMessage, extractSixDigitCode } = emailClient!;

	await context.grantPermissions(['clipboard-read', 'clipboard-write']);

	const signupEmail = buildSignupEmail(signupDomain);
	// For Gmail +alias emails (openmates.e2e+apr121910@gmail.com), extract only
	// the time-based part after '+' as the username, since '+' may not be valid
	// in usernames and the base part would collide across runs.
	const emailLocal = signupEmail.split('@')[0];
	const signupUsername = emailLocal.includes('+') ? emailLocal.split('+')[1] : emailLocal;
	const signupPassword = 'SignupTest!234Secure';

	await page.goto(getE2EDebugUrl('/'));

	// Dismiss "new version available" notification if present (service worker update)
	const versionBanner = page.getByTestId('notification');
	if (await versionBanner.isVisible({ timeout: 2000 }).catch(() => false)) {
		const dismissBtn = page.getByRole('button', { name: /dismiss notification/i });
		if (await dismissBtn.isVisible({ timeout: 1000 }).catch(() => false)) {
			await dismissBtn.click();
			await page.waitForTimeout(500);
		}
	}

	await takeStepScreenshot(page, 'home');

	await openSignupInterface(page);

	const loginTabs = page.getByTestId('login-tabs');
	await expect(loginTabs).toBeVisible();
	await loginTabs.getByRole('button', { name: /sign up/i }).click();
	await takeStepScreenshot(page, 'signup-alpha');
	await assertNoMissingTranslations(page);

	await page.getByRole('button', { name: /continue/i }).click();
	await takeStepScreenshot(page, 'basics-step');

	const emailInput = page.locator('input[type="email"][autocomplete="email"]');
	const usernameInput = page.locator('input[autocomplete="username"]');
	await expect(emailInput).toBeVisible({ timeout: 10000 });
	await emailInput.fill(signupEmail);
	await usernameInput.fill(signupUsername);

	const termsToggle = page.locator('#terms-agreed-toggle');
	const privacyToggle = page.locator('#privacy-agreed-toggle');
	await setToggleChecked(termsToggle, true);
	await setToggleChecked(privacyToggle, true);

	const emailRequestedAt = new Date().toISOString();
	await page.getByRole('button', { name: /create new account/i }).click();

	const openMailLink = page.getByRole('link', { name: /open mail app/i });
	await expect(openMailLink).toBeVisible({ timeout: 10000 });

	const confirmEmailMessage = await waitForMailosaurMessage({
		sentTo: signupEmail,
		receivedAfter: emailRequestedAt
	});
	const emailCode = extractSixDigitCode(confirmEmailMessage);
	expect(emailCode, 'Expected a 6-digit email confirmation code.').toBeTruthy();

	const confirmEmailInput = page.locator('input[inputmode="numeric"][maxlength="6"]');
	await confirmEmailInput.fill(emailCode);

	const passwordOption = page.locator('#signup-password-option');
	await expect(passwordOption).toBeVisible({ timeout: 10000 });
	await passwordOption.click();

	const passwordInputs = page.locator('input[autocomplete="new-password"]');
	await expect(passwordInputs).toHaveCount(2);
	await passwordInputs.nth(0).fill(signupPassword);
	await passwordInputs.nth(1).fill(signupPassword);

	await page.locator('#signup-password-continue').click();
	// Signup now finishes immediately after password account creation.
	await expect(page.getByRole('button', { name: /logout/i }).or(page.getByTestId('profile-container'))).toBeVisible({
		timeout: 30000
	});
	await takeStepScreenshot(page, 'chat-after-signup');

	// Logout
	const signupLogoutButton = page.getByRole('button', { name: /logout/i }).first();
	const logoutItem = page.getByRole('menuitem', { name: /logout|abmelden/i });
	if (await signupLogoutButton.isVisible({ timeout: 3000 }).catch(() => false)) {
		await signupLogoutButton.click();
	} else {
		const settingsMenuButton = page.getByTestId('profile-container');
		await settingsMenuButton.click();
		await expect(page.locator('[data-testid="settings-menu"].visible')).toBeVisible({ timeout: 10000 });
		await expect(logoutItem).toBeVisible({ timeout: 10000 });
		await logoutItem.click();
	}

	await page.waitForFunction(() => window.location.hash.includes('demo-for-everyone'), null, {
		timeout: 10000
	});
	await takeStepScreenshot(page, 'logged-out');
	await page.goto(getE2EDebugUrl('/'));
	await page.waitForLoadState('load');

	// Dismiss version banner again if it reappeared after logout
	if (await versionBanner.isVisible({ timeout: 2000 }).catch(() => false)) {
		const dismissBtn2 = page.getByRole('button', { name: /dismiss notification/i });
		if (await dismissBtn2.isVisible({ timeout: 1000 }).catch(() => false)) {
			await dismissBtn2.click();
			await page.waitForTimeout(500);
		}
	}

	// Login with password only (no OTP expected)
	await openSignupInterface(page);

	// Switch to Login tab (dialog may default to Sign up tab after a fresh signup)
	const loginTab = page.getByTestId('tab-login');
	if (await loginTab.isVisible({ timeout: 3000 }).catch(() => false)) {
		await loginTab.click();
		await page.waitForTimeout(500);
	}

	const emailLastUsedHint = page.getByTestId('last-used-auth-method-email');
	if (await emailLastUsedHint.isVisible({ timeout: 3000 }).catch(() => false)) {
		await expect(page.getByTestId('last-used-auth-method-passkey')).not.toBeVisible();
		await page.getByTestId('clear-last-used-auth-method').click();
		await expect(emailLastUsedHint).not.toBeVisible();
		await expect(page.getByTestId('clear-last-used-auth-method')).not.toBeVisible();
		logSignupCheckpoint('Verified and cleared email/password last-used hint.');
	} else {
		logSignupCheckpoint('Email/password last-used hint was not present; continuing with explicit login.');
	}

	// Use broader selector to handle both login dialog variants (name="username" or id="login-email-input").
	const emailInputRelogin = page.locator('#login-email-input, input[type="email"][name="username"]').first();
	await expect(emailInputRelogin).toBeVisible({ timeout: 10000 });
	await emailInputRelogin.fill(signupEmail);
	await page.getByRole('button', { name: /continue|next/i }).click();

	const passwordInputRelogin = page.locator('#login-password-input');
	await expect(passwordInputRelogin.first()).toBeVisible({ timeout: 10000 });
	await passwordInputRelogin.first().fill(signupPassword);

	await expect(page.locator('#login-otp-input').first()).not.toBeVisible();

	const loginSubmitButton = page.locator('button[type="submit"]', { hasText: /log in|login/i });
	await expect(loginSubmitButton).toBeVisible({ timeout: 10000 });
	await loginSubmitButton.click();

	await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 30000 });
	await takeStepScreenshot(page, 'relogin-success');
	await assertNoMissingTranslations(page);
	logSignupCheckpoint('Re-login with password completed. No 2FA/OTP was requested.');

	// ─── STEP: Delete Account via Email OTP ─────────────────────────────────────
	// Navigate to settings > account > delete account.
	// Password-only users (no 2FA, no passkey) get email OTP verification.

	const settingsMenuForDelete = page.getByTestId('profile-container');
	await settingsMenuForDelete.click();
	await expect(page.locator('[data-testid="settings-menu"].visible')).toBeVisible({ timeout: 10000 });

	// Navigate to Account settings
	await page.getByRole('menuitem', { name: /account/i }).click();
	await expect(page.getByRole('menuitem', { name: /delete/i })).toBeVisible();
	await page.getByRole('menuitem', { name: /delete/i }).click();
	await expect(page.getByTestId('delete-account-container')).toBeVisible();
	await takeStepScreenshot(page, 'delete-account');
	logSignupCheckpoint('Opened delete account settings.');

	// Confirm data deletion checkbox to enable deletion.
	const deleteConfirmToggle = page
		.getByTestId('delete-account-container').locator('input[type="checkbox"]')
		.first();
	await expect(deleteConfirmToggle).toBeAttached({ timeout: 10000 });
	await setToggleChecked(deleteConfirmToggle, true);
	await takeStepScreenshot(page, 'delete-account-confirmed');
	logSignupCheckpoint('Confirmed delete account data warning.');

	// Click delete button — should open the auth modal with email OTP (not 2FA).
	await page.getByTestId('delete-account-container').getByTestId('delete-button').click();
	const authModal = page.getByTestId('auth-modal');
	await expect(authModal).toBeVisible({ timeout: 10000 });
	await takeStepScreenshot(page, 'delete-account-auth-email-otp');

	// Verify this is the email OTP flow (not 2FA or passkey).
	const emailOtpSection = authModal.getByTestId('auth-email-otp');
	await expect(emailOtpSection).toBeVisible({ timeout: 10000 });
	logSignupCheckpoint('Auth modal shows email OTP flow (no 2FA, no passkey).');

	// Verify no 2FA input is shown.
	const twoFactorSection = authModal.getByTestId('auth-2fa');
	await expect(twoFactorSection).not.toBeVisible();

	// Click "Send verification code" button.
	const sendCodeButton = emailOtpSection.getByTestId('auth-btn');
	const deleteEmailRequestedAt = new Date().toISOString();
	await sendCodeButton.click();
	logSignupCheckpoint('Clicked send verification code for account deletion.');

	// Wait for the email OTP input to appear (means code was sent).
	// The backend may fail with "Failed to retrieve email" if encryption keys aren't
	// synced yet for the freshly created account. Retry once after a short wait.
	const deleteOtpInput = emailOtpSection.locator('input[inputmode="numeric"]');
	const otpVisible = await deleteOtpInput.isVisible({ timeout: 5000 }).catch(() => false);
	if (!otpVisible) {
		const errorText = await page.getByText(/failed to retrieve email/i).isVisible({ timeout: 2000 }).catch(() => false);
		if (errorText) {
			logSignupCheckpoint('Got "Failed to retrieve email" — retrying after wait.');
			await page.waitForTimeout(3000);
			await sendCodeButton.click();
		}
	}
	await expect(deleteOtpInput).toBeVisible({ timeout: 10000 });
	await takeStepScreenshot(page, 'delete-account-otp-input');

	// Get the verification code from Mailosaur email.
	const deleteVerificationMessage = await waitForMailosaurMessage({
		sentTo: signupEmail,
		receivedAfter: deleteEmailRequestedAt
	});
	const deleteVerificationCode = extractSixDigitCode(deleteVerificationMessage);
	expect(
		deleteVerificationCode,
		'Expected a 6-digit action verification code for deletion.'
	).toBeTruthy();
	logSignupCheckpoint('Received action verification email with code.');

	// Enter the 6-digit code (auto-submits on 6th digit).
	await deleteOtpInput.fill(deleteVerificationCode);
	logSignupCheckpoint('Entered action verification code to confirm deletion.');

	// Wait for redirect to demo chat after account deletion.
	// The deletion flow sets a brief success message then navigates away,
	// so we wait for the redirect rather than the transient success message.
	await page.waitForFunction(() => window.location.hash.includes('demo-for-everyone'), null, {
		timeout: 10000
	});
	await takeStepScreenshot(page, 'delete-account-redirected');
	logSignupCheckpoint('Account deleted and redirected to demo chat.');

	logSignupCheckpoint(
		'Password signup + password login + email OTP account deletion flow completed successfully.',
		{ signupEmail }
	);
});
