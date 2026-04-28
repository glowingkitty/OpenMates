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
	getSignupTestDomain,
	buildSignupEmail,
	createEmailClient,
	checkEmailQuota,
	generateTotp,
	assertNoMissingTranslations,
	getE2EDebugUrl
} = require('./signup-flow-helpers');
const { openSignupInterface } = require('./helpers/chat-test-helpers');

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
 * - GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET / GMAIL_REFRESH_TOKEN: Gmail API credentials (preferred).
 * - MAILOSAUR_API_KEY / MAILOSAUR_SERVER_ID: Mailosaur credentials (fallback).
 */

const SIGNUP_TEST_EMAIL_DOMAINS = process.env.SIGNUP_TEST_EMAIL_DOMAINS;
// Generic US Visa — works in Stripe Managed Payments (non-EU Embedded Checkout).
const STRIPE_TEST_CARD_NUMBER = '4242424242424242';

test('completes full signup flow: email + 2FA + Managed Payments (Stripe Embedded Checkout)', async ({
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
	// Allow extra time for Mailosaur email delivery + purchase confirmation + account deletion.
	// This is the longest signup spec: full 2FA setup, payment, email verification of purchase,
	// refund link validation, and account deletion with 2FA auth. 600s needed for retries.
	test.setTimeout(600000);

	const logSignupCheckpoint = createSignupLogger('SIGNUP_FLOW_MANAGED');
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
	const githubLink = page.locator('a[href*="github.com"]');
	const instagramLink = page.locator('a[href*="instagram.com"]');
	await expect(githubLink.first()).toBeVisible();
	await expect(instagramLink.first()).toBeVisible();

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
	await confirmEmailInput.fill(emailCode);

	// Secure account step: choose password-based setup.
	const passwordOption = page.locator('#signup-password-option');
	await expect(passwordOption).toBeVisible({ timeout: 10000 });
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
	await takeStepScreenshot(page, 'one-time-codes');
	logSignupCheckpoint('Reached one-time codes step.');

	// One-time codes step: show QR, copy secret, validate selectable secret input.
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

	const tfaContinueButton = page.locator('#signup-2fa-reminder-continue');
	await tfaContinueButton.click();
	await takeStepScreenshot(page, 'backup-codes');
	logSignupCheckpoint('Reached backup codes step.');

	// Backup codes step: download and confirm stored.
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

	// Recovery key step: download, copy, print, and confirm stored.
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

	const recoveryConfirmToggle = page.locator('#confirm-storage-toggle-step5');
	await setToggleChecked(recoveryConfirmToggle, true);
	await takeStepScreenshot(page, 'credits-step');
	logSignupCheckpoint('Reached credits step.');

	// Credits step: exercise gift card path (cancel) and navigation buttons.
	const giftCardButton = page.locator('#signup-credits-gift-card');
	await giftCardButton.scrollIntoViewIfNeeded();
	await giftCardButton.click();
	await takeStepScreenshot(page, 'credits-giftcard');
	await page.locator('#signup-gift-card-cancel').click();
	await takeStepScreenshot(page, 'credits-ready');
	logSignupCheckpoint('Completed credits step actions.');

	const moreButton = page.locator('#signup-credits-more');
	const lessButton = page.locator('#signup-credits-less');
	if (await moreButton.isVisible()) {
		await moreButton.click();
	}
	if (await lessButton.isVisible()) {
		await lessButton.click();
	}

	// Purchase credits to proceed to payment step.
	await page.getByTestId('credits-package').getByTestId('buy-button').first().click();
	await takeStepScreenshot(page, 'payment-consent');
	logSignupCheckpoint('Reached payment consent step.');

	// Payment step: consent to limited refund to reveal payment form.
	// The consent overlay must be dismissed BEFORE switching providers, because
	// it covers the payment area with pointer-events:all.
	const consentToggle = page.locator('#limited-refund-consent-toggle');
	await setToggleChecked(consentToggle, true);
	logSignupCheckpoint('Payment consent accepted.');

	// GHA runners are in the US → Stripe Managed Payments (Embedded Checkout) is auto-selected.
	// This test stays on Managed Payments — do NOT click 'switch-to-stripe'.

	// Wait for Stripe Embedded Checkout iframe inside #checkout.
	await page.waitForSelector('#checkout iframe', { state: 'attached', timeout: 30000 });
	logSignupCheckpoint('Stripe Embedded Checkout iframe loaded.');
	await page.waitForTimeout(3000); // allow Checkout UI to fully render
	await takeStepScreenshot(page, 'payment-form');

	const checkoutFrame = page.frameLocator('#checkout iframe');

	// Dismiss Stripe Link (phone prompt) if shown; switch to Card tab.
	const linkPhone = checkoutFrame.getByPlaceholder(/phone/i);
	if (await linkPhone.isVisible({ timeout: 5000 }).catch(() => false)) {
		const payWithCard = checkoutFrame.getByRole('button', { name: /pay with card/i });
		if (await payWithCard.isVisible({ timeout: 3000 }).catch(() => false)) {
			await payWithCard.click();
		} else {
			const cardTab = checkoutFrame.getByRole('radio', { name: /card/i });
			if (await cardTab.isVisible({ timeout: 3000 }).catch(() => false)) await cardTab.click();
		}
		await page.waitForTimeout(1500);
	}
	const cardTab = checkoutFrame.getByRole('radio', { name: /card/i });
	if (await cardTab.isVisible({ timeout: 5000 }).catch(() => false)) {
		await cardTab.click();
		await page.waitForTimeout(1000);
	}

	// Fill card in Embedded Checkout
	const cardInput = checkoutFrame.locator(
		'input[autocomplete="cc-number"], input[name="number"], input[name="cardNumber"]'
	).first();
	await cardInput.waitFor({ state: 'visible', timeout: 20000 });
	await cardInput.click();
	await cardInput.pressSequentially(STRIPE_TEST_CARD_NUMBER, { delay: 30 });
	const expiryInput = checkoutFrame.locator(
		'input[autocomplete="cc-exp"], input[name="expiry"], input[name="cardExpiry"]'
	).first();
	await expiryInput.click();
	await expiryInput.pressSequentially('1234', { delay: 30 });
	const cvcInput = checkoutFrame.locator(
		'input[autocomplete="cc-csc"], input[name="cvc"], input[name="cardCvc"]'
	).first();
	await cvcInput.click();
	await cvcInput.pressSequentially('123', { delay: 30 });
	const nameInput = checkoutFrame.getByPlaceholder(/full name on card/i);
	if (await nameInput.isVisible({ timeout: 3000 }).catch(() => false)) {
		await nameInput.click();
		await nameInput.pressSequentially('Test User', { delay: 30 });
	}
	const addrInput = checkoutFrame.getByPlaceholder(/^address$/i);
	if (await addrInput.isVisible({ timeout: 3000 }).catch(() => false)) {
		await addrInput.click();
		await addrInput.pressSequentially('123 Test St', { delay: 30 });
		await page.keyboard.press('Escape');
		await page.waitForTimeout(500);
	}
	logSignupCheckpoint('Filled card in Stripe Embedded Checkout.');
	await takeStepScreenshot(page, 'payment-form-filled');

	// Submit payment
	const payBtn = checkoutFrame.locator('button[type="submit"], button:has-text("Pay"), button:has-text("Subscribe")').first();
	await expect(payBtn).toBeVisible({ timeout: 10000 });
	await expect(payBtn).toBeEnabled({ timeout: 10000 });
	const paymentSubmittedAt = new Date().toISOString();
	await payBtn.click();
	logSignupCheckpoint('Clicked Pay in Stripe Embedded Checkout.');

	// Stripe Link interstitial — uncheck save info, fill ZIP, wait, click Pay
	await page.waitForTimeout(3000);
	const linkSave = checkoutFrame.getByText(/save my payment information/i);
	if (await linkSave.isVisible({ timeout: 3000 }).catch(() => false)) {
		const checkbox = checkoutFrame.locator('input[type="checkbox"]').first();
		if (await checkbox.isChecked({ timeout: 2000 }).catch(() => false)) await checkbox.uncheck();
		const cityField = checkoutFrame.getByPlaceholder(/^city$/i);
		if (await cityField.isVisible({ timeout: 2000 }).catch(() => false)) await cityField.fill('New York');
		const zipField = checkoutFrame.getByPlaceholder(/^zip$/i);
		if (await zipField.isVisible({ timeout: 2000 }).catch(() => false)) await zipField.fill('10001');
		await page.waitForTimeout(5000);
		try {
			await checkoutFrame.locator('button[type="submit"], button:has-text("Pay")').first().click({ timeout: 8000 });
		} catch {
			await checkoutFrame.locator('button[type="submit"], button:has-text("Pay")').first().click({ force: true, timeout: 5000 });
		}
		logSignupCheckpoint('Handled Stripe Link interstitial.');
	}

	await expect(page.getByText(/purchase successful/i)).toBeVisible({ timeout: 120000 });
	await takeStepScreenshot(page, 'payment-success');
	logSignupCheckpoint('Purchase completed successfully.');

	// Auto top-up step: finish setup and confirm redirect into the app.
	await page.getByTestId('signup-finish-setup').first().click();
	await page.waitForURL(/chat/);
	await takeStepScreenshot(page, 'chat');
	logSignupCheckpoint('Arrived in chat after signup.');

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
	expect(purchaseText).toMatch(/invoice|confirmation/i);

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
	const settingsMenuButton = page.getByTestId('profile-container');
	await settingsMenuButton.click();
	await expect(page.locator('[data-testid="settings-menu"].visible')).toBeVisible();
	await takeStepScreenshot(page, 'settings-menu-open');
	logSignupCheckpoint('Opened settings menu for credit verification.');

	// Confirm credits reflect the purchase (should be non-zero after payment).
	const creditsAmount = page.getByTestId('credits-amount');
	await expect(creditsAmount).toBeVisible({ timeout: 10000 });
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

	// Start deletion and complete 2FA authentication.
	await page.getByTestId('delete-account-container').getByTestId('delete-button').click();
	const authModal = page.getByTestId('auth-modal');
	await expect(authModal).toBeVisible();
	await takeStepScreenshot(page, 'delete-account-auth');

	const deleteOtpInput = authModal.getByTestId('tfa-input');
	await expect(deleteOtpInput).toBeVisible({ timeout: 10000 });
	await deleteOtpInput.fill(generateTotp(tfaSecret));
	logSignupCheckpoint('Submitted 2FA code to confirm account deletion.');

	await expect(page.getByTestId('delete-account-container').getByTestId('success-message')).toBeVisible({
		timeout: 10000
	});
	await takeStepScreenshot(page, 'delete-account-success');
	logSignupCheckpoint('Account deletion confirmed.');

	// Confirm logout redirect to demo chat after deletion.
	await page.waitForFunction(() => window.location.hash.includes('demo-for-everyone'), null, {
		timeout: 10000
	});
	logSignupCheckpoint('Returned to demo chat after account deletion.');

	// Privacy promise check: after a full signup + purchase + deletion flow,
	// no third-party tracking cookies must exist. Enforces
	// shared/docs/privacy_promises.yml → no-third-party-tracking.
	await assertNoThirdPartyCookies(context);
	logSignupCheckpoint('No third-party cookies observed.');
});
