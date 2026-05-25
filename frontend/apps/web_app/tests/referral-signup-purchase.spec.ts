/* eslint-disable @typescript-eslint/no-require-imports */
// @privacy-promise: no-third-party-tracking
export {};
// NOTE:
// End-to-end referral test: existing test account shares its code, a new user
// signs up from #ref, purchases credits, receives bonus credits/toast, and the
// original referrer receives the referral reward email.

const { test, expect, assertNoThirdPartyCookies } = require('./helpers/cookie-audit');
const {
	archiveExistingScreenshots,
	assertNoMissingTranslations,
	buildSignupEmail,
	checkEmailQuota,
	createEmailClient,
	createSignupLogger,
	createStepScreenshotter,
	generateTotp,
	getE2EDebugUrl,
	getSignupTestDomain,
	getTestAccount,
	setToggleChecked
} = require('./signup-flow-helpers');
const { loginToTestAccount, openSignupInterface } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const STRIPE_TEST_CARD_NUMBER = '4242424242424242';
const SIGNUP_TEST_EMAIL_DOMAINS = process.env.SIGNUP_TEST_EMAIL_DOMAINS;
const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

async function getReferralCodeFromSettings(page: any): Promise<string> {
	await page.getByTestId('profile-container').click();
	await expect(page.locator('[data-testid="settings-menu"].visible')).toBeVisible();
	await page.getByRole('menuitem', { name: /billing/i }).click();
	const referralItem = page.getByRole('menuitem', { name: /referral code/i });
	await expect(referralItem).toBeVisible({ timeout: 15000 });
	await referralItem.click();
	await expect(page.getByTestId('referral-code-settings')).toBeVisible({ timeout: 15000 });
	const referralText = (await page.getByTestId('referral-link').textContent()) || '';
	const code = new URL(referralText.trim()).hash.match(/ref=([A-Z0-9]+)/)?.[1];
	expect(code, 'Expected a referral code in settings').toBeTruthy();
	return code as string;
}

async function completeSignupAndPurchase(page: any, context: any, emailClient: any, signupEmail: string, referralCode: string, log: any, screenshot: any): Promise<string> {
	const { waitForMailosaurMessage, extractSixDigitCode } = emailClient;
	const signupPassword = 'SignupTest!234';
	const signupUsername = signupEmail.split('@')[0].replace(/[^a-z0-9_-]/gi, '-').slice(0, 32);

	page.setDefaultTimeout(30000);
	await context.grantPermissions(['clipboard-read', 'clipboard-write']);
	await page.goto(getE2EDebugUrl(`/#ref=${referralCode}`));
	await page.waitForLoadState('load');
	await expect(page).not.toHaveURL(/#.*ref=/, { timeout: 10000 });
	const storedReferralCode = await page.evaluate(() => sessionStorage.getItem('openmates_pending_referral_code'));
	expect(storedReferralCode).toBe(referralCode);
	log('Captured referral code in referred-user session.', { referralCode });
	await openSignupInterface(page);
	await page.getByTestId('login-tabs').getByRole('button', { name: /sign up/i }).click();

	await page.getByRole('button', { name: /continue/i }).click();
	await screenshot(page, 'referral-signup-basics');
	log('Reached referred signup basics step.', { signupEmail });
	const emailRequestedAt = new Date().toISOString();
	const emailInput = page.locator('input[type="email"][autocomplete="email"]').first();
	const usernameInput = page.locator('input[autocomplete="username"]').first();
	await expect(emailInput).toBeVisible();
	await expect(usernameInput).toBeVisible();
	await emailInput.fill(signupEmail);
	await expect(emailInput).toHaveValue(signupEmail);
	await usernameInput.fill(signupUsername);
	await expect(usernameInput).toHaveValue(signupUsername);
	const stayLoggedInToggle = page.locator('#stayLoggedIn');
	const termsToggle = page.locator('#terms-agreed-toggle');
	const privacyToggle = page.locator('#privacy-agreed-toggle');
	await setToggleChecked(stayLoggedInToggle, true);
	await setToggleChecked(termsToggle, true);
	await setToggleChecked(privacyToggle, true);
	await expect(stayLoggedInToggle).toBeChecked();
	await expect(termsToggle).toBeChecked();
	await expect(privacyToggle).toBeChecked();
	await screenshot(page, 'referral-signup-basics-filled');
	log('Filled referred signup basics.', { signupEmail, signupUsername });
	await page.getByRole('button', { name: /create new account/i }).click();
	log('Submitted referred signup basics.', { signupEmail });

	await expect(page.getByRole('link', { name: /open mail app/i })).toBeVisible({ timeout: 10000 });
	const confirmEmailMessage = await waitForMailosaurMessage({ sentTo: signupEmail, receivedAfter: emailRequestedAt });
	const emailCode = extractSixDigitCode(confirmEmailMessage);
	expect(emailCode).toBeTruthy();
	await page.locator('input[inputmode="numeric"][maxlength="6"]').fill(emailCode);

	await page.locator('#signup-password-option').click();
	const passwordInputs = page.locator('input[autocomplete="new-password"]');
	await expect(passwordInputs).toHaveCount(2);
	await passwordInputs.nth(0).fill(signupPassword);
	await passwordInputs.nth(1).fill(signupPassword);
	await page.locator('#signup-password-continue').click();

	await page.locator('#signup-2fa-scan-qr').click();
	await page.locator('#signup-2fa-scan-qr').click();
	await page.locator('#signup-2fa-copy-secret').click();
	const secretInput = page.locator('input[aria-label="2FA Secret Key"]');
	await expect(secretInput).toBeVisible();
	const tfaSecret = await secretInput.inputValue();
	await page.locator('#otp-code-input').fill(generateTotp(tfaSecret));
	const appNameInput = page.locator('input[placeholder*="app name"]');
	await appNameInput.fill('Google');
	await page.getByRole('button', { name: /google authenticator/i }).click();
	await page.locator('#signup-2fa-reminder-continue').click();

	const backupDownloadButton = page.locator('#signup-backup-codes-download');
	await Promise.all([page.waitForEvent('download'), backupDownloadButton.click()]);
	await setToggleChecked(page.locator('#confirm-storage-toggle-step5'), true);
	const recoveryDownloadButton = page.locator('#signup-recovery-key-download');
	await Promise.all([page.waitForEvent('download'), recoveryDownloadButton.click()]);
	await page.locator('#signup-recovery-key-copy').click();
	const [printPage] = await Promise.all([context.waitForEvent('page'), page.locator('#signup-recovery-key-print').click()]);
	await printPage.close();
	await setToggleChecked(page.locator('#confirm-storage-toggle-step5'), true);

	await page.getByTestId('credits-package').getByTestId('buy-button').first().click();
	await setToggleChecked(page.locator('#limited-refund-consent-toggle'), true);
	await page.waitForSelector('#checkout iframe', { state: 'attached', timeout: 30000 });
	await page.waitForTimeout(3000);
	await screenshot(page, 'referral-payment-form');
	const checkoutFrame = page.frameLocator('#checkout iframe');
	const cardTab = checkoutFrame.getByRole('radio', { name: /card/i });
	if (await cardTab.isVisible({ timeout: 5000 }).catch(() => false)) await cardTab.click();
	const cardInput = checkoutFrame.locator('input[autocomplete="cc-number"], input[name="number"], input[name="cardNumber"]').first();
	await cardInput.waitFor({ state: 'visible', timeout: 20000 });
	await cardInput.pressSequentially(STRIPE_TEST_CARD_NUMBER, { delay: 30 });
	await checkoutFrame.locator('input[autocomplete="cc-exp"], input[name="expiry"], input[name="cardExpiry"]').first().pressSequentially('1234', { delay: 30 });
	await checkoutFrame.locator('input[autocomplete="cc-csc"], input[name="cvc"], input[name="cardCvc"]').first().pressSequentially('123', { delay: 30 });
	const nameInput = checkoutFrame.getByPlaceholder(/full name on card/i);
	if (await nameInput.isVisible({ timeout: 3000 }).catch(() => false)) await nameInput.pressSequentially('Referral Test User', { delay: 30 });
	const paymentSubmittedAt = new Date().toISOString();
	await checkoutFrame.locator('button[type="submit"], button:has-text("Pay"), button:has-text("Subscribe")').first().click();
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
		await checkoutFrame.locator('button[type="submit"], button:has-text("Pay")').first().click({ force: true });
	}

	await expect(page.getByText(/purchase successful/i).first()).toBeVisible({ timeout: 120000 });
	await expect(page.getByText(/referral reward was applied.*2000 free credits/i).first()).toBeVisible({ timeout: 30000 });
	await page.getByTestId('signup-finish-setup').first().click();
	await page.waitForURL(/chat/);
	await assertNoMissingTranslations(page);
	return paymentSubmittedAt;
}

test('referral signup purchase awards credits and notifies both users', async ({ page, context, browser }: { page: any; context: any; browser: any }) => {
	test.slow();
	test.setTimeout(900000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	const log = createSignupLogger('REFERRAL_SIGNUP_PURCHASE');
	const screenshot = createStepScreenshotter(log);
	await archiveExistingScreenshots(log);

	const signupDomain = getSignupTestDomain(SIGNUP_TEST_EMAIL_DOMAINS);
	test.skip(!signupDomain, 'SIGNUP_TEST_EMAIL_DOMAINS must include a test domain.');
	const emailClient = createEmailClient();
	test.skip(!emailClient, 'Email credentials required (GMAIL_* or MAILOSAUR_*).');
	const quota = await checkEmailQuota();
	test.skip(!quota.available, `Email quota reached (${quota.current}/${quota.limit}).`);

	await loginToTestAccount(page, log, screenshot, { waitForEditor: false });
	const referralCode = await getReferralCodeFromSettings(page);
	log('Loaded referrer code from settings.', { referralCode });

	const referredContext = await browser.newContext();
	const referredPage = await referredContext.newPage();
	try {
		const referredEmail = buildSignupEmail(signupDomain as string);
		const paymentSubmittedAt = await completeSignupAndPurchase(
			referredPage,
			referredContext,
			emailClient,
			referredEmail,
			referralCode,
			log,
			screenshot
		);
		log('Referred user completed signup and purchase.', { referredEmail });

		const referralEmail = await emailClient.waitForMailosaurMessage({
			sentTo: TEST_EMAIL,
			subjectContains: 'Someone used your referral code',
			receivedAfter: paymentSubmittedAt,
			timeoutMs: 180000
		});
		const referralText = referralEmail.text?.body || '';
		expect(referralText).toMatch(/Someone used your referral code/i);
		expect(referralText).toMatch(/2000 free credits/i);
		log('Received referrer reward email.');
	} finally {
		await referredContext.close();
	}

	await assertNoThirdPartyCookies(context);
});
