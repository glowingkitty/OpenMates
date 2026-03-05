/*
Purpose: Verifies password signup can skip OTP setup via explicit consent and still allow password login.
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

test('completes signup with skipped 2FA and can login with password', async ({
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
	test.setTimeout(240000);

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

	const consentToggle = page.locator('#limited-refund-consent-toggle');
	await setToggleChecked(consentToggle, true);

	await fillStripeCardDetails(page, STRIPE_TEST_CARD_NUMBER);

	await page.locator('.payment-form .buy-button').click();
	await expect(page.getByText(/purchase successful/i)).toBeVisible({ timeout: 60000 });

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

	logSignupCheckpoint('Skip-2FA signup + password login flow completed successfully.', {
		signupEmail
	});
});
