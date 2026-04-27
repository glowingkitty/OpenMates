/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const {
	archiveExistingScreenshots,
	checkEmailQuota,
	createEmailClient,
	createSignupLogger,
	createStepScreenshotter,
	generateTotp,
	getE2EDebugUrl,
	getTestAccount
} = require('./signup-flow-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

async function openLoginDialog(page: any): Promise<void> {
	const headerButton = page.getByTestId('header-login-signup-btn');
	try {
		await expect(headerButton).toBeVisible({ timeout: 5000 });
		await headerButton.click({ timeout: 5000 });
	} catch {
		await page
			.getByRole('button', { name: /sign up\s*\/\s*login|login\s*\/\s*sign up/i })
			.first()
			.click({ timeout: 15000 });
	}

	await expect(page.getByTestId('login-tabs')).toBeVisible({ timeout: 10000 });
}

function getGmailAlias(label: string): string | null {
	const base = process.env.GMAIL_TEST_ADDRESS;
	if (!base || !base.includes('@')) return null;
	const [localPart, domain] = base.split('@');
	const slot = process.env.PLAYWRIGHT_WORKER_SLOT || '1';
	return `${localPart}+${label}-slot${slot}@${domain}`;
}

async function login(page: any, email: string, log: any): Promise<void> {
	await page.goto(getE2EDebugUrl('/'));
	await page.evaluate(() => localStorage.removeItem('emailLookupRateLimit'));

	await openLoginDialog(page);

	const loginTab = page.getByTestId('tab-login');
	await expect(loginTab).toBeVisible({ timeout: 10000 });
	await loginTab.click();

	const emailInput = page.locator('#login-email-input');
	await expect(emailInput).toBeVisible({ timeout: 15000 });
	await emailInput.fill(email);
	await page.locator('#login-continue-button').click();

	const passwordInput = page.locator('#login-password-input');
	await expect(passwordInput).toBeVisible({ timeout: 15000 });
	await passwordInput.fill(TEST_PASSWORD);

	const submitButton = page.locator('#login-submit-button');
	await submitButton.click();

	const otpInput = page.locator('#login-otp-input');
	await expect(otpInput).toBeVisible({ timeout: 15000 });
	await otpInput.fill(generateTotp(TEST_OTP_KEY));
	await submitButton.click();

	await page.waitForURL(/chat/, { timeout: 30000 });
	await page.waitForTimeout(5000);
	log('Logged in.', { email });
}

async function logout(page: any, log: any): Promise<void> {
	const profileContainer = page.getByTestId('profile-container');
	await expect(profileContainer).toBeVisible({ timeout: 10000 });
	await profileContainer.click();

	const logoutItem = page.getByRole('menuitem', { name: /logout|log out|abmelden/i });
	await expect(logoutItem).toBeVisible({ timeout: 10000 });
	await logoutItem.click();
	await expect(page.getByTestId('header-login-signup-btn')).toBeVisible({ timeout: 20000 });
	log('Logged out.');
}

async function openEmailSettings(page: any, log: any): Promise<void> {
	const profileContainer = page.getByTestId('profile-container');
	await expect(profileContainer).toBeVisible({ timeout: 10000 });
	await profileContainer.click();

	const settingsMenu = page.locator('[data-testid="settings-menu"].visible');
	await expect(settingsMenu).toBeVisible({ timeout: 10000 });

	const accountItem = settingsMenu.getByRole('menuitem', { name: /^account$/i }).first();
	await expect(accountItem).toBeVisible({ timeout: 10000 });
	await accountItem.click();

	const emailItem = settingsMenu.getByRole('menuitem', { name: /e-?mail|email/i }).first();
	await expect(emailItem).toBeVisible({ timeout: 10000 });
	await emailItem.click();

	await expect(page.getByTestId('email-change-new-email')).toBeVisible({ timeout: 15000 });
	log('Opened email settings.');
}

async function changeEmail(page: any, targetEmail: string, log: any): Promise<void> {
	const emailClient = createEmailClient(targetEmail);
	if (!emailClient) throw new Error('Email client unavailable');

	const requestedAt = new Date().toISOString();
	await page.getByTestId('email-change-new-email').fill(targetEmail);
	await page.getByTestId('email-change-request-code').click();
	log('Requested email change code.', { targetEmail });

	const message = await emailClient.waitForMailosaurMessage({
		sentTo: targetEmail,
		receivedAfter: requestedAt,
		timeoutMs: 120000
	});
	const code = emailClient.extractSixDigitCode(message);
	expect(code, 'Expected a six-digit email-change code.').toBeTruthy();

	await page.getByTestId('email-change-code').fill(code);
	await page.getByTestId('email-change-verify-code').click();
	await expect(page.getByText(/new e-mail verified|new email verified/i)).toBeVisible({ timeout: 15000 });

	await page.getByTestId('email-change-confirm').click();
	const authModal = page.getByTestId('auth-modal');
	await expect(authModal).toBeVisible({ timeout: 15000 });

	const passwordInput = authModal.locator('input[type="password"]');
	await expect(passwordInput).toBeVisible({ timeout: 15000 });
	await passwordInput.fill(TEST_PASSWORD);
	await authModal.getByTestId('auth-btn').click();

	const tfaInput = authModal.getByTestId('tfa-input');
	await expect(tfaInput).toBeVisible({ timeout: 15000 });
	await tfaInput.fill(generateTotp(TEST_OTP_KEY));

	await expect(page.getByText(/e-mail address changed successfully|email address changed successfully/i)).toBeVisible({
		timeout: 30000
	});
	await expect(page.getByText(targetEmail)).toBeVisible({ timeout: 15000 });
	log('Email changed.', { targetEmail });
}

test('changes account email and verifies login with the new address', async ({ page, context }: { page: any; context: any }) => {
	test.slow();
	test.setTimeout(420000);

	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	test.skip(!process.env.GMAIL_TEST_ADDRESS, 'GMAIL_TEST_ADDRESS is required for email-change migration.');

	const isCurrentMailosaur = TEST_EMAIL?.endsWith('.mailosaur.net');
	const migrationEmail = getGmailAlias('testacct');
	const temporaryEmail = getGmailAlias(`roundtrip-${Date.now()}`);
	test.skip(!migrationEmail || !temporaryEmail, 'Could not build Gmail test aliases.');

	const quota = await checkEmailQuota(isCurrentMailosaur ? migrationEmail! : temporaryEmail!);
	test.skip(!quota.available, `Email quota reached (${quota.current}/${quota.limit}).`);

	const log = createSignupLogger('SETTINGS_CHANGE_EMAIL');
	const screenshot = createStepScreenshotter(log, { filenamePrefix: 'settings-change-email' });
	await archiveExistingScreenshots(log);
	await context.grantPermissions(['clipboard-read', 'clipboard-write']);

	await login(page, TEST_EMAIL, log);
	await openEmailSettings(page, log);
	await screenshot(page, 'email-settings-open');

	if (isCurrentMailosaur) {
		await changeEmail(page, migrationEmail!, log);
		await screenshot(page, 'mailosaur-migrated-to-gmail');
		await logout(page, log);
		await login(page, migrationEmail!, log);
		log('Migration login with Gmail alias succeeded.', { migrationEmail });
		return;
	}

	await changeEmail(page, temporaryEmail!, log);
	await screenshot(page, 'changed-to-temporary-gmail');
	await changeEmail(page, TEST_EMAIL, log);
	await screenshot(page, 'changed-back-to-original-gmail');
	await logout(page, log);
	await login(page, TEST_EMAIL, log);
	log('Roundtrip login with original Gmail alias succeeded.', { email: TEST_EMAIL });
});
