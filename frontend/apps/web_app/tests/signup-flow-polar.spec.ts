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
	buildSignupEmail,
	createMailosaurClient,
	generateTotp,
	assertNoMissingTranslations
} = require('./signup-flow-helpers');

/**
 * Full signup flow test using Polar as the payment provider (non-EU flow).
 *
 * ARCHITECTURE NOTES:
 * - Since Playwright tests run from a fixed IP (not a non-EU IP), we can't rely
 *   on IP-based geo-detection to get Polar automatically. Instead, we click the
 *   "Pay with a non-EU card" switch button that appears in the Stripe payment form.
 *   This simulates a non-EU user switching to Polar.
 * - Polar checkout opens as a full-screen iframe overlay appended to document.body.
 *   We interact with it via Playwright's frameLocator.
 * - Polar uses Stripe's test infrastructure in sandbox mode, so Stripe test cards
 *   work inside the Polar checkout iframe.
 * - This test is SKIPPED when Polar is not yet configured in Vault
 *   (i.e., when ?provider_override=polar falls back to 'stripe').
 *
 * POLAR SANDBOX TEST CARD:
 * - Card number: 4242 4242 4242 4242 (Stripe's universal test card, works in Polar sandbox)
 * - Expiry: any future date (e.g. 12/34)
 * - CVC: any 3 digits (e.g. 123)
 * - Name: any non-empty name
 *
 * REQUIRED ENV VARS:
 * - SIGNUP_TEST_EMAIL_DOMAINS: Comma-separated list of allowed test domains.
 * - MAILOSAUR_API_KEY: Mailosaur API key for test mailbox access.
 * - MAILOSAUR_SERVER_ID: Mailosaur server ID used by the test domain.
 * - PLAYWRIGHT_TEST_BASE_URL: Base URL of the deployed dev web app.
 *
 * POLAR VAULT PREREQUISITE:
 * - Polar secrets must be configured in Vault at kv/data/providers/polar:
 *     production_access_token, sandbox_access_token,
 *     production_webhook_secret, sandbox_webhook_secret
 * - Without these, ?provider_override=polar falls back to 'stripe' and this test skips.
 */

const MAILOSAUR_API_KEY = process.env.MAILOSAUR_API_KEY;
const MAILOSAUR_SERVER_ID = process.env.MAILOSAUR_SERVER_ID;
const SIGNUP_TEST_EMAIL_DOMAINS = process.env.SIGNUP_TEST_EMAIL_DOMAINS;
const PLAYWRIGHT_TEST_BASE_URL =
	process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org';

// Polar uses Stripe's test infrastructure in sandbox, so Stripe test cards work.
// This is the standard Stripe success card — always succeeds in test/sandbox mode.
const POLAR_SANDBOX_TEST_CARD = '4242424242424242';

/**
 * Check if the Polar payment provider is active on the current environment.
 * Calls /v1/payments/config?provider_override=polar and returns true only if
 * the response returns provider='polar' (not the Stripe fallback).
 *
 * Used as a skip guard — the test is meaningless if Polar isn't configured.
 */
async function isPolarConfigured(baseUrl: string, apiKey?: string): Promise<boolean> {
	try {
		const apiBaseUrl = baseUrl.replace('app.', 'api.').replace(/\/$/, '');
		const headers: Record<string, string> = { 'Content-Type': 'application/json' };
		if (apiKey) {
			headers['Authorization'] = `Bearer ${apiKey}`;
		}
		const response = await fetch(`${apiBaseUrl}/v1/payments/config?provider_override=polar`, {
			headers
		});
		if (!response.ok) {
			return false;
		}
		const data = await response.json();
		return data?.provider === 'polar';
	} catch {
		return false;
	}
}

test('completes full Polar signup flow with email + 2FA + non-EU payment', async ({
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
	// Allow extra time: Polar checkout overlay + purchase confirmation email + account deletion.
	test.setTimeout(300000);

	const logSignupCheckpoint = createSignupLogger('POLAR_SIGNUP_FLOW');
	const takeStepScreenshot = createStepScreenshotter(logSignupCheckpoint, {
		filenamePrefix: 'polar'
	});

	await archiveExistingScreenshots(logSignupCheckpoint);

	// ─── Skip guards ─────────────────────────────────────────────────────────────

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

	// Skip if Polar is not yet configured in Vault on this environment.
	// When Polar secrets are missing, ?provider_override=polar falls back to 'stripe'.
	// Running this test against the Stripe fallback would produce a false passing result.
	const polarReady = await isPolarConfigured(PLAYWRIGHT_TEST_BASE_URL);
	if (!polarReady) {
		test.skip(
			true,
			'Polar is not configured in Vault on this environment — add SECRET__POLAR__* ' +
				'secrets to kv/data/providers/polar in Vault to enable Polar E2E tests.'
		);
		return;
	}
	logSignupCheckpoint('Polar provider confirmed active in environment.');

	const { waitForMailosaurMessage, extractSixDigitCode, extractRefundLink, extractMessageLinks } =
		createMailosaurClient({
			apiKey: MAILOSAUR_API_KEY,
			serverId: mailosaurServerId
		});

	// Grant clipboard permissions so "Copy" actions can be exercised reliably.
	await context.grantPermissions(['clipboard-read', 'clipboard-write']);

	const signupEmail = buildSignupEmail(signupDomain);
	const signupUsername = signupEmail.split('@')[0];
	const signupPassword = 'PolarTest!234';
	logSignupCheckpoint('Initialized Polar signup identity.', { signupEmail });

	// ─── Navigation & signup basics ──────────────────────────────────────────────

	await page.goto('/');
	await takeStepScreenshot(page, 'home');

	const headerLoginSignupButton = page.getByRole('button', {
		name: /login.*sign up|sign up/i
	});
	await expect(headerLoginSignupButton).toBeVisible();
	await headerLoginSignupButton.click();
	await takeStepScreenshot(page, 'login-dialog');
	logSignupCheckpoint('Opened login dialog.');

	await assertNoMissingTranslations(page);
	logSignupCheckpoint('No missing translations on login dialog.');

	const loginTabs = page.locator('.login-tabs');
	await expect(loginTabs).toBeVisible();
	await loginTabs.getByRole('button', { name: /sign up/i }).click();
	await takeStepScreenshot(page, 'signup-alpha');

	await assertNoMissingTranslations(page);
	logSignupCheckpoint('No missing translations on signup alpha step.');

	const githubLink = page.locator('a[href*="github.com"]');
	const instagramLink = page.locator('a[href*="instagram.com"]');
	await expect(githubLink.first()).toBeVisible();
	await expect(instagramLink.first()).toBeVisible();

	await page.getByRole('button', { name: /continue/i }).click();
	await takeStepScreenshot(page, 'basics-step');
	await assertNoMissingTranslations(page);
	logSignupCheckpoint('Reached basics step.');

	const emailInput = page.locator('input[type="email"][autocomplete="email"]');
	const usernameInput = page.locator('input[autocomplete="username"]');
	await expect(emailInput).toBeVisible();
	await emailInput.fill(signupEmail);
	await usernameInput.fill(signupUsername);
	await takeStepScreenshot(page, 'basics-filled');

	const stayLoggedInToggle = page.locator('#stayLoggedIn');
	await setToggleChecked(stayLoggedInToggle, true);
	await expect(stayLoggedInToggle).toBeChecked();

	const termsToggle = page.locator('#terms-agreed-toggle');
	const privacyToggle = page.locator('#privacy-agreed-toggle');
	await setToggleChecked(termsToggle, true);
	await setToggleChecked(privacyToggle, true);
	await expect(termsToggle).toBeChecked();
	await expect(privacyToggle).toBeChecked();

	const emailRequestedAt = new Date().toISOString();
	await page.getByRole('button', { name: /create new account/i }).click();
	logSignupCheckpoint('Submitted signup basics, waiting for email confirmation.');

	// ─── Email confirmation ───────────────────────────────────────────────────────

	const openMailLink = page.getByRole('link', { name: /open mail app/i });
	await expect(openMailLink).toBeVisible({ timeout: 15000 });
	await takeStepScreenshot(page, 'confirm-email');

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

	// ─── Password setup ───────────────────────────────────────────────────────────

	const passwordOption = page.getByRole('button', { name: /password/i });
	await expect(passwordOption).toBeVisible();
	await takeStepScreenshot(page, 'secure-account');
	await passwordOption.click();
	await takeStepScreenshot(page, 'password-step');

	const passwordInputs = page.locator('input[autocomplete="new-password"]');
	await expect(passwordInputs).toHaveCount(2);
	await passwordInputs.nth(0).fill(signupPassword);
	await passwordInputs.nth(1).fill(signupPassword);
	await takeStepScreenshot(page, 'password-filled');
	logSignupCheckpoint('Password fields completed.');

	await page.getByRole('button', { name: /continue/i }).click();
	await takeStepScreenshot(page, 'one-time-codes');
	logSignupCheckpoint('Reached one-time codes step.');

	// ─── 2FA setup ────────────────────────────────────────────────────────────────

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

	const tfaSecret = await secretInput.inputValue();
	expect(tfaSecret, 'Expected a 2FA secret to be available after copy.').toBeTruthy();
	logSignupCheckpoint('Retrieved 2FA secret.');

	const otpCode = generateTotp(tfaSecret);
	const otpInput = page.locator('#otp-code-input');
	await otpInput.fill(otpCode);
	logSignupCheckpoint('Entered OTP code.');

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

	// ─── Backup codes + recovery key ─────────────────────────────────────────────

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

	// ─── Credits step ─────────────────────────────────────────────────────────────

	const recoveryConfirmToggle = page.locator('#confirm-storage-toggle-step5');
	await setToggleChecked(recoveryConfirmToggle, true);
	await takeStepScreenshot(page, 'credits-step');
	logSignupCheckpoint('Reached credits step.');

	await page.locator('.credits-package-container .buy-button').first().click();
	await takeStepScreenshot(page, 'payment-consent');
	logSignupCheckpoint('Reached payment consent step.');

	// ─── Payment consent ─────────────────────────────────────────────────────────

	const consentToggle = page.locator('#limited-refund-consent-toggle');
	await setToggleChecked(consentToggle, true);
	await takeStepScreenshot(page, 'payment-form-stripe');
	logSignupCheckpoint('Payment consent accepted — Stripe payment form visible.');

	// ─── Switch from Stripe to Polar ─────────────────────────────────────────────
	// The payment form defaults to Stripe (because the test machine is detected as EU or
	// we can't control IP). We click the "Pay with a non-EU card" switch button to
	// activate the Polar checkout overlay.
	//
	// The switch button renders as a text button under the Stripe payment form.
	// Text (EN): "Pay with a non-EU card"

	const switchToPolarButton = page.getByRole('button', { name: /pay with a non-eu card/i });
	await expect(switchToPolarButton).toBeVisible({ timeout: 15000 });
	await switchToPolarButton.click();
	await takeStepScreenshot(page, 'polar-switch-clicked');
	logSignupCheckpoint(
		'Clicked "Pay with a non-EU card" switch button — waiting for Polar overlay.'
	);

	// ─── Polar checkout overlay ───────────────────────────────────────────────────
	// After clicking the Polar pay button (or switch), PolarEmbedCheckout.create()
	// appends a full-screen fixed iframe to document.body.
	// The iframe does not have a stable title — we locate it by the polar.sh URL pattern.

	// First click the Polar "Buy" button to trigger the overlay (switch just sets the provider).
	// The Polar section renders a .polar-pay-button — wait for it and click.
	const polarBuyButton = page.locator('.polar-pay-button');
	await expect(polarBuyButton).toBeVisible({ timeout: 15000 });
	await takeStepScreenshot(page, 'polar-payment-form');
	logSignupCheckpoint('Polar payment form visible.');

	const paymentSubmittedAt = new Date().toISOString();
	await polarBuyButton.click();
	logSignupCheckpoint('Clicked Polar buy button — waiting for Polar checkout overlay.');

	// Wait for the Polar embed iframe to appear in the DOM.
	// Polar's embed appends an iframe to body; the src is a polar.sh checkout URL.
	const polarIframe = page.frameLocator('iframe[src*="polar.sh"], iframe[src*="sandbox.polar.sh"]');

	// Wait for the iframe to load by checking for a card input inside it.
	// Polar uses Stripe's payment form internally in sandbox, so the card input
	// is a standard Stripe card number field.
	const polarCardInput = polarIframe
		.locator('input[name="cardNumber"], input[autocomplete="cc-number"], [placeholder*="1234"]')
		.first();
	await expect(polarCardInput).toBeVisible({ timeout: 60000 });
	await takeStepScreenshot(page, 'polar-checkout-overlay');
	logSignupCheckpoint('Polar checkout overlay visible with card input.');

	// Fill Polar's (Stripe-backed) card form in the overlay iframe.
	await polarCardInput.fill(POLAR_SANDBOX_TEST_CARD);

	const polarExpiryInput = polarIframe
		.locator('input[name="cardExpiry"], input[autocomplete="cc-exp"], [placeholder*="MM"]')
		.first();
	await polarExpiryInput.fill('12/34');

	const polarCvcInput = polarIframe
		.locator(
			'input[name="cardCvc"], input[autocomplete="cc-csc"], [placeholder*="CVC"], [placeholder*="123"]'
		)
		.first();
	await polarCvcInput.fill('123');

	await takeStepScreenshot(page, 'polar-card-filled');
	logSignupCheckpoint('Filled Polar sandbox card details.');

	// Submit the Polar checkout form.
	// The submit button in Polar's checkout overlay should be labeled "Pay" or similar.
	const polarSubmitButton = polarIframe
		.getByRole('button', { name: /pay|subscribe|complete/i })
		.first();
	await expect(polarSubmitButton).toBeVisible({ timeout: 15000 });
	await polarSubmitButton.click();
	logSignupCheckpoint('Submitted Polar checkout form.');

	// After Polar processes the payment, the overlay fires a 'success' event and our
	// Payment.svelte transitions to the ProcessingPayment / success state.
	// Wait for "purchase successful" to appear in the main page (not inside the iframe).
	await expect(page.getByText(/purchase successful/i)).toBeVisible({ timeout: 120000 });
	await takeStepScreenshot(page, 'polar-payment-success');
	logSignupCheckpoint('Polar purchase completed successfully.');

	// ─── Post-payment flow ────────────────────────────────────────────────────────

	// For Polar, the "auto top-up" step still shows the "Finish setup" button.
	await page
		.getByRole('button', { name: /finish setup/i })
		.first()
		.click();
	await page.waitForURL(/chat/);
	await takeStepScreenshot(page, 'chat');
	logSignupCheckpoint('Arrived in chat after Polar signup.');

	await assertNoMissingTranslations(page);
	logSignupCheckpoint('No missing translations on chat page.');

	// ─── Purchase confirmation email (Polar) ──────────────────────────────────────
	// Polar purchases send a "Payment Confirmation" email (same subject as Stripe).
	// The PDF is titled "Payment Confirmation" instead of "Invoice", and includes
	// a note that Polar (polar.sh) issued the official tax invoice as MoR.

	logSignupCheckpoint('Waiting for Polar purchase confirmation email.');
	const purchaseEmail = await waitForMailosaurMessage({
		sentTo: signupEmail,
		subjectContains: 'Purchase confirmation',
		receivedAfter: paymentSubmittedAt,
		timeoutMs: 180000
	});
	logSignupCheckpoint('Received Polar purchase confirmation email.');

	const purchaseText = purchaseEmail.text?.body || '';
	// Email body says "thanks for your purchase" and mentions the attached PDF.
	expect(purchaseText).toMatch(/thanks for your purchase/i);
	// The attached PDF title is "Payment Confirmation" for Polar (not "Invoice"),
	// but the email body text still refers to the attached file as invoice/PDF.
	// We check for the refund link (deep link to in-app billing) which is always present.
	const refundLink = extractRefundLink(purchaseEmail);
	if (!refundLink) {
		const allLinks = extractMessageLinks(purchaseEmail);
		logSignupCheckpoint('Refund link missing from Polar purchase email.', {
			linkCount: allLinks.length,
			links: allLinks.slice(0, 10),
			textSnippet: purchaseText.slice(0, 300)
		});
	}
	expect(
		refundLink,
		'Expected a refund link in the Polar purchase confirmation email.'
	).toBeTruthy();
	if (!refundLink) {
		throw new Error('Refund link missing from Polar purchase confirmation email.');
	}
	expect(() => new URL(refundLink)).not.toThrow();
	logSignupCheckpoint('Validated refund link from Polar purchase email.', {
		refundLink: refundLink.slice(0, 120)
	});

	// ─── Settings: credit verification + account deletion ─────────────────────────

	const settingsMenuButton = page.locator('.profile-container[role="button"]');
	await settingsMenuButton.click();
	await expect(page.locator('.settings-menu.visible')).toBeVisible();
	await takeStepScreenshot(page, 'settings-menu-open');
	logSignupCheckpoint('Opened settings menu for credit verification.');

	const creditsAmount = page.locator('.credits-amount');
	await expect(creditsAmount).toBeVisible();
	const creditsText = (await creditsAmount.textContent()) || '';
	const creditsValue = Number.parseInt(creditsText.replace(/[^\d]/g, ''), 10);
	expect(
		creditsValue,
		'Expected purchased credits to be visible in settings after Polar payment.'
	).toBeGreaterThan(0);
	logSignupCheckpoint('Verified purchased credits in settings after Polar payment.', {
		creditsValue,
		creditsText
	});

	// Open account settings and delete the test account.
	await page.getByRole('menuitem', { name: /account/i }).click();
	await expect(page.getByRole('menuitem', { name: /delete/i })).toBeVisible();
	await page.getByRole('menuitem', { name: /delete/i }).click();
	await expect(page.locator('.delete-account-container')).toBeVisible();
	await takeStepScreenshot(page, 'delete-account');
	logSignupCheckpoint('Opened delete account settings.');

	const deleteConfirmToggle = page
		.locator('.delete-account-container input[type="checkbox"]')
		.first();
	await expect(deleteConfirmToggle).toBeAttached({ timeout: 60000 });
	await setToggleChecked(deleteConfirmToggle, true);
	await takeStepScreenshot(page, 'delete-account-confirmed');
	logSignupCheckpoint('Confirmed delete account data warning.');

	await page.locator('.delete-account-container .delete-button').click();
	const authModal = page.locator('.auth-modal');
	await expect(authModal).toBeVisible();
	await takeStepScreenshot(page, 'delete-account-auth');

	const deleteOtpInput = authModal.locator('input.tfa-input');
	await expect(deleteOtpInput).toBeVisible();
	await deleteOtpInput.fill(generateTotp(tfaSecret));
	logSignupCheckpoint('Submitted 2FA code to confirm account deletion.');

	await expect(page.locator('.delete-account-container .success-message')).toBeVisible({
		timeout: 60000
	});
	await takeStepScreenshot(page, 'delete-account-success');
	logSignupCheckpoint('Account deletion confirmed.');

	await page.waitForFunction(() => window.location.hash.includes('demo-for-everyone'), null, {
		timeout: 60000
	});
	logSignupCheckpoint('Returned to demo chat after account deletion.');
});
