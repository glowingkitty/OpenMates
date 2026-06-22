/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Account interests settings E2E coverage.
 *
 * Verifies the authenticated portion of
 * docs/specs/guest-interest-smart-selection/spec.yml: users can edit account
 * topic preferences from Settings > Account > Interests and the sync request
 * contains encrypted settings only, not cleartext tag IDs.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

async function openAccountInterestsSettings(page: any): Promise<void> {
	const settingsMenuButton = page.getByTestId('profile-container');
	await expect(settingsMenuButton).toBeVisible({ timeout: 15000 });
	await settingsMenuButton.click();

	const settingsMenu = page.getByTestId('settings-menu');
	await expect(settingsMenu).toBeVisible({ timeout: 10000 });
	await settingsMenu.getByRole('menuitem', { name: /^account$/i }).click();
	await settingsMenu.getByRole('menuitem', { name: /interests/i }).click();

	await expect(page.getByTestId('account-interests-list')).toBeVisible({ timeout: 15000 });
}

test.describe('Account interests settings', () => {
	test('can edit encrypted account interests without cleartext sync payloads', async ({ page }: { page: any }) => {
		test.setTimeout(120000);
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

		await loginToTestAccount(page, () => undefined, async () => undefined, {
			credentials: { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY }
		});
		await openAccountInterestsSettings(page);

		const softwareOption = page.getByTestId('account-interests-list-option-software_development');
		await expect(softwareOption).toBeVisible({ timeout: 10000 });
		await softwareOption.click();

		const requestPromise = page.waitForRequest(
			(req: any) => req.url().includes('/v1/settings/topic-preferences') && req.method() === 'POST',
			{ timeout: 15000 }
		);
		await page.getByTestId('account-interests-save').click();
		const request = await requestPromise;

		const body = JSON.parse(request.postData() || '{}');
		expect(body.encrypted_settings, 'topic preferences must sync as encrypted settings ciphertext').toBeTruthy();
		expect(JSON.stringify(body)).not.toContain('software_development');
		expect(JSON.stringify(body)).not.toContain('selectedTagIds');
	});
});
