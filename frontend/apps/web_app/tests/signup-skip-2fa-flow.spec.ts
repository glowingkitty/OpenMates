/*
Purpose: Verifies password signup with skipped 2FA setup, re-login with password only, and account deletion via email OTP.
Architecture: Covers the signup route state machine and auth login flow from the deployed web app.
Architecture Doc: See docs/architecture/app-skills.md for async auth-related flow context.
Tests: N/A (this file is the Playwright E2E test entrypoint)
*/
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
	fillStripeCardDetails,
	getSignupTestDomain,
	getMailosaurServerId,
	buildSignupEmail,
	createMailosaurClient,
	assertNoMissingTranslations
} = require('./signup-flow-helpers');

const MAILOSAUR_API_KEY = process.env.MAILOSAUR_API_KEY;
const MAILOSAUR_SERVER_ID = process.env.MAILOSAUR_SERVER_ID;
const SIGNUP_TEST_EMAIL_DOMAINS = process.env.SIGNUP_TEST_EMAIL_DOMAINS;
const STRIPE_TEST_CARD_NUMBER = '4000002760000016';

test('completes signup with skipped 2FA, login with password, and delete account via email OTP', async ({
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
	test.setTimeout(360000);

	const logSignupCheckpoint = createSignupLogger('SIGNUP_SKIP_2FA_FLOW');
	const takeStepScreenshot = createStepScreenshotter(logSignupCheckpoint, {
		filenamePrefix: 'skip-2fa'
	});

	await archiveExistingScreenshots(logSignupCheckpoint);

	const signupDomain = getSignupTestDomain(SIGNUP_TEST_EMAIL_DOMAINS);
	test.skip(!signupDomain, 'SIGNUP_TEST_EMAIL_DOMAINS must include a test domain.');
	test.skip(!MAILOSAUR_API_KEY, 'MAILOSAUR_API_KEY is required for email validation.');
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

	await context.grantPermissions(['clipboard-read', 'clipboard-write']);

	const signupEmail = buildSignupEmail(signupDomain);
	const signupUsername = signupEmail.split('@')[0];
	const signupPassword = 'SignupTest!234Secure';

	await page.goto('/');
	await takeStepScreenshot(page, 'home');

	const headerLoginSignupButton = page.getByRole('button', {
		name: /login.*sign up|sign up/i
	});
	await expect(headerLoginSignupButton).toBeVisible();
	await headerLoginSignupButton.click();

	const loginTabs = page.locator('.login-tabs');
	await expect(loginTabs).toBeVisible();
	await loginTabs.getByRole('button', { name: /sign up/i }).click();
	await takeStepScreenshot(page, 'signup-alpha');
	await assertNoMissingTranslations(page);

	await page.getByRole('button', { name: /continue/i }).click();
	await takeStepScreenshot(page, 'basics-step');

	const emailInput = page.locator('input[type="email"][autocomplete="email"]');
	const usernameInput = page.locator('input[autocomplete="username"]');
	await expect(emailInput).toBeVisible();
	await emailInput.fill(signupEmail);
	await usernameInput.fill(signupUsername);

	const termsToggle = page.locator('#terms-agreed-toggle');
	const privacyToggle = page.locator('#privacy-agreed-toggle');
	await setToggleChecked(termsToggle, true);
	await setToggleChecked(privacyToggle, true);

	const emailRequestedAt = new Date().toISOString();
	await page.getByRole('button', { name: /create new account/i }).click();

	const openMailLink = page.getByRole('link', { name: /open mail app/i });
	await expect(openMailLink).toBeVisible({ timeout: 15000 });

	const confirmEmailMessage = await waitForMailosaurMessage({
		sentTo: signupEmail,
		receivedAfter: emailRequestedAt
	});
	const emailCode = extractSixDigitCode(confirmEmailMessage);
	expect(emailCode, 'Expected a 6-digit email confirmation code.').toBeTruthy();

	const confirmEmailInput = page.locator('input[inputmode="numeric"][maxlength="6"]');
	await confirmEmailInput.fill(emailCode);

	const passwordOption = page.getByRole('button', { name: /password/i });
	await expect(passwordOption).toBeVisible({ timeout: 30000 });
	await passwordOption.click();

	const passwordInputs = page.locator('input[autocomplete="new-password"]');
	await expect(passwordInputs).toHaveCount(2);
	await passwordInputs.nth(0).fill(signupPassword);
	await passwordInputs.nth(1).fill(signupPassword);

	await page.getByRole('button', { name: /continue/i }).click();
	await takeStepScreenshot(page, 'one-time-codes');

	const skipForNowButton = page.getByRole('button', { name: /skip for now/i });
	await expect(skipForNowButton).toBeVisible({ timeout: 20000 });
	await skipForNowButton.click();

	await expect(page.getByText(/be aware before skipping 2fa/i)).toBeVisible({ timeout: 15000 });
	await takeStepScreenshot(page, 'skip-2fa-consent');

	const skipConsentToggle = page.locator('#skip-2fa-consent-toggle');
	await setToggleChecked(skipConsentToggle, true);
	await expect(skipConsentToggle).toBeChecked();

	await page.getByRole('button', { name: /continue/i }).click();
	await takeStepScreenshot(page, 'recovery-key');
	logSignupCheckpoint('Skipped 2FA and continued to recovery key step.');

	const recoveryDownloadButton = page.getByRole('button', { name: /download/i }).first();
	const [recoveryDownload] = await Promise.all([
		page.waitForEvent('download'),
		recoveryDownloadButton.click()
	]);
	expect(await recoveryDownload.suggestedFilename()).toMatch(/recovery/i);

	const recoveryConfirmToggle = page.locator('#confirm-storage-toggle-step5');
	await setToggleChecked(recoveryConfirmToggle, true);

	await expect(page.locator('.credits-package-container .buy-button').first()).toBeVisible({
		timeout: 30000
	});
	await page.locator('.credits-package-container .buy-button').first().click();
	await takeStepScreenshot(page, 'payment-consent');
	logSignupCheckpoint('Reached payment consent step.');

	// Payment step: consent to limited refund to reveal payment form.
	// Wait for the consent toggle to appear — Stripe Elements must initialize first.
	const consentToggle = page.locator('#limited-refund-consent-toggle');
	await expect(consentToggle).toBeAttached({ timeout: 60000 });
	await setToggleChecked(consentToggle, true);
	await takeStepScreenshot(page, 'payment-form');
	logSignupCheckpoint('Payment consent accepted.');

	// Fill Stripe payment element with the test card.
	await fillStripeCardDetails(page, STRIPE_TEST_CARD_NUMBER);
	logSignupCheckpoint('Filled Stripe card details.');

	// Submit payment and wait for success.
	await page.locator('.payment-form .buy-button').click();
	await expect(page.getByText(/purchase successful/i)).toBeVisible({ timeout: 120000 });
	logSignupCheckpoint('Stripe payment completed successfully.');

	await page
		.getByRole('button', { name: /finish setup/i })
		.first()
		.click();
	await page.waitForURL(/chat/);
	await takeStepScreenshot(page, 'chat-after-signup');

	// Logout
	const settingsMenuButton = page.locator('.profile-container[role="button"]');
	await settingsMenuButton.click();
	await expect(page.locator('.settings-menu.visible')).toBeVisible({ timeout: 10000 });

	const logoutItem = page.getByRole('menuitem', { name: /logout|abmelden/i });
	await expect(logoutItem).toBeVisible({ timeout: 10000 });
	await logoutItem.click();

	await page.waitForFunction(() => window.location.hash.includes('demo-for-everyone'), null, {
		timeout: 60000
	});
	await takeStepScreenshot(page, 'logged-out');

	// Login with password only (no OTP expected)
	const loginButtonAfterLogout = page.getByRole('button', {
		name: /login.*sign up|sign up/i
	});
	await expect(loginButtonAfterLogout).toBeVisible({ timeout: 15000 });
	await loginButtonAfterLogout.click();

	const emailInputRelogin = page.locator('input[type="email"][name="username"]');
	await expect(emailInputRelogin).toBeVisible({ timeout: 10000 });
	await emailInputRelogin.fill(signupEmail);
	await page.getByRole('button', { name: /continue|next/i }).click();

	const passwordInputRelogin = page.locator('input[type="password"]');
	await expect(passwordInputRelogin.first()).toBeVisible({ timeout: 15000 });
	await passwordInputRelogin.first().fill(signupPassword);

	await expect(page.locator('input[autocomplete="one-time-code"]').first()).not.toBeVisible();

	const loginSubmitButton = page.locator('button[type="submit"]', { hasText: /log in|login/i });
	await expect(loginSubmitButton).toBeVisible({ timeout: 15000 });
	await loginSubmitButton.click();

	await page.waitForURL(/chat/, { timeout: 60000 });
	await takeStepScreenshot(page, 'relogin-success');
	await assertNoMissingTranslations(page);
	logSignupCheckpoint('Re-login with password completed. No 2FA/OTP was requested.');

	// ─── STEP: Delete Account via Email OTP ─────────────────────────────────────
	// Navigate to settings > account > delete account.
	// Password-only users (no 2FA, no passkey) get email OTP verification.

	const settingsMenuForDelete = page.locator('.profile-container[role="button"]');
	await settingsMenuForDelete.click();
	await expect(page.locator('.settings-menu.visible')).toBeVisible({ timeout: 10000 });

	// Navigate to Account settings
	await page.getByRole('menuitem', { name: /account/i }).click();
	await expect(page.getByRole('menuitem', { name: /delete/i })).toBeVisible();
	await page.getByRole('menuitem', { name: /delete/i }).click();
	await expect(page.locator('.delete-account-container')).toBeVisible();
	await takeStepScreenshot(page, 'delete-account');
	logSignupCheckpoint('Opened delete account settings.');

	// Confirm data deletion checkbox to enable deletion.
	const deleteConfirmToggle = page
		.locator('.delete-account-container input[type="checkbox"]')
		.first();
	await expect(deleteConfirmToggle).toBeAttached({ timeout: 60000 });
	await setToggleChecked(deleteConfirmToggle, true);
	await takeStepScreenshot(page, 'delete-account-confirmed');
	logSignupCheckpoint('Confirmed delete account data warning.');

	// Click delete button — should open the auth modal with email OTP (not 2FA).
	await page.locator('.delete-account-container .delete-button').click();
	const authModal = page.locator('.auth-modal');
	await expect(authModal).toBeVisible({ timeout: 15000 });
	await takeStepScreenshot(page, 'delete-account-auth-email-otp');

	// Verify this is the email OTP flow (not 2FA or passkey).
	const emailOtpSection = authModal.locator('.auth-email-otp');
	await expect(emailOtpSection).toBeVisible({ timeout: 10000 });
	logSignupCheckpoint('Auth modal shows email OTP flow (no 2FA, no passkey).');

	// Verify no 2FA input is shown.
	const twoFactorSection = authModal.locator('.auth-2fa');
	await expect(twoFactorSection).not.toBeVisible();

	// Click "Send verification code" button.
	const sendCodeButton = emailOtpSection.locator('.auth-btn');
	const deleteEmailRequestedAt = new Date().toISOString();
	await sendCodeButton.click();
	logSignupCheckpoint('Clicked send verification code for account deletion.');

	// Wait for the email OTP input to appear (means code was sent).
	const deleteOtpInput = emailOtpSection.locator('input.tfa-input');
	await expect(deleteOtpInput).toBeVisible({ timeout: 30000 });
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

	// Wait for success message indicating account was deleted.
	await expect(page.locator('.delete-account-container .success-message')).toBeVisible({
		timeout: 60000
	});
	await takeStepScreenshot(page, 'delete-account-success');
	logSignupCheckpoint('Account deletion confirmed via email OTP.');

	// Confirm logout redirect to demo chat after deletion.
	await page.waitForFunction(() => window.location.hash.includes('demo-for-everyone'), null, {
		timeout: 60000
	});
	await takeStepScreenshot(page, 'delete-account-redirected');
	logSignupCheckpoint('Returned to demo chat after account deletion.');

	logSignupCheckpoint(
		'Skip-2FA signup + password login + email OTP account deletion flow completed successfully.',
		{ signupEmail }
	);
});
