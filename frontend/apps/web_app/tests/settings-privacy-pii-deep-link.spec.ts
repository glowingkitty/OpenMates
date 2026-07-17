/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Settings deep-link checks.
 *
 * Verifies the deployed web app opens nested settings destinations from a cold
 * hash navigation. These links are intentionally hash-based so the selected
 * settings page remains client-side after the initial document request.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { createSignupLogger, getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

const EXPECTED_SETTINGS_VIEW = 'privacy/hide-personal-data';
const EXPECTED_ACCOUNT_DELETE_VIEW = 'account/delete';

async function expectHidePersonalDataSettings(page: any): Promise<void> {
	const settingsMenu = page.getByTestId('settings-menu');
	await expect(settingsMenu).toBeVisible({ timeout: 20000 });
	await expect(settingsMenu).toHaveAttribute('data-active-view', EXPECTED_SETTINGS_VIEW, {
		timeout: 20000
	});
	await expect.poll(() => new URL(page.url()).search, {
		message: 'settings deep links must not add query parameters',
		timeout: 5000
	}).toBe('');
}

async function expectAccountDeleteSettings(page: any): Promise<void> {
	const settingsMenu = page.getByTestId('settings-menu');
	await expect(settingsMenu).toBeVisible({ timeout: 20000 });
	await expect(settingsMenu).toHaveAttribute('data-active-view', EXPECTED_ACCOUNT_DELETE_VIEW, {
		timeout: 20000
	});
	await expect(page.getByTestId('delete-account-container')).toBeVisible({ timeout: 20000 });
}

test.describe('settings deep links', () => {
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

	test('opens Hide personal data from hash aliases and /privacy/pii', async ({ page }: { page: any }) => {
		test.slow();
		test.setTimeout(180000);

		const log = createSignupLogger('SETTINGS_PRIVACY_PII_DEEP_LINK');
		await loginToTestAccount(page, log);

		for (const path of ['/#settings/privacy/hide-personal-data', '/#settings/privacy/pii']) {
			log(`Checking settings deep link: ${path}`);
			await page.goto(getE2EDebugUrl(path), { waitUntil: 'domcontentloaded' });
			await expectHidePersonalDataSettings(page);
		}

		log('Checking settings short URL redirect: /privacy/pii');
		const privacyPiiUrl = new URL('/privacy/pii', page.url()).toString();
		const redirectResponse = await page.request.get(privacyPiiUrl, { maxRedirects: 0 });
		expect(redirectResponse.status()).toBe(302);
		expect(redirectResponse.headers().location).toBe('/#settings/privacy/pii');

		await page.goto(getE2EDebugUrl('/#settings/privacy/pii'), { waitUntil: 'domcontentloaded' });
		await expectHidePersonalDataSettings(page);
	});

	test('opens Delete account from a cold authenticated hash navigation', async ({ page }: { page: any }) => {
		test.slow();
		test.setTimeout(180000);

		const log = createSignupLogger('SETTINGS_ACCOUNT_DELETE_DEEP_LINK');
		await loginToTestAccount(page, log);

		await page.goto(getE2EDebugUrl('/#settings/account/delete'), { waitUntil: 'domcontentloaded' });
		await expectAccountDeleteSettings(page);
	});
});
