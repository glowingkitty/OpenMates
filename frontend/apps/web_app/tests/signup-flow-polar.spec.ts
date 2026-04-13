/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};
// NOTE:
// This file is executed inside the official Playwright Docker image, which
// provides the @playwright/test module at runtime. To keep repo-wide TypeScript
// checks happy without requiring local Playwright installation, we use CommonJS
// require() and broad lint disables limited to this spec file.
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
	generateTotp,
	assertNoMissingTranslations,
	getE2EDebugUrl
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
 * - GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET / GMAIL_REFRESH_TOKEN: Gmail API credentials (preferred).
 * - MAILOSAUR_API_KEY / MAILOSAUR_SERVER_ID: Mailosaur credentials (fallback).
 * - PLAYWRIGHT_TEST_BASE_URL: Base URL of the deployed dev web app.
 *
 * POLAR VAULT PREREQUISITE:
 * - Polar secrets must be configured in Vault at kv/data/providers/polar:
 *     production_access_token, sandbox_access_token,
 *     production_webhook_secret, sandbox_webhook_secret
 * - Without these, ?provider_override=polar falls back to 'stripe' and this test skips.
 */

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
	// GHA runners are slower — 300s was insufficient; 480s provides comfortable margin.
	test.setTimeout(480000);

	const logSignupCheckpoint = createSignupLogger('POLAR_SIGNUP_FLOW');
	const takeStepScreenshot = createStepScreenshotter(logSignupCheckpoint, {
		filenamePrefix: 'polar'
	});

	await archiveExistingScreenshots(logSignupCheckpoint);

	// ─── Skip guards ─────────────────────────────────────────────────────────────

	const signupDomain = getSignupTestDomain(SIGNUP_TEST_EMAIL_DOMAINS);
	test.skip(!signupDomain, 'SIGNUP_TEST_EMAIL_DOMAINS must include a test domain.');

	const emailClient = createEmailClient();
	test.skip(!emailClient, 'Email credentials required (GMAIL_* or MAILOSAUR_*).');

	const quota = await checkEmailQuota();
	test.skip(!quota.available, `Email quota reached (${quota.current}/${quota.limit}).`);

	if (!signupDomain) {
		throw new Error('Missing signup test domain after skip guard.');
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
		emailClient!;

	// Grant clipboard permissions so "Copy" actions can be exercised reliably.
	await context.grantPermissions(['clipboard-read', 'clipboard-write']);

	const signupEmail = buildSignupEmail(signupDomain);
	const emailLocal = signupEmail.split('@')[0];
	const signupUsername = emailLocal.includes('+') ? emailLocal.split('+')[1] : emailLocal;
	const signupPassword = 'PolarTest!234';
	logSignupCheckpoint('Initialized Polar signup identity.', { signupEmail });

	// ─── Navigation & signup basics ──────────────────────────────────────────────

	await page.goto(getE2EDebugUrl('/'));
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

	const loginTabs = page.getByTestId('login-tabs');
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
	await expect(emailInput).toBeVisible({ timeout: 10000 });
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
	await expect(openMailLink).toBeVisible({ timeout: 10000 });
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

	const passwordOption = page.locator('#signup-password-option');
	await expect(passwordOption).toBeVisible({ timeout: 10000 });
	await takeStepScreenshot(page, 'secure-account');
	await passwordOption.click();
	await takeStepScreenshot(page, 'password-step');

	const passwordInputs = page.locator('input[autocomplete="new-password"]');
	await expect(passwordInputs).toHaveCount(2);
	await passwordInputs.nth(0).fill(signupPassword);
	await passwordInputs.nth(1).fill(signupPassword);
	await takeStepScreenshot(page, 'password-filled');
	logSignupCheckpoint('Password fields completed.');

	await page.locator('#signup-password-continue').click();
	await takeStepScreenshot(page, 'one-time-codes');
	logSignupCheckpoint('Reached one-time codes step.');

	// ─── 2FA setup ────────────────────────────────────────────────────────────────

	const qrButton = page.locator('#signup-2fa-scan-qr');
	await qrButton.click();
	await expect(page.getByTestId('qr-code')).toBeVisible();
	await takeStepScreenshot(page, 'one-time-codes-qr');
	await qrButton.click();
	await expect(page.getByTestId('qr-code')).toBeHidden();

	const copySecretButton = page.locator('#signup-2fa-copy-secret');
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

	const tfaContinueButton = page.locator('#signup-2fa-reminder-continue');
	await tfaContinueButton.click();
	await takeStepScreenshot(page, 'backup-codes');
	logSignupCheckpoint('Reached backup codes step.');

	// ─── Backup codes + recovery key ─────────────────────────────────────────────

	const backupDownloadButton = page.locator('#signup-backup-codes-download');
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

	const recoveryDownloadButton = page.locator('#signup-recovery-key-download');
	const [recoveryDownload] = await Promise.all([
		page.waitForEvent('download'),
		recoveryDownloadButton.click()
	]);
	await takeStepScreenshot(page, 'recovery-key');
	expect(await recoveryDownload.suggestedFilename()).toMatch(/recovery/i);
	logSignupCheckpoint('Downloaded recovery key.');

	const recoveryCopyButton = page.locator('#signup-recovery-key-copy');
	await recoveryCopyButton.click();

	const [printPage] = await Promise.all([
		context.waitForEvent('page'),
		page.locator('#signup-recovery-key-print').click()
	]);
	await printPage.close();
	await takeStepScreenshot(page, 'recovery-key-actions');
	logSignupCheckpoint('Completed recovery key actions.');

	// ─── Credits step ─────────────────────────────────────────────────────────────

	const recoveryConfirmToggle = page.locator('#confirm-storage-toggle-step5');
	await setToggleChecked(recoveryConfirmToggle, true);
	await takeStepScreenshot(page, 'credits-step');
	logSignupCheckpoint('Reached credits step.');

	await page.getByTestId('credits-package').getByTestId('buy-button').first().click();
	await takeStepScreenshot(page, 'payment-consent');
	logSignupCheckpoint('Reached payment consent step.');

	// ─── Payment consent ─────────────────────────────────────────────────────────
	// The consent overlay appears regardless of whether the initial provider is Stripe or Polar.

	const consentToggle = page.locator('#limited-refund-consent-toggle');
	await expect(consentToggle).toBeAttached({ timeout: 10000 });
	await setToggleChecked(consentToggle, true);
	await takeStepScreenshot(page, 'payment-consent-accepted');
	logSignupCheckpoint('Payment consent accepted.');

	// ─── Ensure Polar is the active provider ─────────────────────────────────────
	// The initial provider depends on geo-detection (EU IP → Stripe, non-EU → Polar).
	// If we landed on Stripe, switch to Polar. If already on Polar, proceed directly.

	const switchToPolarButton = page.getByRole('button', { name: /pay with a non-eu card/i });
	const alreadyOnPolar = !(await switchToPolarButton.isVisible({ timeout: 5000 }).catch(() => false));

	if (!alreadyOnPolar) {
		await switchToPolarButton.click();
		await takeStepScreenshot(page, 'polar-switch-clicked');
		logSignupCheckpoint('Switched from Stripe to Polar.');
	} else {
		logSignupCheckpoint('Already on Polar provider (non-EU IP detected).');
	}

	// ─── Polar checkout ──────────────────────────────────────────────────────────
	// Polar renders an inline iframe for checkout. If auto-trigger succeeded, the iframe
	// is already visible. If not, a retry "Buy" button is shown — click it to trigger.

	const polarIframeLocator = page.locator('iframe[src*="polar.sh"], iframe[src*="sandbox.polar.sh"]');
	const polarBuyButton = page.getByTestId('polar-pay-button');

	// Wait for either the iframe or the retry button to appear
	await expect(polarIframeLocator.or(polarBuyButton)).toBeVisible({ timeout: 30000 });

	// If the retry button is visible (auto-trigger failed), click it to start checkout
	if (await polarBuyButton.isVisible()) {
		await takeStepScreenshot(page, 'polar-payment-form');
		logSignupCheckpoint('Polar payment form visible (retry button).');
		await polarBuyButton.click();
		logSignupCheckpoint('Clicked Polar buy button.');
	} else {
		logSignupCheckpoint('Polar checkout auto-triggered — iframe already loading.');
	}

	const paymentSubmittedAt = new Date().toISOString();

	// Wait for the Polar embed iframe to appear in the DOM.
	// Polar renders an inline iframe with the checkout form; the src is a polar.sh URL.
	const polarIframe = page.frameLocator('iframe[src*="polar.sh"], iframe[src*="sandbox.polar.sh"]');

	// Wait for the Polar iframe to load by checking for a visible element inside it.
	// Polar's checkout page renders a submit button — use that as the load indicator.
	await expect(polarIframe.getByRole('button', { name: /pay|subscribe|complete/i }).first())
		.toBeVisible({ timeout: 30000 });
	await takeStepScreenshot(page, 'polar-checkout-overlay');
	logSignupCheckpoint('Polar checkout overlay visible.');

	// Polar uses Stripe Payment Element internally, which renders card inputs inside
	// a NESTED iframe within the Polar checkout iframe. We need two levels of frameLocator:
	//   page → iframe[src*="polar.sh"] → iframe (Stripe Payment Element) → inputs
	const stripeFrame = polarIframe.frameLocator('iframe').first();

	// Stripe Payment Element uses input[name="number"] for card number.
	const polarCardInput = stripeFrame
		.locator('input[name="number"], input[autocomplete="cc-number"], input[id="Field-numberInput"]')
		.first();
	await expect(polarCardInput).toBeVisible({ timeout: 30000 });
	logSignupCheckpoint('Stripe Payment Element card input visible inside Polar checkout.');

	// Fill card details inside the nested Stripe iframe.
	await polarCardInput.fill(POLAR_SANDBOX_TEST_CARD);

	const polarExpiryInput = stripeFrame
		.locator('input[name="expiry"], input[autocomplete="cc-exp"], input[id="Field-expiryInput"]')
		.first();
	await polarExpiryInput.fill('12/34');

	const polarCvcInput = stripeFrame
		.locator('input[name="cvc"], input[autocomplete="cc-csc"], input[id="Field-cvcInput"]')
		.first();
	await polarCvcInput.fill('123');

	// Polar's checkout requires cardholder name and billing country.
	// These fields are in the Polar iframe directly (not the nested Stripe iframe).
	const cardholderNameInput = polarIframe.locator('input[name="customer_name"]');
	await expect(cardholderNameInput).toBeVisible({ timeout: 10000 });
	await cardholderNameInput.fill('Test User');

	const billingCountrySelect = polarIframe.locator('select[autocomplete="billing country"]');
	await expect(billingCountrySelect).toBeVisible({ timeout: 10000 });
	await billingCountrySelect.selectOption('US');
	logSignupCheckpoint('Filled cardholder name and billing country.');

	await takeStepScreenshot(page, 'polar-card-filled');
	logSignupCheckpoint('Filled Polar sandbox card details.');

	// Submit the Polar checkout form.
	// The submit button is in the Polar iframe (not inside the Stripe iframe).
	const polarSubmitButton = polarIframe
		.getByRole('button', { name: /pay|subscribe|complete/i })
		.first();
	await expect(polarSubmitButton).toBeVisible({ timeout: 30000 });
	await polarSubmitButton.click();
	logSignupCheckpoint('Submitted Polar checkout form.');

	// After Polar processes the payment, the overlay fires a 'success' event and our
	// Payment.svelte transitions to the ProcessingPayment / success state.
	// Wait for "purchase successful" to appear in the main page (not inside the iframe).
	await expect(page.getByText(/purchase successful/i)).toBeVisible({ timeout: 60000 });
	await takeStepScreenshot(page, 'polar-payment-success');
	logSignupCheckpoint('Polar purchase completed successfully.');

	// ─── Post-payment flow ────────────────────────────────────────────────────────

	// For Polar, the "auto top-up" step still shows the "Finish setup" button.
	await page.locator('#signup-finish-setup').click();
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

	const settingsMenuButton = page.getByTestId('profile-container');
	await settingsMenuButton.click();
	await expect(page.locator('[data-testid="settings-menu"].visible')).toBeVisible();
	await takeStepScreenshot(page, 'settings-menu-open');
	logSignupCheckpoint('Opened settings menu for credit verification.');

	const creditsAmount = page.getByTestId('credits-amount');
	await expect(creditsAmount).toBeVisible({ timeout: 10000 });
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
	await expect(page.getByTestId('delete-account-container')).toBeVisible();
	await takeStepScreenshot(page, 'delete-account');
	logSignupCheckpoint('Opened delete account settings.');

	const deleteConfirmToggle = page
		.getByTestId('delete-account-container').locator('input[type="checkbox"]')
		.first();
	await expect(deleteConfirmToggle).toBeAttached({ timeout: 10000 });
	await setToggleChecked(deleteConfirmToggle, true);
	await takeStepScreenshot(page, 'delete-account-confirmed');
	logSignupCheckpoint('Confirmed delete account data warning.');

	await page.getByTestId('delete-account-container').getByTestId('delete-button').click();
	const authModal = page.getByTestId('auth-modal');
	await expect(authModal).toBeVisible();
	await takeStepScreenshot(page, 'delete-account-auth');

	const deleteOtpInput = authModal.locator('input.tfa-input');
	await expect(deleteOtpInput).toBeVisible();
	await deleteOtpInput.fill(generateTotp(tfaSecret));
	logSignupCheckpoint('Submitted 2FA code to confirm account deletion.');

	await expect(page.getByTestId('delete-account-container').getByTestId('success-message')).toBeVisible({
		timeout: 10000
	});
	await takeStepScreenshot(page, 'delete-account-success');
	logSignupCheckpoint('Account deletion confirmed.');

	await page.waitForFunction(() => window.location.hash.includes('demo-for-everyone'), null, {
		timeout: 10000
	});
	logSignupCheckpoint('Returned to demo chat after account deletion.');
});
