/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};
// =============================================================================
// Create Test Account
//
// Signs up a new account (email + password + 2FA + credit purchase) and writes
// the credentials to artifacts/account-credentials.json.  Does NOT delete the
// account afterward — it is meant to stay around for parallel test workers.
//
// Usage (from project root):
//   docker compose --env-file .env -f docker-compose.playwright.yml run --rm \
//     -e SIGNUP_TEST_EMAIL_DOMAINS \
//     -e MAILOSAUR_API_KEY \
//     -e PLAYWRIGHT_TEST_FILE="create-test-account.spec.ts" \
//     playwright
//
// After the run, read artifacts/account-credentials.json for:
//   { email, password, otpKey }
// =============================================================================
const fs = require('fs');
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
		consoleLogs.slice(-20).forEach((log: string) => console.log(log));
		console.log('\n[RECENT NETWORK ACTIVITIES]');
		networkActivities.slice(-20).forEach((a: string) => console.log(a));
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
	generateTotp,
	assertNoMissingTranslations
} = require('./signup-flow-helpers');

const MAILOSAUR_API_KEY = process.env.MAILOSAUR_API_KEY;
const MAILOSAUR_SERVER_ID = process.env.MAILOSAUR_SERVER_ID;
const SIGNUP_TEST_EMAIL_DOMAINS = process.env.SIGNUP_TEST_EMAIL_DOMAINS;
const STRIPE_TEST_CARD_NUMBER = '4000002760000016';

test('creates a new test account with credits', async ({
	page,
	context
}: {
	page: any;
	context: any;
}) => {
	// Capture browser diagnostics for debugging on failure.
	page.on('console', (msg: any) => {
		const ts = new Date().toISOString();
		consoleLogs.push(`[${ts}] [${msg.type()}] ${msg.text()}`);
	});
	page.on('request', (req: any) => {
		const ts = new Date().toISOString();
		networkActivities.push(`[${ts}] >> ${req.method()} ${req.url()}`);
	});
	page.on('response', (res: any) => {
		const ts = new Date().toISOString();
		networkActivities.push(`[${ts}] << ${res.status()} ${res.url()}`);
	});

	test.slow();
	test.setTimeout(300000); // 5 min — email delivery + Stripe can be slow

	const log = createSignupLogger('CREATE_ACCOUNT');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'create-acct' });

	await archiveExistingScreenshots(log);

	// --- Validate env vars ---
	const signupDomain = getSignupTestDomain(SIGNUP_TEST_EMAIL_DOMAINS);
	test.skip(!signupDomain, 'SIGNUP_TEST_EMAIL_DOMAINS must include a test domain.');
	test.skip(!MAILOSAUR_API_KEY, 'MAILOSAUR_API_KEY is required.');
	if (!signupDomain) throw new Error('Missing signup test domain.');

	const mailosaurServerId = getMailosaurServerId(signupDomain, MAILOSAUR_SERVER_ID);
	if (!mailosaurServerId) {
		throw new Error('Cannot derive Mailosaur server ID.');
	}
	const { deleteAllMessages, waitForMailosaurMessage, extractSixDigitCode } = createMailosaurClient(
		{ apiKey: MAILOSAUR_API_KEY, serverId: mailosaurServerId }
	);

	await context.grantPermissions(['clipboard-read', 'clipboard-write']);

	// --- Generate identity ---
	const signupEmail = buildSignupEmail(signupDomain);
	const signupUsername = signupEmail.split('@')[0];
	const signupPassword = 'TestAcct!2026pw';
	log('Generated identity.', { signupEmail, signupUsername });

	// Clear the Mailosaur inbox so we don't pick up stale emails.
	await deleteAllMessages();
	log('Cleared Mailosaur inbox.');

	// =========================================================================
	// 1. Navigate → open signup dialog → alpha disclaimer
	// =========================================================================
	await page.goto('/');
	await screenshot(page, 'home');

	const loginBtn = page.getByRole('button', { name: /login.*sign up|sign up/i });
	await expect(loginBtn).toBeVisible();
	await loginBtn.click();
	await screenshot(page, 'login-dialog');

	await assertNoMissingTranslations(page);

	// Switch to signup tab
	const loginTabs = page.locator('.login-tabs');
	await expect(loginTabs).toBeVisible();
	await loginTabs.getByRole('button', { name: /sign up/i }).click();
	await screenshot(page, 'signup-alpha');

	await assertNoMissingTranslations(page);

	// Alpha disclaimer — continue
	await page.getByRole('button', { name: /continue/i }).click();
	await screenshot(page, 'basics-step');
	await assertNoMissingTranslations(page);
	log('Reached basics step.');

	// =========================================================================
	// 2. Basics step — email, username, toggles
	// =========================================================================
	const emailInput = page.locator('input[type="email"][autocomplete="email"]');
	const usernameInput = page.locator('input[autocomplete="username"]');
	await expect(emailInput).toBeVisible();
	await emailInput.fill(signupEmail);
	await usernameInput.fill(signupUsername);

	const stayLoggedInToggle = page.locator('#stayLoggedIn');
	await setToggleChecked(stayLoggedInToggle, true);

	const termsToggle = page.locator('#terms-agreed-toggle');
	const privacyToggle = page.locator('#privacy-agreed-toggle');
	await setToggleChecked(termsToggle, true);
	await setToggleChecked(privacyToggle, true);

	const emailRequestedAt = new Date().toISOString();
	await page.getByRole('button', { name: /create new account/i }).click();
	log('Submitted basics, waiting for confirmation email.');

	// =========================================================================
	// 3. Email verification
	// =========================================================================
	const openMailLink = page.getByRole('link', { name: /open mail app/i });
	await expect(openMailLink).toBeVisible({ timeout: 15000 });
	await screenshot(page, 'confirm-email');

	log('Polling Mailosaur for confirmation email...');
	const confirmEmailMsg = await waitForMailosaurMessage({
		sentTo: signupEmail,
		receivedAfter: emailRequestedAt
	});
	const emailCode = extractSixDigitCode(confirmEmailMsg);
	expect(emailCode, 'Expected a 6-digit email confirmation code.').toBeTruthy();
	log('Got email code.', { emailCode });

	const codeInput = page.locator('input[inputmode="numeric"][maxlength="6"]');
	await codeInput.fill(emailCode);

	// =========================================================================
	// 4. Secure account — choose password
	// =========================================================================
	const passwordOption = page.getByRole('button', { name: /password/i });
	await expect(passwordOption).toBeVisible();
	await passwordOption.click();
	await screenshot(page, 'password-step');

	const passwordInputs = page.locator('input[autocomplete="new-password"]');
	await expect(passwordInputs).toHaveCount(2);
	await passwordInputs.nth(0).fill(signupPassword);
	await passwordInputs.nth(1).fill(signupPassword);
	log('Password set.');

	await page.getByRole('button', { name: /continue/i }).click();
	await screenshot(page, 'one-time-codes');
	log('Reached OTP setup.');

	// =========================================================================
	// 5. 2FA setup — show QR, copy secret, enter TOTP
	// =========================================================================
	// Show QR code so the secret input becomes visible
	const qrButton = page.getByRole('button', { name: /scan via 2fa app/i });
	await expect(qrButton).toBeVisible({ timeout: 10000 });
	await qrButton.click();
	await expect(page.locator('.qr-code')).toBeVisible();
	await qrButton.click(); // close QR overlay
	await expect(page.locator('.qr-code')).toBeHidden();

	// Copy the secret so the input is populated
	const copySecretButton = page.getByRole('button', { name: /copy secret/i });
	await copySecretButton.click();

	const secretInput = page.locator('input[aria-label="2FA Secret Key"]');
	await expect(secretInput).toBeVisible();
	const tfaSecret = await secretInput.inputValue();
	expect(tfaSecret, 'Expected a 2FA secret.').toBeTruthy();
	log('Captured 2FA secret.', { tfaSecret });

	const otpCode = generateTotp(tfaSecret);
	const otpInput = page.locator('#otp-code-input');
	await otpInput.fill(otpCode);
	log('Entered OTP.');

	// Pick an authenticator app name and continue
	const appNameInput = page.locator('input[placeholder*="app name"]');
	await appNameInput.click();
	await appNameInput.fill('Google');
	const appResult = page.getByRole('button', { name: /google authenticator/i });
	await appResult.click();

	await page.getByRole('button', { name: /continue/i }).click();
	await screenshot(page, 'backup-codes');
	log('Reached backup codes step.');

	// =========================================================================
	// 6. Backup codes — download and confirm
	// =========================================================================
	const backupDownloadBtn = page.getByRole('button', { name: /download/i }).first();
	const [backupDownload] = await Promise.all([
		page.waitForEvent('download'),
		backupDownloadBtn.click()
	]);
	expect(await backupDownload.suggestedFilename()).toMatch(/backup/i);
	log('Downloaded backup codes.');

	const backupConfirmToggle = page.locator('#confirm-storage-toggle-step5');
	await setToggleChecked(backupConfirmToggle, true);
	log('Confirmed backup codes stored → transitioning to recovery key step.');

	// =========================================================================
	// 7. Recovery key — download and confirm
	// =========================================================================
	// Wait for the recovery key step to load (heading changes from "Backup codes"
	// to "Recovery key").
	await expect(page.getByText(/recovery key/i).first()).toBeVisible({ timeout: 10000 });
	await screenshot(page, 'recovery-key-step');

	const recoveryDownloadBtn = page.getByRole('button', { name: /download/i }).first();
	const [recoveryDownload] = await Promise.all([
		page.waitForEvent('download'),
		recoveryDownloadBtn.click()
	]);
	expect(await recoveryDownload.suggestedFilename()).toMatch(/recovery/i);
	log('Downloaded recovery key.');

	const recoveryConfirmToggle = page.locator('#confirm-storage-toggle-step5');
	await setToggleChecked(recoveryConfirmToggle, true);
	log('Confirmed recovery key stored → transitioning to credits step.');

	// Wait for the credits step to load.
	await expect(page.getByText(/pay.*per use/i).first()).toBeVisible({ timeout: 10000 });
	await screenshot(page, 'credits-step');
	log('Reached credits step.');

	// =========================================================================
	// 8. Credits — purchase with Stripe test card
	// =========================================================================
	// Two-stage payment flow:
	//   Stage 1 (credits step): click the buy button to transition to the payment step.
	//   Stage 2 (payment step): click "Pay with an EU card instead" to get an inline
	//     Stripe Elements form (the main "Buy for X EUR" on the payment step opens
	//     Stripe Checkout which redirects to stripe.com and can't be automated here).

	// --- Stage 1: credits step → payment step ---
	const creditsBuyBtn = page.locator('.credits-package-container .buy-button').first();
	if (await creditsBuyBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
		await creditsBuyBtn.click();
		log('Clicked buy button on credits step → transitioning to payment step.');
	} else {
		await page.getByRole('button', { name: /buy for/i }).click();
		log('Clicked "Buy for" button on credits step (fallback selector).');
	}

	// Wait for the payment step to load — "Pay with an EU card instead" appears here.
	const euCardLink = page.getByText(/pay with an eu card/i);
	await expect(euCardLink).toBeVisible({ timeout: 10000 });
	await screenshot(page, 'payment-step');
	log('Reached payment step.');

	// --- Stage 2: click "Pay with an EU card instead" → inline Stripe form ---
	await euCardLink.click();
	log('Clicked "Pay with an EU card instead".');
	await screenshot(page, 'payment-eu-card');

	// Wait for the consent toggle to appear and accept it — the buy button
	// stays disabled until this toggle is checked.  The actual <input> checkbox
	// is CSS-hidden (custom toggle component), so we wait for its presence in
	// the DOM rather than visual visibility.
	const consentToggle = page.locator('#limited-refund-consent-toggle');
	await expect(consentToggle).toBeAttached({ timeout: 10000 });
	await setToggleChecked(consentToggle, true);
	log('Accepted refund consent.');
	await screenshot(page, 'payment-consent-accepted');

	// Wait for Stripe Elements iframe to load (inline card form).
	const stripeFrame = page.frameLocator('iframe[title*="Secure payment"]').first();
	await expect(
		stripeFrame.locator('input[name="cardNumber"], input[autocomplete="cc-number"]').first()
	).toBeVisible({ timeout: 30000 });

	await fillStripeCardDetails(page, STRIPE_TEST_CARD_NUMBER);
	log('Filled Stripe card details.');

	// Find the submit button in the payment form and wait for it to be enabled
	// (it enables after consent + valid card details).
	const payButton = page.locator('.payment-form .buy-button').first();
	await expect(payButton).toBeVisible({ timeout: 10000 });
	await expect(payButton).toBeEnabled({ timeout: 15000 });
	await payButton.click();
	log('Clicked pay/submit button.');

	await expect(page.getByText(/purchase successful/i)).toBeVisible({ timeout: 60000 });
	await screenshot(page, 'payment-success');
	log('Purchase completed.');

	// =========================================================================
	// 9. Finish setup → land in chat
	// =========================================================================
	await page
		.getByRole('button', { name: /finish setup/i })
		.first()
		.click();
	await page.waitForURL(/chat/);
	await screenshot(page, 'chat');
	log('Arrived in chat. Account creation complete.');

	// =========================================================================
	// 10. Write credentials to JSON for extraction
	// =========================================================================
	const credentials = {
		email: signupEmail,
		password: signupPassword,
		otpKey: tfaSecret,
		createdAt: new Date().toISOString()
	};

	// Write to artifacts/ (mounted as ./playwright-artifacts on host)
	const credPath = 'artifacts/account-credentials.json';
	fs.writeFileSync(credPath, JSON.stringify(credentials, null, 2));
	log('Wrote credentials to ' + credPath, credentials);

	// Also print to stdout so it appears in docker logs
	console.log('\n=== ACCOUNT CREDENTIALS ===');
	console.log(JSON.stringify(credentials, null, 2));
	console.log('=== END CREDENTIALS ===\n');
});
