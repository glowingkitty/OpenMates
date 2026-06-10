/* eslint-disable @typescript-eslint/no-require-imports */
// @privacy-promise: cli-provisioned-account-web-login
export {};

/**
 * Verifies that an account provisioned through the OpenMates CLI can log in
 * through the web app with password + TOTP. The spec intentionally does not
 * mutate account recovery material so it can share the reserved CLI-provisioned
 * slot with the recovery-key login spec.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const {
	assertNoMissingTranslations,
	createSignupLogger,
	createStepScreenshotter,
	getIsolatedTestAccount
} = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');

const {
	email: OPENMATES_TEST_ACCOUNT_EMAIL,
	password: OPENMATES_TEST_ACCOUNT_PASSWORD,
	otpKey: OPENMATES_TEST_ACCOUNT_OTP_KEY
} = getIsolatedTestAccount('cli-created-account-login.spec.ts');

test.describe.configure({ mode: 'serial' });

test('logs into the web app with a CLI-provisioned password account', async ({ page }: { page: any }) => {
	test.slow();
	test.setTimeout(120000);

	skipWithoutCredentials(
		test,
		OPENMATES_TEST_ACCOUNT_EMAIL,
		OPENMATES_TEST_ACCOUNT_PASSWORD,
		OPENMATES_TEST_ACCOUNT_OTP_KEY
	);

	const logCheckpoint = createSignupLogger('CLI_CREATED_ACCOUNT_LOGIN');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'cli-created-account-login'
	});

	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot, {
		waitForEditor: true,
		credentials: {
			email: OPENMATES_TEST_ACCOUNT_EMAIL,
			password: OPENMATES_TEST_ACCOUNT_PASSWORD,
			otpKey: OPENMATES_TEST_ACCOUNT_OTP_KEY
		}
	});

	await expect(page.locator('[data-authenticated="true"]')).toBeVisible({ timeout: 15000 });
	await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 15000 });

	await page.getByTestId('profile-container').click();
	await expect(page.getByRole('menuitem', { name: /account/i })).toBeVisible({ timeout: 10000 });
	await page.getByRole('menuitem', { name: /account/i }).click();

	await assertNoMissingTranslations(page);
	logCheckpoint('CLI-provisioned account logged in and opened account settings.');
});
