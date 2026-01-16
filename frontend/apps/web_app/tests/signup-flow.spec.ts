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
	fillStripeCardDetails,
	getSignupTestDomain,
	getMailosaurServerId,
	buildSignupEmail,
	createMailosaurClient,
	generateTotp
} = require('./signup-flow-helpers');

/**
 * Full signup flow test (password + 2FA + purchase) against a deployed web app.
 *
 * ARCHITECTURE NOTES:
 * - The test is intentionally self-contained: we avoid adding npm/pnpm deps by
 *   using built-in Node.js crypto for TOTP and Mailosaur's raw REST API via fetch.
 * - The email confirmation code and purchase confirmation email are fetched
 *   from Mailosaur (server + API key must be provided via env vars).
 * - We generate a unique signup email using SIGNUP_TEST_EMAIL_DOMAINS so the
 *   backend domain allowlist can be enforced while still allowing test signups.
 *
 * REQUIRED ENV VARS:
 * - SIGNUP_TEST_EMAIL_DOMAINS: Comma-separated list of allowed test domains.
 * - MAILOSAUR_API_KEY: Mailosaur API key for test mailbox access.
 * - MAILOSAUR_SERVER_ID: Mailosaur server ID used by the test domain.
 */

const MAILOSAUR_API_KEY = process.env.MAILOSAUR_API_KEY;
const MAILOSAUR_SERVER_ID = process.env.MAILOSAUR_SERVER_ID;
const SIGNUP_TEST_EMAIL_DOMAINS = process.env.SIGNUP_TEST_EMAIL_DOMAINS;
const STRIPE_TEST_CARD_NUMBER = '4000002760000016';

test('completes full signup flow with email + 2FA + purchase', async ({ page, context }: { page: any; context: any }) => {
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
	// Allow extra time for purchase confirmation email + account deletion cleanup.
	test.setTimeout(240000);

	const logSignupCheckpoint = createSignupLogger('SIGNUP_FLOW');
	const takeStepScreenshot = createStepScreenshotter(logSignupCheckpoint);

	await archiveExistingScreenshots(logSignupCheckpoint);

	const signupDomain = getSignupTestDomain(SIGNUP_TEST_EMAIL_DOMAINS);
	test.skip(!signupDomain, 'SIGNUP_TEST_EMAIL_DOMAINS must include a test domain.');
	test.skip(!MAILOSAUR_API_KEY, 'MAILOSAUR_API_KEY is required for email validation.');
	if (!signupDomain) {
		throw new Error('Missing signup test domain after skip guard.');
	}
	const mailosaurServerId = getMailosaurServerId(signupDomain, MAILOSAUR_SERVER_ID);
	if (!mailosaurServerId) {
		throw new Error('MAILOSAUR_SERVER_ID is missing and could not be derived from the signup domain.');
	}
	const {
		waitForMailosaurMessage,
		extractSixDigitCode,
		extractRefundLink,
		extractMessageLinks
	} = createMailosaurClient({
		apiKey: MAILOSAUR_API_KEY,
		serverId: mailosaurServerId
	});

	// Grant clipboard permissions so "Copy" actions can be exercised reliably.
	await context.grantPermissions(['clipboard-read', 'clipboard-write']);

	const signupEmail = buildSignupEmail(signupDomain);
	const signupUsername = signupEmail.split('@')[0];
	const signupPassword = 'SignupTest!234';
	logSignupCheckpoint('Initialized signup identity.', { signupEmail });

	// Base URL comes from PLAYWRIGHT_TEST_BASE_URL or the default in config.
	await page.goto('/');
	await takeStepScreenshot(page, 'home');

	// Open the login/signup dialog from the header.
	const headerLoginSignupButton = page.getByRole('button', {
		name: /login.*sign up|sign up/i
	});
	await expect(headerLoginSignupButton).toBeVisible();
	await headerLoginSignupButton.click();
	await takeStepScreenshot(page, 'login-dialog');
	logSignupCheckpoint('Opened login dialog.');

	// Switch to the signup tab inside the login dialog.
	const loginTabs = page.locator('.login-tabs');
	await expect(loginTabs).toBeVisible();
	await loginTabs.getByRole('button', { name: /sign up/i }).click();
	await takeStepScreenshot(page, 'signup-alpha');

	// Alpha disclaimer: verify outbound links exist and continue.
	// Use href-based locators because link accessible names can vary by locale.
	const githubLink = page.locator('a[href*="github.com"]');
	const instagramLink = page.locator('a[href*="instagram.com"]');
	await expect(githubLink.first()).toBeVisible();
	await expect(instagramLink.first()).toBeVisible();

	await page.getByRole('button', { name: /continue/i }).click();
	await takeStepScreenshot(page, 'basics-step');
	logSignupCheckpoint('Reached basics step.');

	// Basics step: fill email/username and exercise key toggles.
	const emailInput = page.locator('input[type="email"][autocomplete="email"]');
	const usernameInput = page.locator('input[autocomplete="username"]');
	await expect(emailInput).toBeVisible();
	await emailInput.fill(signupEmail);
	await usernameInput.fill(signupUsername);
	await takeStepScreenshot(page, 'basics-filled');

	// Toggle "Stay logged in" on (explicitly test toggle wiring).
	const stayLoggedInToggle = page.locator('#stayLoggedIn');
	await setToggleChecked(stayLoggedInToggle, true);
	await expect(stayLoggedInToggle).toBeChecked();

	// Toggle newsletter on then off so we test the control without sending a subscription.
	const newsletterToggle = page.locator('#newsletter-subscribe-toggle');
	await setToggleChecked(newsletterToggle, true);
	await expect(newsletterToggle).toBeChecked();
	await setToggleChecked(newsletterToggle, false);
	await expect(newsletterToggle).not.toBeChecked();

	// Terms and privacy consent are required to proceed.
	const termsToggle = page.locator('#terms-agreed-toggle');
	const privacyToggle = page.locator('#privacy-agreed-toggle');
	await setToggleChecked(termsToggle, true);
	await setToggleChecked(privacyToggle, true);
	await expect(termsToggle).toBeChecked();
	await expect(privacyToggle).toBeChecked();

	// Submit signup basics and trigger the confirmation email.
	const emailRequestedAt = new Date().toISOString();
	await page.getByRole('button', { name: /create new account/i }).click();
	await takeStepScreenshot(page, 'confirm-email');
	logSignupCheckpoint('Submitted signup basics, waiting for email confirmation.');

	// Confirm email step: verify "Open mail app" link and enter OTP.
	const openMailLink = page.getByRole('link', { name: /open mail app/i });
	await expect(openMailLink).toHaveAttribute('href', /^mailto:/i);

	logSignupCheckpoint('Polling Mailosaur for confirmation email.');
	const confirmEmailMessage = await waitForMailosaurMessage({
		sentTo: signupEmail,
		receivedAfter: emailRequestedAt
	});
	const emailCode = extractSixDigitCode(confirmEmailMessage);
	expect(emailCode, 'Expected a 6-digit email confirmation code.').toBeTruthy();
	logSignupCheckpoint('Received email confirmation code.');

	const confirmEmailInput = page.locator('input[inputmode="numeric"][maxlength="6"]');
	await confirmEmailInput.fill(emailCode);

	// Secure account step: choose password-based setup.
	const passwordOption = page.getByRole('button', { name: /password/i });
	await expect(passwordOption).toBeVisible();
	await takeStepScreenshot(page, 'secure-account');
	await passwordOption.click();
	await takeStepScreenshot(page, 'password-step');

	// Password step: fill and validate password fields.
	const passwordInputs = page.locator('input[autocomplete="new-password"]');
	await expect(passwordInputs).toHaveCount(2);
	await passwordInputs.nth(0).fill(signupPassword);
	await passwordInputs.nth(1).fill(signupPassword);
	await takeStepScreenshot(page, 'password-filled');
	logSignupCheckpoint('Password fields completed.');

	// Password manager link should be present (no navigation needed).
	const passwordManagerLink = page.getByRole('link', { name: /password manager/i });
	await expect(passwordManagerLink).toHaveAttribute('href', /^https?:/i);

	await page.getByRole('button', { name: /continue/i }).click();
	await takeStepScreenshot(page, 'one-time-codes');
	logSignupCheckpoint('Reached one-time codes step.');

	// One-time codes step: show QR, copy secret, validate selectable secret input.
	const qrButton = page.getByRole('button', { name: /scan via 2fa app/i });
	await qrButton.click();
	await expect(page.locator('.qr-code')).toBeVisible();
	await takeStepScreenshot(page, 'one-time-codes-qr');
	await qrButton.click();
	await expect(page.locator('.qr-code')).toBeHidden();

	const copySecretButton = page.getByRole('button', { name: /copy secret/i });
	await copySecretButton.click();

	const secretInput = page.locator('input[aria-label="2FA Secret Key"]');
	await expect(secretInput).toBeVisible();
	await takeStepScreenshot(page, 'one-time-codes-secret');
	await secretInput.click();
	const secretInputSelected = await secretInput.evaluate((element: HTMLInputElement) => {
		const input = element as HTMLInputElement;
		return input.selectionStart === 0 && input.selectionEnd === input.value.length;
	});
	expect(secretInputSelected).toBe(true);

	const tfaSecret = await secretInput.inputValue();
	expect(tfaSecret, 'Expected a 2FA secret to be available after copy.').toBeTruthy();
	logSignupCheckpoint('Retrieved 2FA secret.');

	// Enter the generated TOTP to complete 2FA setup.
	const otpCode = generateTotp(tfaSecret);
	const otpInput = page.locator('#otp-code-input');
	await otpInput.fill(otpCode);
	logSignupCheckpoint('Entered OTP code.');

	// 2FA app reminder: pick an app name from suggestions and continue.
	const appNameInput = page.locator('input[placeholder*="app name"]');
	await appNameInput.click();
	await appNameInput.fill('Google');
	await takeStepScreenshot(page, 'tfa-app-reminder');
	const appResult = page.getByRole('button', { name: /google authenticator/i });
	await appResult.click();

	const tfaContinueButton = page.getByRole('button', { name: /continue/i });
	await tfaContinueButton.click();
	await takeStepScreenshot(page, 'backup-codes');
	logSignupCheckpoint('Reached backup codes step.');

	// Backup codes step: download and confirm stored.
	const backupDownloadButton = page.getByRole('button', { name: /download/i }).first();
	const [backupDownload] = await Promise.all([
		page.waitForEvent('download'),
		backupDownloadButton.click()
	]);
	expect(await backupDownload.suggestedFilename()).toMatch(/backup/i);
	logSignupCheckpoint('Downloaded backup codes.');

	const backupConfirmToggle = page.locator('#confirm-storage-toggle-step5');
	await setToggleChecked(backupConfirmToggle, true);
	await takeStepScreenshot(page, 'backup-codes-confirmed');
	logSignupCheckpoint('Confirmed backup code storage.');

	// Recovery key step: download, copy, print, and confirm stored.
	const recoveryDownloadButton = page.getByRole('button', { name: /download/i }).first();
	const [recoveryDownload] = await Promise.all([
		page.waitForEvent('download'),
		recoveryDownloadButton.click()
	]);
	await takeStepScreenshot(page, 'recovery-key');
	expect(await recoveryDownload.suggestedFilename()).toMatch(/recovery/i);
	logSignupCheckpoint('Downloaded recovery key.');

	const recoveryCopyButton = page.getByRole('button', { name: /^copy$/i });
	await recoveryCopyButton.click();

	const [printPage] = await Promise.all([
		context.waitForEvent('page'),
		page.getByRole('button', { name: /print/i }).click()
	]);
	await printPage.close();
	await takeStepScreenshot(page, 'recovery-key-actions');
	logSignupCheckpoint('Completed recovery key actions.');

	const recoveryConfirmToggle = page.locator('#confirm-storage-toggle-step5');
	await setToggleChecked(recoveryConfirmToggle, true);
	await takeStepScreenshot(page, 'credits-step');
	logSignupCheckpoint('Reached credits step.');

	// Credits step: exercise gift card path (cancel) and navigation buttons.
	const giftCardButton = page.locator('.gift-card-button');
	await giftCardButton.scrollIntoViewIfNeeded();
	await giftCardButton.click();
	await takeStepScreenshot(page, 'credits-giftcard');
	await page.getByRole('button', { name: /cancel/i }).click();
	await takeStepScreenshot(page, 'credits-ready');
	logSignupCheckpoint('Completed credits step actions.');

	const moreButton = page.getByRole('button', { name: /more/i });
	const lessButton = page.getByRole('button', { name: /less/i });
	if (await moreButton.isVisible()) {
		await moreButton.click();
	}
	if (await lessButton.isVisible()) {
		await lessButton.click();
	}

	// Purchase credits to proceed to payment step.
	await page.locator('.credits-package-container .buy-button').first().click();
	await takeStepScreenshot(page, 'payment-consent');
	logSignupCheckpoint('Reached payment consent step.');

	// Payment step: consent to limited refund to reveal payment form.
	const consentToggle = page.locator('#limited-refund-consent-toggle');
	await setToggleChecked(consentToggle, true);
	await takeStepScreenshot(page, 'payment-form');
	logSignupCheckpoint('Payment consent accepted.');

	// Payment security info button should open a Stripe privacy page (close immediately).
	const securityInfoButton = page.locator('.payment-form .text-button').first();
	await securityInfoButton.scrollIntoViewIfNeeded();
	const [securityInfoPage] = await Promise.all([
		context.waitForEvent('page'),
		securityInfoButton.click()
	]);
	await securityInfoPage.close();
	logSignupCheckpoint('Closed payment security info page.');

	// Fill Stripe payment element with the test card.
	await fillStripeCardDetails(page, STRIPE_TEST_CARD_NUMBER);
	logSignupCheckpoint('Filled Stripe card details.');

	// Submit payment and wait for success.
	const paymentSubmittedAt = new Date().toISOString();
	await page.locator('.payment-form .buy-button').click();
	await expect(page.getByText(/purchase successful/i)).toBeVisible({ timeout: 60000 });
	await takeStepScreenshot(page, 'payment-success');
	logSignupCheckpoint('Purchase completed successfully.');

	// Auto top-up step: finish setup and confirm redirect into the app.
	await page.getByRole('button', { name: /finish setup/i }).first().click();
	await page.waitForURL(/chat/);
	await takeStepScreenshot(page, 'chat');
	logSignupCheckpoint('Arrived in chat after signup.');

	// Purchase confirmation email: verify key content and refund link.
	logSignupCheckpoint('Waiting for purchase confirmation email.');
	const purchaseEmail = await waitForMailosaurMessage({
		sentTo: signupEmail,
		subjectContains: 'Purchase confirmation',
		receivedAfter: paymentSubmittedAt,
		timeoutMs: 180000
	});
	logSignupCheckpoint('Received purchase confirmation email.');

	const purchaseText = purchaseEmail.text?.body || '';
	expect(purchaseText).toMatch(/thanks for your purchase/i);
	expect(purchaseText).toMatch(/invoice/i);

	const refundLink = extractRefundLink(purchaseEmail);
	if (!refundLink) {
		const allLinks = extractMessageLinks(purchaseEmail);
		logSignupCheckpoint('Refund link missing from purchase email.', {
			linkCount: allLinks.length,
			links: allLinks.slice(0, 10),
			textSnippet: purchaseText.slice(0, 300)
		});
	}
	expect(refundLink, 'Expected a refund link in the purchase confirmation email.').toBeTruthy();
	if (!refundLink) {
		throw new Error('Refund link missing from purchase confirmation email.');
	}
	expect(() => new URL(refundLink)).not.toThrow();
	logSignupCheckpoint('Validated refund link from purchase email.', {
		refundLink: refundLink.slice(0, 120)
	});

	// Open settings to verify credit balance and delete the test account.
	const settingsMenuButton = page.locator('.profile-container[role="button"]');
	await settingsMenuButton.click();
	await expect(page.locator('.settings-menu.visible')).toBeVisible();
	await takeStepScreenshot(page, 'settings-menu-open');
	logSignupCheckpoint('Opened settings menu for credit verification.');

	// Confirm credits reflect the purchase (should be non-zero after payment).
	const creditsAmount = page.locator('.credits-amount');
	await expect(creditsAmount).toBeVisible();
	const creditsText = (await creditsAmount.textContent()) || '';
	const creditsValue = Number.parseInt(creditsText.replace(/[^\d]/g, ''), 10);
	expect(creditsValue, 'Expected purchased credits to be visible in settings.').toBeGreaterThan(0);
	logSignupCheckpoint('Verified purchased credits in settings.', { creditsValue, creditsText });

	// Navigate to Account settings and open delete account flow.
	await page.getByRole('menuitem', { name: /account/i }).click();
	await expect(page.getByRole('menuitem', { name: /delete/i })).toBeVisible();
	await page.getByRole('menuitem', { name: /delete/i }).click();
	await expect(page.locator('.delete-account-container')).toBeVisible();
	await takeStepScreenshot(page, 'delete-account');
	logSignupCheckpoint('Opened delete account settings.');

	// Confirm data deletion checkbox to enable deletion.
	// Use the delete account toggle directly because the label text is lengthy and localized.
	const deleteConfirmToggle = page.locator('.delete-account-container input[type="checkbox"]').first();
	await expect(deleteConfirmToggle).toBeAttached({ timeout: 60000 });
	await setToggleChecked(deleteConfirmToggle, true);
	await takeStepScreenshot(page, 'delete-account-confirmed');
	logSignupCheckpoint('Confirmed delete account data warning.');

	// Start deletion and complete 2FA authentication.
	await page.locator('.delete-account-container .delete-button').click();
	const authModal = page.locator('.auth-modal');
	await expect(authModal).toBeVisible();
	await takeStepScreenshot(page, 'delete-account-auth');

	const deleteOtpInput = authModal.locator('input.tfa-input');
	await expect(deleteOtpInput).toBeVisible();
	await deleteOtpInput.fill(generateTotp(tfaSecret));
	logSignupCheckpoint('Submitted 2FA code to confirm account deletion.');

	await expect(page.locator('.delete-account-container .success-message')).toBeVisible({ timeout: 60000 });
	await takeStepScreenshot(page, 'delete-account-success');
	logSignupCheckpoint('Account deletion confirmed.');

	// Confirm logout redirect to demo chat after deletion.
	await page.waitForFunction(() => window.location.hash.includes('demo-welcome'), null, { timeout: 60000 });
	logSignupCheckpoint('Returned to demo chat after account deletion.');
});

