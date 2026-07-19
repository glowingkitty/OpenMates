/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Account Import V1 deployed web E2E coverage.
 *
 * Verifies Settings > Account > Import parses Claude JSON and OpenMates Export
 * V1 ZIP fixtures in the browser, uses the V1 endpoint sequence, client-encrypts
 * before persistence, and reports unsupported OpenMates domains.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const {
	installAccountImportMock,
	loginAndOpenImportSettings,
	persistPayloads,
	uploadClaudeJson,
	uploadOpenMatesZip,
	writePersistArtifacts,
} = require('./helpers/account-import-test-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

test.describe('Account Import V1 web flow', () => {
	test('imports Claude JSON through scan and encrypted persistence', async ({ page }: { page: any }, testInfo: any) => {
		test.setTimeout(180000);
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

		const calls = await installAccountImportMock(page, { importId: 'web-import-claude' });
		await loginAndOpenImportSettings(page, { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY });
		await uploadClaudeJson(page, 1);

		await expect(page.getByTestId('import-preview-summary')).toContainText('Chats found');
		await expect(page.getByTestId('import-preview-summary')).toContainText('1');
		await page.getByTestId('account-import-start').click();
		await expect(page.getByTestId('import-results-container')).toContainText('2', { timeout: 30000 });

		const paths = calls.map((call: { path: string }) => call.path);
		expect(paths).toContain('/v1/account-imports/preview');
		expect(paths).toContain('/v1/account-imports/web-import-claude/scan');
		expect(paths).toContain('/v1/account-imports/web-import-claude/persist-encrypted');
		expect(paths).toContain('/v1/account-imports/web-import-claude/complete');

		const persistBody = persistPayloads(calls)[0] as { chats: Array<Record<string, unknown>> };
		expect(persistBody.chats).toHaveLength(1);
		expect(JSON.stringify(persistBody)).not.toContain('Synthetic web import user message');
		expect(JSON.stringify(persistBody)).not.toContain('Claude import chat 1');
		expect(persistBody.chats[0]).not.toHaveProperty('title');
		writePersistArtifacts(testInfo, calls, 'account-import-claude-persist.json');
	});

	test('parses OpenMates Export V1 ZIP and reports skipped domains', async ({ page }: { page: any }, testInfo: any) => {
		test.setTimeout(180000);
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

		const calls = await installAccountImportMock(page, { importId: 'web-import-openmates' });
		await loginAndOpenImportSettings(page, { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY });
		await uploadOpenMatesZip(page);

		await expect(page.getByText(/^This OpenMates archive also contains projects\./i)).toBeVisible({ timeout: 15000 });
		await expect(page.getByText(/Other domains are tracked in OPE-588/i)).toBeVisible();
		await page.getByTestId('account-import-start').click();
		await expect(page.getByTestId('import-results-container')).toContainText('1', { timeout: 30000 });

		const previewCall = calls.find((call: { path: string }) => call.path === '/v1/account-imports/preview');
		expect(previewCall?.body?.source).toBe('openmates');
		expect(JSON.stringify(persistPayloads(calls)[0])).not.toContain('Synthetic OpenMates web import message');
		writePersistArtifacts(testInfo, calls, 'account-import-openmates-persist.json');
	});
});
