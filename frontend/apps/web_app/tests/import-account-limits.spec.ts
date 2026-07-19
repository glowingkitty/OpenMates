/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Account Import V1 limits E2E coverage.
 *
 * Verifies Settings > Account > Import displays server-provided free allowance,
 * paid default selection, batch cap, estimated cost, and blocked-credit state
 * before any scan or encrypted persistence request is made.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const {
	installAccountImportMock,
	loginAndOpenImportSettings,
	uploadClaudeJson,
} = require('./helpers/account-import-test-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

test.describe('Account Import V1 limits', () => {
	test('shows free allowance, paid defaults, batch cap, and cost before import', async ({ page }: { page: any }) => {
		test.setTimeout(180000);
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

		const calls = await installAccountImportMock(page, {
			importId: 'web-import-limits',
			freeRemaining: 3,
			defaultSelectionCount: 20,
			maxBatchCount: 30,
			estimatedCredits: 20,
		});
		await loginAndOpenImportSettings(page, { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY });
		await uploadClaudeJson(page, 31);

		const summary = page.getByTestId('import-preview-summary');
		await expect(summary).toContainText('Chats found');
		await expect(summary).toContainText('31');
		await expect(summary).toContainText('Default selection');
		await expect(summary).toContainText('20');
		await expect(summary).toContainText('Batch limit');
		await expect(summary).toContainText('30');
		await expect(summary).toContainText('Free allowance remaining');
		await expect(summary).toContainText('3');
		await expect(page.getByText(/~20/i)).toBeVisible();

		expect(calls.map((call: { path: string }) => call.path)).toEqual(['/v1/account-imports/preview']);
	});

	test('blocks import before scan when preview says credits are insufficient', async ({ page }: { page: any }) => {
		test.setTimeout(180000);
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

		const calls = await installAccountImportMock(page, {
			importId: 'web-import-insufficient-credits',
			freeRemaining: 0,
			defaultSelectionCount: 0,
			maxBatchCount: 0,
			estimatedCredits: 1,
			canImport: false,
			reason: 'insufficient_credits',
		});
		await loginAndOpenImportSettings(page, { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY });
		await uploadClaudeJson(page, 1);

		await expect(page.getByText(/not have enough free allowance or credits/i)).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('account-import-start')).toBeDisabled();
		expect(calls.map((call: { path: string }) => call.path)).toEqual(['/v1/account-imports/preview']);
	});
});
