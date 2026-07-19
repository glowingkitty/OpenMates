/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Account Import V1 duplicate-warning E2E coverage.
 *
 * Verifies duplicate source fingerprints show a warning and continuing creates
 * a new encrypted chat id instead of reusing or overwriting the source chat id.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const {
	installAccountImportMock,
	loginAndOpenImportSettings,
	persistPayloads,
	uploadClaudeJson,
	writePersistArtifacts,
} = require('./helpers/account-import-test-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

test.describe('Account Import V1 dedupe warnings', () => {
	test('warns on duplicate fingerprints but persists a separate new chat', async ({ page }: { page: any }, testInfo: any) => {
		test.setTimeout(180000);
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

		const calls = await installAccountImportMock(page, {
			importId: 'web-import-dedupe',
			duplicateFingerprints: ['placeholder-populated-after-preview-body'],
		});
		await loginAndOpenImportSettings(page, { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY });
		await uploadClaudeJson(page, 1, { duplicateTitle: 'Potential duplicate import' });

		const previewCall = calls.find((call: { path: string }) => call.path === '/v1/account-imports/preview');
		const fingerprint = Array.isArray(previewCall?.body?.source_fingerprints)
			? String(previewCall.body.source_fingerprints[0])
			: '';
		await page.unroute('**/v1/account-imports**');
		calls.length = 0;
		await installAccountImportMock(page, {
			importId: 'web-import-dedupe',
			duplicateFingerprints: [fingerprint],
		});
		await uploadClaudeJson(page, 1, { duplicateTitle: 'Potential duplicate import' });

		await expect(page.getByText(/may already have been imported/i)).toBeVisible({ timeout: 15000 });
		await expect(page.getByText(/will create new chats/i)).toBeVisible();
		await page.getByTestId('account-import-start').click();
		await expect(page.getByTestId('import-results-container')).toContainText('2', { timeout: 30000 });

		const persistBody = persistPayloads(calls)[0] as { chats: Array<Record<string, unknown>> };
		expect(persistBody.chats[0].chat_id).toBeTruthy();
		expect(persistBody.chats[0].chat_id).not.toBe('claude-chat-1');
		expect(JSON.stringify(persistBody)).not.toContain('Potential duplicate import');
		writePersistArtifacts(testInfo, calls, 'account-import-dedupe-persist.json');
	});
});
