/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Create a persistent test account via the real signup flow.
 *
 * Runs the full signup (email verification, password, 2FA, Stripe payment)
 * but does NOT delete the account. The created account is fully usable
 * (has credits, can send messages) and intended for reuse across E2E tests.
 *
 * Environment:
 *   CREATE_ACCOUNT_SLOT  — slot number (1-20), determines email/password
 *   SIGNUP_TEST_EMAIL_DOMAINS — Mailosaur test domain
 *   GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET / GMAIL_REFRESH_TOKEN — Gmail API credentials (preferred)
 *   MAILOSAUR_API_KEY / MAILOSAUR_SERVER_ID — Mailosaur credentials (fallback)
 *
 * Usage:
 *   gh workflow run playwright-spec.yml -f spec=create-test-account.spec.ts \
 *     -f create_account_slot=1
 *
 * After the run, parse logs for the ===ACCOUNT_CREDENTIALS=== block and set
 * GitHub secrets:
 *   gh secret set OPENMATES_TEST_ACCOUNT_{SLOT}_EMAIL --body "..."
 *   gh secret set OPENMATES_TEST_ACCOUNT_{SLOT}_PASSWORD --body "..."
 *   gh secret set OPENMATES_TEST_ACCOUNT_{SLOT}_OTP_KEY --body "..."
 *
 * Architecture: docs/architecture/e2e-testing.md
 * Test reference: python3 scripts/run_tests.py --spec create-test-account.spec.ts
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	setToggleChecked,
	fillStripeCardDetails,
	getSignupTestDomain,
	buildTestAccountEmail,
	createEmailClient,
	checkEmailQuota,
	generateTotp,
	assertNoMissingTranslations,
	getE2EDebugUrl
} = require('./signup-flow-helpers');

const SIGNUP_TEST_EMAIL_DOMAINS = process.env.SIGNUP_TEST_EMAIL_DOMAINS;
const CREATE_ACCOUNT_SLOT = process.env.CREATE_ACCOUNT_SLOT;
const STRIPE_TEST_CARD_NUMBER = '4000002760000016';

test.describe('Create persistent test account', () => {
	test('completes full signup flow with payment for a reusable test account', async ({
		page,
		context
	}: {
		page: any;
		context: any;
	}) => {
		const slot = parseInt(CREATE_ACCOUNT_SLOT || '', 10);
		test.skip(!CREATE_ACCOUNT_SLOT || isNaN(slot), 'CREATE_ACCOUNT_SLOT env var is required (1-20).');
		test.skip(!SIGNUP_TEST_EMAIL_DOMAINS, 'SIGNUP_TEST_EMAIL_DOMAINS is required.');

		const emailClient = createEmailClient();
		test.skip(!emailClient, 'Email credentials required (GMAIL_* or MAILOSAUR_*).');

		const quota = await checkEmailQuota();
		test.skip(!quota.available, `Email quota reached (${quota.current}/${quota.limit}).`);

		// Allow generous time for full signup + payment flow.
		test.setTimeout(240000);

		const logCheckpoint = createSignupLogger('CREATE_ACCOUNT');
		const takeScreenshot = createStepScreenshotter(logCheckpoint);

		await archiveExistingScreenshots(logCheckpoint);

		const signupDomain = getSignupTestDomain(SIGNUP_TEST_EMAIL_DOMAINS);
		if (!signupDomain) {
			throw new Error('Missing signup test domain.');
		}

		const { waitForMailosaurMessage, extractSixDigitCode } = emailClient!;

		await context.grantPermissions(['clipboard-read', 'clipboard-write']);

		// Build deterministic credentials for this slot
		const accountEmail = buildTestAccountEmail(slot, signupDomain);
		const accountUsername = `testacct${slot}`;
		const accountPassword = `TestAcct!2026pw${slot}`;

		logCheckpoint(`Creating test account for slot ${slot}.`, { accountEmail });

		// ─── Open signup dialog ───────────────────────────────────────────
		await page.goto(getE2EDebugUrl('/'));
		await takeScreenshot(page, 'home');

		const headerButton = page.getByRole('button', { name: /login.*sign up|sign up/i });
		await expect(headerButton).toBeVisible();
		await headerButton.click();
		logCheckpoint('Opened login dialog.');

		// Switch to signup tab
		const loginTabs = page.getByTestId('login-tabs');
		await expect(loginTabs).toBeVisible();
		await loginTabs.getByRole('button', { name: /sign up/i }).click();

		// Alpha disclaimer: continue
		await page.getByRole('button', { name: /continue/i }).click();
		logCheckpoint('Passed alpha disclaimer.');

		// ─── Basics step ──────────────────────────────────────────────────
		const emailInput = page.locator('input[type="email"][autocomplete="email"]');
		const usernameInput = page.locator('input[autocomplete="username"]');
		await expect(emailInput).toBeVisible({ timeout: 15000 });
		await emailInput.fill(accountEmail);
		await usernameInput.fill(accountUsername);

		// Stay logged in
		const stayLoggedInToggle = page.locator('#stayLoggedIn');
		await setToggleChecked(stayLoggedInToggle, true);

		// Terms and privacy consent
		const termsToggle = page.locator('#terms-agreed-toggle');
		const privacyToggle = page.locator('#privacy-agreed-toggle');
		await setToggleChecked(termsToggle, true);
		await setToggleChecked(privacyToggle, true);

		const emailRequestedAt = new Date().toISOString();
		await page.getByRole('button', { name: /create new account/i }).click();
		logCheckpoint('Submitted basics, waiting for email confirmation.');

		// ─── Email confirmation ───────────────────────────────────────────
		const openMailLink = page.getByRole('link', { name: /open mail app/i });
		await expect(openMailLink).toBeVisible({ timeout: 15000 });

		logCheckpoint('Polling Mailosaur for confirmation email.');
		const confirmEmail = await waitForMailosaurMessage({
			sentTo: accountEmail,
			receivedAfter: emailRequestedAt
		});
		const emailCode = extractSixDigitCode(confirmEmail);
		expect(emailCode, 'Expected a 6-digit confirmation code.').toBeTruthy();
		logCheckpoint('Received confirmation code.');

		const confirmInput = page.locator('input[inputmode="numeric"][maxlength="6"]');
		await confirmInput.fill(emailCode);

		// ─── Password step ────────────────────────────────────────────────
		const passwordOption = page.locator('#signup-password-option');
		await expect(passwordOption).toBeVisible({ timeout: 15000 });
		await passwordOption.click();

		const passwordInputs = page.locator('input[autocomplete="new-password"]');
		await expect(passwordInputs).toHaveCount(2);
		await passwordInputs.nth(0).fill(accountPassword);
		await passwordInputs.nth(1).fill(accountPassword);
		logCheckpoint('Password fields completed.');

		await page.locator('#signup-password-continue').click();
		logCheckpoint('Reached one-time codes step.');

		// ─── 2FA setup ────────────────────────────────────────────────────
		// Copy the 2FA secret
		const copySecretButton = page.locator('#signup-2fa-copy-secret');
		await copySecretButton.click();

		const secretInput = page.locator('input[aria-label="2FA Secret Key"]');
		await expect(secretInput).toBeVisible();

		const tfaSecret = await secretInput.inputValue();
		expect(tfaSecret, 'Expected a 2FA secret.').toBeTruthy();
		logCheckpoint('Retrieved 2FA secret.');

		// Generate and enter TOTP
		const otpCode = generateTotp(tfaSecret);
		const otpInput = page.locator('#otp-code-input');
		await otpInput.fill(otpCode);
		logCheckpoint('Entered OTP code.');

		// Pick authenticator app
		const appNameInput = page.locator('input[placeholder*="app name"]');
		await appNameInput.click();
		await appNameInput.fill('Google');
		const appResult = page.getByRole('button', { name: /google authenticator/i });
		await appResult.click();

		const tfaContinueButton = page.locator('#signup-2fa-reminder-continue');
		await tfaContinueButton.click();
		logCheckpoint('Reached backup codes step.');

		// ─── Backup codes ─────────────────────────────────────────────────
		const backupDownloadButton = page.locator('#signup-backup-codes-download');
		const [backupDownload] = await Promise.all([
			page.waitForEvent('download'),
			backupDownloadButton.click()
		]);
		expect(await backupDownload.suggestedFilename()).toMatch(/backup/i);
		logCheckpoint('Downloaded backup codes.');

		const backupConfirmToggle = page.locator('#confirm-storage-toggle-step5');
		await setToggleChecked(backupConfirmToggle, true);
		logCheckpoint('Confirmed backup code storage.');

		// ─── Recovery key ─────────────────────────────────────────────────
		const recoveryDownloadButton = page.locator('#signup-recovery-key-download');
		const [recoveryDownload] = await Promise.all([
			page.waitForEvent('download'),
			recoveryDownloadButton.click()
		]);
		expect(await recoveryDownload.suggestedFilename()).toMatch(/recovery/i);
		logCheckpoint('Downloaded recovery key.');

		const recoveryCopyButton = page.locator('#signup-recovery-key-copy');
		await recoveryCopyButton.click();

		const recoveryConfirmToggle = page.locator('#confirm-storage-toggle-step5');
		await setToggleChecked(recoveryConfirmToggle, true);
		logCheckpoint('Reached credits step.');

		// ─── Credits + Payment ────────────────────────────────────────────
		// Buy the first available credits package
		await page.getByTestId('credits-package').getByTestId('buy-button').first().click();
		logCheckpoint('Reached payment consent step.');

		// Accept limited refund consent
		const consentToggle = page.locator('#limited-refund-consent-toggle');
		await setToggleChecked(consentToggle, true);
		logCheckpoint('Payment consent accepted.');

		// Fill Stripe test card
		await fillStripeCardDetails(page, STRIPE_TEST_CARD_NUMBER);
		logCheckpoint('Filled Stripe card details.');

		// Submit payment
		await page.getByTestId('payment-form').getByTestId('buy-button').click();
		await expect(page.getByText(/purchase successful/i)).toBeVisible({ timeout: 60000 });
		logCheckpoint('Purchase completed successfully.');

		// Finish setup → redirect to chat
		await page.locator('#signup-finish-setup').click();
		await page.waitForURL(/chat/);
		logCheckpoint('Arrived in chat after signup.');

		// ─── Output credentials immediately ───────────────────────────────
		// Output BEFORE any optional verifications so credentials are always captured.
		console.log('===ACCOUNT_CREDENTIALS===');
		console.log(`SLOT=${slot}`);
		console.log(`EMAIL=${accountEmail}`);
		console.log(`PASSWORD=${accountPassword}`);
		console.log(`OTP_KEY=${tfaSecret}`);
		console.log('===END_CREDENTIALS===');

		logCheckpoint(`Account slot ${slot} created successfully.`, {
			email: accountEmail,
			username: accountUsername
		});

		// Verify no missing translations
		await assertNoMissingTranslations(page);

		// Verify credits are available (wait briefly for balance to update after payment)
		const settingsMenuButton = page.getByTestId('profile-container');
		await settingsMenuButton.click();
		await expect(page.locator('[data-testid="settings-menu"].visible')).toBeVisible();

		const creditsAmount = page.getByTestId('credits-amount');
		await expect(creditsAmount).toBeVisible();
		// Credits may take a moment to reflect after Stripe webhook
		await page.waitForTimeout(3000);
		const creditsText = (await creditsAmount.textContent()) || '';
		const creditsValue = Number.parseInt(creditsText.replace(/[^\d]/g, ''), 10);
		logCheckpoint('Credits balance check.', { creditsValue, creditsText });

		// NOTE: Account is intentionally NOT deleted — it persists for E2E test reuse.
	});
});
