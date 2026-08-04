/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Account Import V1 deployed web E2E coverage.
 *
 * Verifies Settings > Account > Import parses Claude JSON, ChatGPT official,
 * OpenCode CLI, and OpenMates Export V1 fixtures in the browser, uses the V1
 * endpoint sequence, client-encrypts before persistence, and reports unsupported
 * OpenMates domains.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const {
	installAccountImportMock,
	loginAndOpenImportSettings,
	persistPayloads,
	selectImportSource,
	uploadChatGPTZip,
	uploadClaudeJson,
	uploadGenericJson,
	uploadOpenCodeJson,
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
		await expect(page.getByTestId('account-import-file-upload')).not.toBeVisible();
		await selectImportSource(page, 'claude');
		await uploadClaudeJson(page, 1);

		await expect(page.getByTestId('import-preview-summary')).toContainText('Chats found');
		await expect(page.getByTestId('import-preview-summary')).toContainText('1');
		await page.getByTestId('account-import-start').click();
		await expect(page.getByTestId('import-results-container')).toContainText('2', { timeout: 30000 });

		const paths = calls.map((call: { path: string }) => call.path);
		expect(paths).toContain('/v1/account-imports/preview');
		expect(paths).toContain('/v1/account-imports/web-import-claude/confirm');
		expect(paths).toContain('/v1/account-imports/web-import-claude/status');
		expect(paths).toContain('/v1/account-imports/web-import-claude/scan');
		expect(paths).toContain('/v1/account-imports/web-import-claude/compress');
		expect(paths).toContain('/v1/account-imports/web-import-claude/persist-encrypted');
		expect(paths).toContain('/v1/account-imports/web-import-claude/complete');

		const persistBody = persistPayloads(calls)[0] as { chats: Array<Record<string, unknown>> };
		expect(persistBody.chats).toHaveLength(1);
		expect(JSON.stringify(persistBody)).not.toContain('Synthetic web import user message');
		expect(JSON.stringify(persistBody)).not.toContain('Claude import chat 1');
		expect(persistBody.chats[0]).not.toHaveProperty('title');
		writePersistArtifacts(testInfo, calls, 'account-import-claude-persist.json');
	});

	test('imports ChatGPT ZIP through scan and encrypted persistence', async ({ page }: { page: any }, testInfo: any) => {
		test.setTimeout(180000);
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

		const calls = await installAccountImportMock(page, { importId: 'web-import-chatgpt' });
		await loginAndOpenImportSettings(page, { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY });
		await selectImportSource(page, 'chatgpt');
		await uploadChatGPTZip(page);

		await expect(page.getByTestId('import-preview-summary')).toContainText('Chats found');
		await expect(page.getByTestId('import-preview-summary')).toContainText('1');
		await page.getByTestId('account-import-start').click();
		await expect(page.getByTestId('import-results-container')).toContainText('2 messages imported', { timeout: 30000 });

		const paths = calls.map((call: { path: string }) => call.path);
		expect(paths).toContain('/v1/account-imports/preview');
		expect(paths).toContain('/v1/account-imports/web-import-chatgpt/scan');
		expect(paths).toContain('/v1/account-imports/web-import-chatgpt/persist-encrypted');
		expect(paths).toContain('/v1/account-imports/web-import-chatgpt/complete');

		const previewCall = calls.find((call: { path: string }) => call.path === '/v1/account-imports/preview');
		expect(previewCall?.body?.source).toBe('chatgpt');
		const persistBody = persistPayloads(calls)[0] as { chats: Array<Record<string, unknown>> };
		expect(persistBody.chats).toHaveLength(1);
		expect(JSON.stringify(persistBody)).not.toContain('Synthetic ChatGPT web import user message');
		expect(JSON.stringify(persistBody)).not.toContain('Synthetic ChatGPT web import chat');
		expect(JSON.stringify(persistBody)).not.toContain('This ChatGPT branch must not import');
		expect(persistBody.chats[0]).not.toHaveProperty('title');
		writePersistArtifacts(testInfo, calls, 'account-import-chatgpt-persist.json');
	});

	test('imports visible OpenCode transcript text without private parts or file payloads', async ({ page }: { page: any }, testInfo: any) => {
		test.setTimeout(180000);
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

		const calls = await installAccountImportMock(page, { importId: 'web-import-opencode' });
		await loginAndOpenImportSettings(page, { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY });
		await selectImportSource(page, 'opencode');
		await uploadOpenCodeJson(page);

		await expect(page.getByTestId('import-preview-summary')).toContainText('Chats found');
		await expect(page.getByTestId('import-preview-summary')).toContainText('1');
		await page.getByTestId('account-import-start').click();
		await expect(page.getByTestId('import-results-container')).toContainText('2 messages imported', { timeout: 30000 });

		const previewCall = calls.find((call: { path: string }) => call.path === '/v1/account-imports/preview');
		expect(previewCall?.body?.source).toBe('opencode');
		const scanCall = calls.find((call: { path: string }) => call.path === '/v1/account-imports/web-import-opencode/scan');
		const scanJson = JSON.stringify(scanCall?.body);
		expect(scanJson).toContain('Synthetic OpenCode web import user message');
		expect(scanJson).toContain('Synthetic OpenCode web import assistant message');
		expect(scanJson).not.toContain('OpenCode reasoning must not import');
		expect(scanJson).not.toContain('OpenCode tool output must not import');
		expect(scanJson).not.toContain('cHJpdmF0ZQ==');

		const persistBody = persistPayloads(calls)[0] as { chats: Array<Record<string, unknown>> };
		expect(persistBody.chats).toHaveLength(1);
		expect(JSON.stringify(persistBody)).not.toContain('Synthetic OpenCode web import');
		expect(persistBody.chats[0]).not.toHaveProperty('title');
		writePersistArtifacts(testInfo, calls, 'account-import-opencode-persist.json');
	});

	test('parses OpenMates Export V1 ZIP and reports skipped domains', async ({ page }: { page: any }, testInfo: any) => {
		test.setTimeout(180000);
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

		const calls = await installAccountImportMock(page, { importId: 'web-import-openmates' });
		await loginAndOpenImportSettings(page, { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY });
		await selectImportSource(page, 'openmates');
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

	test('imports strict generic Gemini JSON with encrypted provider identity and summary', async ({ page }: { page: any }, testInfo: any) => {
		test.setTimeout(180000);
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

		const calls = await installAccountImportMock(page, { importId: 'web-import-gemini' });
		await loginAndOpenImportSettings(page, { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY });
		await selectImportSource(page, 'gemini');
		await expect(page.getByTestId('account-import-gemini-generic-note')).toContainText('Gemini Takeout');
		await uploadGenericJson(page);
		await page.getByTestId('account-import-start').click();
		await expect(page.getByTestId('import-results-container')).toContainText('2 messages imported', { timeout: 30000 });

		const previewCall = calls.find((call: { path: string }) => call.path === '/v1/account-imports/preview');
		expect(previewCall?.body?.source).toBe('gemini');
		expect(previewCall?.body?.parser_format).toBe('generic');
		const paths = calls.map((call: { path: string }) => call.path);
		expect(paths).toEqual(expect.arrayContaining([
			'/v1/account-imports/web-import-gemini/confirm',
			'/v1/account-imports/web-import-gemini/scan',
			'/v1/account-imports/web-import-gemini/compress',
			'/v1/account-imports/web-import-gemini/persist-encrypted',
			'/v1/account-imports/web-import-gemini/complete',
		]));
		const persistBody = persistPayloads(calls)[0] as { chats: Array<{ messages: Array<Record<string, unknown>> }> };
		const assistant = persistBody.chats[0].messages.find((message) => message.role === 'assistant');
		expect(assistant).toHaveProperty('encrypted_sender_name');
		expect(assistant).toHaveProperty('encrypted_category');
		expect(assistant).toHaveProperty('encrypted_model_name');
		expect(assistant).not.toHaveProperty('avatar_key');
		expect(JSON.stringify(persistBody)).not.toContain('Synthetic generic web import');
		expect(JSON.stringify(persistBody)).not.toContain('Synthetic sanitized compression summary');
		writePersistArtifacts(testInfo, calls, 'account-import-gemini-persist.json');
	});
});
