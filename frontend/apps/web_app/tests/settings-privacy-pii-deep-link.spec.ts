/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Settings privacy PII deep-link checks.
 *
 * Verifies the deployed web app opens Hide personal data from the public PII
 * shortcuts without exposing settings state through query parameters. These
 * links are intentionally hash-based so the selected settings page remains
 * client-side after the initial document request.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { createSignupLogger, getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

const EXPECTED_SETTINGS_VIEW = 'privacy/hide-personal-data';

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

test.describe('privacy PII settings deep links', () => {
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
});
