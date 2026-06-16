/* eslint-disable @typescript-eslint/no-require-imports */
// @privacy-promise: no-third-party-tracking
export {};
// NOTE:
// This file is executed inside the official Playwright Docker image, which
// provides the @playwright/test module at runtime. To keep repo-wide TypeScript
// checks happy without requiring local Playwright installation, we use CommonJS
// require() and broad lint disables limited to this spec file.
const { test, expect, assertNoThirdPartyCookies } = require('./helpers/cookie-audit');
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
	buildSignupEmail,
	createEmailClient,
	checkEmailQuota,
	assertNoMissingTranslations,
	getE2EDebugUrl
} = require('./signup-flow-helpers');
const { openSignupInterface } = require('./helpers/chat-test-helpers');

/**
 * Signup + Settings billing purchase flow against a deployed web app.
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
 * - GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET / GMAIL_REFRESH_TOKEN: Gmail API credentials (preferred).
 * - MAILOSAUR_API_KEY / MAILOSAUR_SERVER_ID: Mailosaur credentials (fallback).
 */

const SIGNUP_TEST_EMAIL_DOMAINS = process.env.SIGNUP_TEST_EMAIL_DOMAINS;
// Netherlands EU card — required to pass the Radar "block non-EU cards" rule on the EU Stripe path.
const STRIPE_TEST_CARD_NUMBER = '4000002760000016';

test('completes signup and EU card purchase from Settings billing', async ({
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

	// Listen for network responses (log body for auth endpoints to debug failures)
	page.on('response', async (response: any) => {
		const timestamp = new Date().toISOString();
		const url: string = response.url();
		networkActivities.push(`[${timestamp}] << ${response.status()} ${url}`);
		if (url.includes('/auth/') && response.status() < 500) {
			try {
				const body = await response.text();
				networkActivities.push(`[${timestamp}]    body: ${body.slice(0, 300)}`);
			} catch {
				// ignore body read errors
			}
		}
	});

	test.slow();
	// Allow extra time for Mailosaur email delivery, purchase confirmation, and account deletion.
	// This is a long spec: signup, Settings billing payment, refund link validation, and deletion.
	test.setTimeout(600000);

	const logSignupCheckpoint = createSignupLogger('SIGNUP_FLOW_STRIPE_EU');
	const takeStepScreenshot = createStepScreenshotter(logSignupCheckpoint);

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
	const { waitForMailosaurMessage, extractSixDigitCode, extractRefundLink, extractMessageLinks } =
		emailClient!;

	// Grant clipboard permissions so "Copy" actions can be exercised reliably.
	await context.grantPermissions(['clipboard-read', 'clipboard-write']);

	const signupEmail = buildSignupEmail(signupDomain);
	const emailLocal = signupEmail.split('@')[0];
	const signupUsername = emailLocal.includes('+') ? emailLocal.split('+')[1] : emailLocal;
	const signupPassword = 'SignupTest!234';
	logSignupCheckpoint('Initialized signup identity.', { signupEmail });

	// Base URL comes from PLAYWRIGHT_TEST_BASE_URL or the default in config.
	await page.goto(getE2EDebugUrl('/'));
	await takeStepScreenshot(page, 'home');

	// Open the login/signup dialog from the header.
	await openSignupInterface(page);
	await takeStepScreenshot(page, 'login-dialog');
	logSignupCheckpoint('Opened login dialog.');

	// Verify no missing translations on the login dialog (catches [object Object] or [T:key] issues).
	await assertNoMissingTranslations(page);
	logSignupCheckpoint('No missing translations on login dialog.');

	// Switch to the signup tab inside the login dialog.
	const loginTabs = page.getByTestId('login-tabs');
	await expect(loginTabs).toBeVisible();
	await loginTabs.getByRole('button', { name: /sign up/i }).click();
	await takeStepScreenshot(page, 'signup-alpha');

	// Verify no missing translations on the signup alpha disclaimer step.
	await assertNoMissingTranslations(page);
	logSignupCheckpoint('No missing translations on signup alpha step.');

	// Alpha disclaimer: verify outbound links exist and continue.
	// Use href-based locators because link accessible names can vary by locale.
	const githubLink = page.getByTestId('signup-alpha-github-link');
	const instagramLink = page.getByTestId('signup-alpha-instagram-link');
	await expect(githubLink).toBeVisible();
	await expect(instagramLink).toBeVisible();

	await page.getByRole('button', { name: /continue/i }).click();
	await takeStepScreenshot(page, 'basics-step');
	// Verify no missing translations on the basics step (back button, form labels, etc.).
	await assertNoMissingTranslations(page);
	logSignupCheckpoint('Reached basics step.');

	// Basics step: fill email/username and exercise key toggles.
	const emailInput = page.locator('input[type="email"][autocomplete="email"]');
	const usernameInput = page.locator('input[autocomplete="username"]');
	await expect(emailInput).toBeVisible({ timeout: 10000 });
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
	logSignupCheckpoint('Submitted signup basics, waiting for email confirmation.');

	// Confirm email step: wait for step transition and verify "Open mail app" link.
	// The step transition may take a moment, so we wait for the link to appear with a longer timeout.
	const openMailLink = page.getByRole('link', { name: /open mail app/i });
	await expect(openMailLink).toBeVisible({ timeout: 10000 });
	await takeStepScreenshot(page, 'confirm-email');
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
	await expect(confirmEmailInput).toBeVisible({ timeout: 10000 });
	await confirmEmailInput.click();
	await confirmEmailInput.pressSequentially(emailCode);

	// Secure account step: choose password-based setup.
	const passwordOption = page.locator('#signup-password-option');
	await expect(passwordOption).toBeVisible({ timeout: 30000 });
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

	await page.locator('#signup-password-continue').click();
	await page.waitForURL(/chat/);
	await takeStepScreenshot(page, 'chat');
	logSignupCheckpoint('Arrived in chat after signup.');

	// Billing moved out of signup. Purchase credits from Settings > Billing > Buy Credits.
	const settingsMenuButtonForPurchase = page.locator('#settings-menu-toggle');
	await expect(settingsMenuButtonForPurchase).toBeVisible({ timeout: 10000 });
	await settingsMenuButtonForPurchase.click();
	await expect(page.locator('[data-testid="settings-menu"].visible')).toBeVisible({ timeout: 10000 });
	await page.getByRole('menuitem', { name: /billing/i }).click();
	await page.getByRole('menuitem', { name: /buy credits/i }).click();
	await page.locator('[data-testid="settings-menu"].visible [data-testid="menu-item"][role="menuitem"]').first().click();
	await takeStepScreenshot(page, 'payment-consent');
	logSignupCheckpoint('Reached payment consent step.');

	// First purchase from Settings must collect the limited refund consent.
	const consentToggle = page.locator('#limited-refund-consent-toggle');
	await expect(page.getByText(/Limited refund/i)).toBeVisible({ timeout: 10000 });
	await setToggleChecked(consentToggle, true);
	logSignupCheckpoint('Payment consent accepted.');

	// GHA runners are in the US, so Stripe Managed Payments is auto-selected (non-EU IP).
	// Switch to EU Stripe for this test — it specifically tests the EU card payment flow.
	const switchToStripeBtn = page.getByTestId('switch-to-stripe');
	if (await switchToStripeBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
		await switchToStripeBtn.click();
		logSignupCheckpoint('Switched from Managed Payments to EU Stripe payment provider.');
	}

	// Wait for Stripe Payment Element iframe to load after provider switch.
	// switchPaymentMode() destroys any existing checkout, fetches config, loads Stripe.js,
	// creates a PaymentIntent, and mounts the Payment Element — all async. The iframe
	// won't exist until that chain completes.
	const stripeIframe = page.frameLocator('iframe[title="Secure payment input frame"]');
	const cardInput = stripeIframe
		.locator('input[name="number"], input[name="cardNumber"], input[autocomplete="cc-number"]')
		.first();
	await cardInput.waitFor({ state: 'visible', timeout: 30000 });
	logSignupCheckpoint('Stripe Payment Element loaded.');

	await takeStepScreenshot(page, 'payment-form');

	// Fill Stripe payment element with the test card.
	await fillStripeCardDetails(page, STRIPE_TEST_CARD_NUMBER);
	logSignupCheckpoint('Filled Stripe card details.');

	// Wait for Stripe to validate the card (isPaymentElementComplete → buy button enabled).
	const buyButton = page.getByTestId('payment-form').getByTestId('buy-button');
	await expect(buyButton).toBeEnabled({ timeout: 10000 });

	// Submit payment and wait for success.
	const paymentSubmittedAt = new Date().toISOString();
	await buyButton.click();
	await expect(page.getByRole('heading', { name: /purchase successful/i })).toBeVisible({ timeout: 60000 });
	await takeStepScreenshot(page, 'payment-success');
	logSignupCheckpoint('Purchase completed successfully.');

	// Verify no missing translations on the main chat page after signup
	await assertNoMissingTranslations(page);
	logSignupCheckpoint('No missing translations detected.');

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

	await page.getByRole('button', { name: /done/i }).click();
	await page.getByTestId('icon-button-close').click();
	await expect(page.getByTestId('profile-container')).toBeVisible({ timeout: 10000 });

	// Open settings to verify credit balance and delete the test account.
	const settingsMenuButton = page.getByTestId('profile-container');
	if (!(await page.locator('[data-testid="settings-menu"].visible').isVisible({ timeout: 2000 }).catch(() => false))) {
		await settingsMenuButton.click();
	}
	await expect(page.locator('[data-testid="settings-menu"].visible')).toBeVisible();
	await takeStepScreenshot(page, 'settings-menu-open');
	logSignupCheckpoint('Opened settings menu for credit verification.');

	// Confirm credits reflect the purchase (should be non-zero after payment).
	const creditsAmount = page.getByTestId('credits-amount');
	await expect(creditsAmount).toBeVisible({ timeout: 10000 });
	await page.waitForFunction(() => {
		const creditsElement = document.querySelector('[data-testid="credits-amount"]');
		const creditsText = creditsElement?.textContent || '';
		return Number.parseInt(creditsText.replace(/[^\d]/g, ''), 10) > 0;
	}, null, { timeout: 30000 });
	const creditsText = (await creditsAmount.textContent()) || '';
	const creditsValue = Number.parseInt(creditsText.replace(/[^\d]/g, ''), 10);
	expect(creditsValue, 'Expected purchased credits to be visible in settings.').toBeGreaterThan(0);
	logSignupCheckpoint('Verified purchased credits in settings.', { creditsValue, creditsText });

	// Navigate to Account settings and open delete account flow.
	await page.getByRole('menuitem', { name: /account/i }).click();
	await expect(page.getByRole('menuitem', { name: /delete/i })).toBeVisible();
	await page.getByRole('menuitem', { name: /delete/i }).click();
	await expect(page.getByTestId('delete-account-container')).toBeVisible();
	await takeStepScreenshot(page, 'delete-account');
	logSignupCheckpoint('Opened delete account settings.');

	// Confirm data deletion checkbox to enable deletion.
	// Use the delete account toggle directly because the label text is lengthy and localized.
	const deleteConfirmToggle = page
		.getByTestId('delete-account-container').locator('input[type="checkbox"]')
		.first();
	await expect(deleteConfirmToggle).toBeAttached({ timeout: 10000 });
	await setToggleChecked(deleteConfirmToggle, true);
	await takeStepScreenshot(page, 'delete-account-confirmed');
	logSignupCheckpoint('Confirmed delete account data warning.');

	// Password-only users get email OTP verification for account deletion.
	await page.getByTestId('delete-account-container').getByTestId('delete-button').click();
	const authModal = page.getByTestId('auth-modal');
	await expect(authModal).toBeVisible();
	await takeStepScreenshot(page, 'delete-account-auth');

	const emailOtpSection = authModal.getByTestId('auth-email-otp');
	await expect(emailOtpSection).toBeVisible({ timeout: 10000 });
	const sendCodeButton = emailOtpSection.getByTestId('auth-btn');
	const deleteEmailRequestedAt = new Date().toISOString();
	await sendCodeButton.click();
	logSignupCheckpoint('Clicked send verification code for account deletion.');

	const deleteOtpInput = emailOtpSection.locator('input[inputmode="numeric"]');
	await expect(deleteOtpInput).toBeVisible({ timeout: 10000 });

	const deleteVerificationMessage = await waitForMailosaurMessage({
		sentTo: signupEmail,
		receivedAfter: deleteEmailRequestedAt
	});
	const deleteVerificationCode = extractSixDigitCode(deleteVerificationMessage);
	expect(deleteVerificationCode, 'Expected a 6-digit action verification code for deletion.').toBeTruthy();
	await deleteOtpInput.fill(deleteVerificationCode);
	logSignupCheckpoint('Entered action verification code to confirm deletion.');

	// Confirm logout redirect to demo chat after deletion. The deletion flow can
	// clear authenticated UI before the transient in-settings success message is visible.
	await page.waitForFunction(() => window.location.hash.includes('demo-for-everyone'), null, {
		timeout: 30000
	});
	await takeStepScreenshot(page, 'delete-account-success');
	logSignupCheckpoint('Account deletion confirmed.');
	logSignupCheckpoint('Returned to demo chat after account deletion.');

	// Privacy promise check: after a full signup + purchase + deletion flow,
	// no third-party tracking cookies must exist. Enforces
	// shared/docs/privacy_promises.yml → no-third-party-tracking.
	await assertNoThirdPartyCookies(context);
	logSignupCheckpoint('No third-party cookies observed.');
});
