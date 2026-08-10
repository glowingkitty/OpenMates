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
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
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

async function readRawImportedMessages(page: any, chatId: string): Promise<Array<Record<string, unknown>>> {
	return page.evaluate(async (targetChatId: string) => new Promise((resolve, reject) => {
		const openRequest = indexedDB.open('chats_db');
		openRequest.onerror = () => reject(openRequest.error);
		openRequest.onsuccess = () => {
			const db = openRequest.result;
			const request = db.transaction('messages', 'readonly').objectStore('messages').getAll();
			request.onerror = () => reject(request.error);
			request.onsuccess = () => {
				resolve((request.result as Array<Record<string, unknown>>).filter((message) => message.chat_id === targetChatId));
				db.close();
			};
		};
	}), chatId);
}

async function openImportedChat(page: any, chatId: string): Promise<void> {
	await page.getByTestId('icon-button-close').first().click();
	const sidebarToggle = page.getByTestId('sidebar-toggle');
	if (await sidebarToggle.isVisible({ timeout: 2000 }).catch(() => false)) await sidebarToggle.click();
	const importedChat = page.locator(`[data-testid="chat-item-wrapper"][data-chat-id="${chatId}"]`);
	await expect(importedChat).toBeVisible({ timeout: 15000 });
	await importedChat.click();
}

test.describe('Account Import V1 web flow', () => {
	test('shows explicit import source selection on mobile', async ({ page }: { page: any }, testInfo: any) => {
		test.setTimeout(180000);
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
		await page.setViewportSize({ width: 390, height: 844 });

		const calls = await installAccountImportMock(page, { importId: 'web-import-mobile' });
		await loginToTestAccount(page, () => undefined, async () => undefined, {
			credentials: { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY },
		});
		await page.goto('/#settings/account/import', { waitUntil: 'domcontentloaded' });
		const sourceSelect = page.getByTestId('account-import-source');
		await expect(sourceSelect).toHaveRole('combobox');
		await expect(sourceSelect).toHaveValue('');
		await expect(sourceSelect.getByRole('option', { name: 'OpenMates' })).toBeAttached();
		await expect(sourceSelect.getByRole('option', { name: 'Other' })).toBeAttached();
		await expect(page.getByTestId('account-import-file-upload')).not.toBeVisible();
		await selectImportSource(page, 'other');
		await expect(page.getByTestId('account-import-source-description')).toContainText('Generic role/content JSON');
		await expect(page.getByTestId('account-import-file-upload')).toBeVisible();
		await page.screenshot({ path: testInfo.outputPath('mobile-source-selection.png'), fullPage: true });
		await uploadGenericJson(page);
		await page.getByTestId('account-import-start').click();
		await expect(page.getByTestId('import-results-container')).toContainText('2 messages imported', { timeout: 30000 });
		const persistBody = persistPayloads(calls)[0] as { chats: Array<Record<string, unknown>> };
		await page.goto(`/#chat-id=${String(persistBody.chats[0].chat_id)}`, { waitUntil: 'domcontentloaded' });
		await page.reload({ waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('chat-mate-name').filter({ hasText: 'AI assistant' })).toBeVisible();
		await expect(page.getByTestId('imported-provider-profile')).toHaveAttribute('data-provider-category', 'other');
		const mobileHeaderTitle = page.getByTestId('chat-header-title');
		expect(await mobileHeaderTitle.textContent()).not.toContain('Untitled chat');
		await expect(mobileHeaderTitle).toContainText('Synthetic generic web import chat');
		await page.screenshot({ path: testInfo.outputPath('mobile-other-provider.png'), fullPage: true });
	});

	test('imports Claude JSON through scan and encrypted persistence', async ({ page }: { page: any }, testInfo: any) => {
		test.setTimeout(180000);
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

		const calls = await installAccountImportMock(page, {
			importId: 'web-import-claude',
			promptInjectionRedaction: {
				exact: 'Synthetic web import user message 1',
				replacement: '[Prompt injection removed]',
			},
		});
		await loginAndOpenImportSettings(page, { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY });
		await expect(page.getByTestId('account-import-file-upload')).not.toBeVisible();
		await selectImportSource(page, 'claude');
		await uploadClaudeJson(page, 1);

		await expect(page.getByTestId('import-preview-summary')).toContainText('Chats found');
		await expect(page.getByTestId('import-preview-summary')).toContainText('1');
		await page.getByTestId('account-import-start').click();
		await expect(page.getByTestId('import-results-container')).toContainText('3 messages imported', { timeout: 30000 });

		const paths = calls.map((call: { path: string }) => call.path);
		expect(paths).toContain('/v1/account-imports/preview');
		expect(paths).toContain('/v1/account-imports/web-import-claude/confirm');
		expect(paths).toContain('/v1/account-imports/web-import-claude/status');
		expect(paths).toContain('/v1/account-imports/web-import-claude/scan');
		expect(paths).toContain('/v1/account-imports/web-import-claude/compress');
		expect(paths).toContain('/v1/account-imports/web-import-claude/persist-encrypted');
		expect(paths).toContain('/v1/account-imports/web-import-claude/complete');

		const persistBody = persistPayloads(calls)[0] as { chats: Array<Record<string, unknown>> };
		const scanBody = calls.find((call: { path: string }) => call.path.endsWith('/scan'))?.body as {
			chats: Array<{ messages: Array<{ role: string; content: string }> }>;
		};
		expect(scanBody.chats[0].messages).toEqual(expect.arrayContaining([
			expect.objectContaining({ role: 'system', content: 'Synthetic imported system message' }),
			expect.objectContaining({ role: 'user', content: 'Synthetic web import user message 1' }),
		]));
		expect(persistBody.chats).toHaveLength(1);
		expect(JSON.stringify(persistBody)).not.toContain('Synthetic web import user message');
		expect(JSON.stringify(persistBody)).not.toContain('[Prompt injection removed]');
		expect(JSON.stringify(persistBody)).not.toContain('Synthetic imported system message');
		expect(JSON.stringify(persistBody)).not.toContain('Claude import chat 1');
		expect(persistBody.chats[0]).not.toHaveProperty('title');
		const importedChatId = String(persistBody.chats[0].chat_id);
		await openImportedChat(page, importedChatId);
		await expect(page.getByTestId('chat-header-title')).toContainText('Claude import chat 1');
		await expect(page.getByText('[Prompt injection removed]', { exact: true })).toBeVisible();
		await expect(page.getByText('Synthetic web import user message 1', { exact: true })).toHaveCount(0);
		writePersistArtifacts(testInfo, calls, 'account-import-claude-persist.json');
	});

	test('fails closed when scanner infrastructure fails', async ({ page }: { page: any }) => {
		test.setTimeout(180000);
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

		const calls = await installAccountImportMock(page, {
			importId: 'web-import-scanner-failure',
			scanFailures: [{ source_chat_id: 'claude-chat-1', reason: 'scanner_unavailable', retryable: true }],
		});
		await loginAndOpenImportSettings(page, { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY });
		await selectImportSource(page, 'claude');
		await uploadClaudeJson(page, 1);
		await page.getByTestId('account-import-start').click();
		await expect(page.getByText(/Import scan failed for one or more selected chats/i)).toBeVisible({ timeout: 30000 });

		const paths = calls.map((call: { path: string }) => call.path);
		expect(paths.some((path: string) => path.endsWith('/persist-encrypted'))).toBe(false);
		const completion = calls.find((call: { path: string }) => call.path.endsWith('/complete'));
		expect(completion?.body?.imported_chat_ids).toEqual([]);
		expect(completion?.body?.client_failures).toEqual([
			expect.objectContaining({ reason: 'scanner_unavailable', retryable: true }),
		]);
		await expect(page.getByTestId('import-results-container')).toHaveCount(0);
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

		const calls = await installAccountImportMock(page, { importId: 'web-import-gemini', compressionSummary: 'Synthetic sanitized compression summary' });
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
		const compressionSummary = persistBody.chats[0].messages.find((message) => message.role === 'system');
		expect(assistant).toHaveProperty('encrypted_sender_name');
		expect(assistant).toHaveProperty('encrypted_category');
		expect(assistant).toHaveProperty('encrypted_model_name');
		expect(assistant).not.toHaveProperty('avatar_key');
		expect(compressionSummary).toMatchObject({
			role: 'system',
			encrypted_content: expect.any(String),
			encrypted_category: expect.any(String),
		});
		expect(compressionSummary).not.toHaveProperty('content');
		expect(compressionSummary).not.toHaveProperty('category');
		expect(JSON.stringify(persistBody)).not.toContain('Synthetic generic web import');
		expect(JSON.stringify(persistBody)).not.toContain('Synthetic sanitized compression summary');
		expect(JSON.stringify(persistBody)).not.toContain('compression_summary');
		const importedChatId = String((persistBody.chats[0] as Record<string, unknown>).chat_id);
		await openImportedChat(page, importedChatId);
		await expect(page.getByTestId('chat-header-title')).toContainText('Synthetic generic web import chat');
		await expect(page.getByTestId('show-forgotten-messages')).toBeVisible({ timeout: 15000 });
		await page.getByTestId('show-forgotten-messages').click();
		await expect(page.getByTestId('show-forgotten-messages')).toHaveCount(1);
		await expect(page.getByTestId('hide-forgotten-messages-at-boundary')).toHaveCount(0);
		await expect(page.getByTestId('chat-mate-name').filter({ hasText: 'Gemini' })).toBeVisible();
		await expect(page.getByTestId('imported-provider-profile')).toHaveAttribute('data-provider-category', 'gemini');
		const rawMessages = await readRawImportedMessages(page, importedChatId);
		const rawSummary = rawMessages.find((message) => message.role === 'system');
		expect(rawSummary).toMatchObject({ encrypted_content: expect.any(String), encrypted_category: expect.any(String) });
		expect(rawSummary).not.toHaveProperty('content');
		expect(rawSummary).not.toHaveProperty('category');
		expect(JSON.stringify(rawMessages)).not.toContain('Synthetic sanitized compression summary');
		expect(JSON.stringify(rawMessages)).not.toContain('compression_summary');
		await page.screenshot({ path: testInfo.outputPath('compression-history-expanded.png'), fullPage: true });
		writePersistArtifacts(testInfo, calls, 'account-import-gemini-persist.json');
	});

	test('renders Other imports as a generic AI assistant rather than a mate', async ({ page }: { page: any }) => {
		test.setTimeout(180000);
		skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);

		const calls = await installAccountImportMock(page, { importId: 'web-import-other' });
		await loginAndOpenImportSettings(page, { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY });
		await selectImportSource(page, 'other');
		await uploadGenericJson(page);
		await page.getByTestId('account-import-start').click();
		await expect(page.getByTestId('import-results-container')).toContainText('2 messages imported', { timeout: 30000 });
		const persistBody = persistPayloads(calls)[0] as { chats: Array<Record<string, unknown>> };
		await openImportedChat(page, String(persistBody.chats[0].chat_id));
		await expect(page.getByTestId('chat-mate-name').filter({ hasText: 'AI assistant' })).toBeVisible();
		await expect(page.getByTestId('imported-provider-profile')).toHaveAttribute('data-provider-category', 'other');
		const headerTitle = page.getByTestId('chat-header-title');
		expect(await headerTitle.textContent()).not.toContain('Untitled chat');
		await expect(headerTitle).toContainText('Synthetic generic web import chat');
		await expect(page.getByTestId('mate-profile')).toHaveCount(0);
	});
});
