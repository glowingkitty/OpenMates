/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Shared Rust core (WASM) — Account Import V1 parsing, chat export and account
 * export on the shared Worker `transfer` unit (the only transfer path).
 *
 * Engineering check (web lane: import/export). For each supported export
 * (Claude JSON, ChatGPT ZIP, OpenCode JSON, OpenMates Export V1 ZIP and a
 * generic role/content transcript) the file is parsed on the Rust unit; the
 * import preview must carry the expected source and chat count, and the page
 * must route through the unit with exactly one shared Worker, one WASM instance
 * and none on the page. A full Claude import then runs through scan and
 * encrypted persistence.
 *
 * Chat export (web_transfer_export.rs): a real chat is downloaded from the sidebar
 * context menu; the zip (planned by web_transfer_zip.rs) must hold the metadata,
 * Markdown and YAML entries with the sent message.
 *
 * Account export (web_transfer_account_export.rs): the Account Export V1 archive is
 * downloaded from a mocked job and must hold every expected entry.
 * Runs only in the CI lane that builds the Rust core package (web-rust-core-* specs).
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { loginToTestAccount, sendMessage, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { createSignupLogger, createStepScreenshotter, withMockMarker } = require('./signup-flow-helpers');
const { rustCoreInstances } = require('./helpers/rust-core-instances');
const { installAccountExportMock } = require('./helpers/account-export-mock');
const { inflateRawSync } = require('node:zlib');
const {
	installAccountImportMock,
	openImportSettings,
	persistPayloads,
	selectImportSource,
	uploadChatGPTZip,
	uploadClaudeJson,
	uploadGenericJson,
	uploadOpenCodeJson,
	uploadOpenMatesZip,
} = require('./helpers/account-import-test-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

const FORMATS: Array<{ name: string; source: string; upload: (page: any) => Promise<void> }> = [
	{ name: 'claude-json', source: 'claude', upload: (page) => uploadClaudeJson(page, 3) },
	{ name: 'chatgpt-zip', source: 'chatgpt', upload: uploadChatGPTZip },
	{ name: 'opencode-json', source: 'opencode', upload: uploadOpenCodeJson },
	{ name: 'openmates-zip', source: 'openmates', upload: uploadOpenMatesZip },
	{ name: 'generic-json', source: 'other', upload: uploadGenericJson },
];

async function openImport(page: any): Promise<void> {
	// Fresh realm per format: the unit client is per page load.
	// Navigating to the app root (not reload) drops any settings deep link so the
	// profile menu opens closed and the import tab is reached from a clean state.
	await page.goto('/', { waitUntil: 'domcontentloaded' });
	await expect(page.getByTestId('profile-container')).toBeVisible({ timeout: 30000 });
	await openImportSettings(page);
}

async function previewBody(page: any, calls: Array<{ path: string; body: Record<string, unknown> | null }>, format: (typeof FORMATS)[number]) {
	const before = calls.filter((call) => call.path === '/v1/account-imports/preview').length;
	await selectImportSource(page, format.source);
	await format.upload(page);
	await expect(page.getByTestId('import-preview-summary')).toContainText('Chats found', { timeout: 30000 });
	const previews = calls.filter((call) => call.path === '/v1/account-imports/preview');
	expect(previews.length, `${format.name}: one preview per parse`).toBe(before + 1);
	return previews[previews.length - 1].body;
}

// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
test('account import parses every export format on the shared Rust transfer unit', async ({ page }: { page: any }, testInfo: any) => {
	test.slow();
	test.setTimeout(420000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	const calls = await installAccountImportMock(page, { importId: 'web-rust-transfer-preview', maxBatchCount: 5, defaultSelectionCount: 5 });
	await loginToTestAccount(page, () => undefined, async () => undefined, {
		credentials: { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY },
	});

	const report: Record<string, unknown> = {};
	for (const format of FORMATS) {
		await openImport(page);
		const body = await previewBody(page, calls, format);
		expect(body, `${format.name}: the Rust unit sent an import preview`).not.toBeNull();
		const stats = await page.evaluate(() => (window as any).__openmatesRustTransferStats?.() ?? null);
		expect(stats, `${format.name}: Rust loaded the transfer unit client`).not.toBeNull();
		expect(stats.calls, `${format.name}: parsed through the transfer unit`).toBeGreaterThanOrEqual(2);
		expect(stats.failures, `${format.name}: no transfer unit call failed`).toBe(0);
		const instances = await rustCoreInstances(page);
		expect(instances.wasmMainThreadInstantiations, 'no WASM on the page realm').toBe(0);
		expect(instances.workers.filter((worker: { name: string }) => worker.name === 'shared.worker').length, 'one shared Rust core Worker').toBe(1);
		expect(instances.rustWorkers, 'no other Rust core Worker').toBe(1);
		expect(instances.sharedWorkerWasm, 'one WASM instance in the shared Worker').toBe(1);
		report[format.name] = body;
	}
	await testInfo.attach('transfer-preview.json', { body: JSON.stringify(report, null, 2), contentType: 'application/json' });
});

// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
test('Rust-parsed Claude import completes scan and encrypted persistence', async ({ page }: { page: any }) => {
	test.setTimeout(240000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	const calls = await installAccountImportMock(page, { importId: 'web-rust-transfer-claude' });
	await loginToTestAccount(page, () => undefined, async () => undefined, {
		credentials: { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY },
	});
	await openImport(page);
	await selectImportSource(page, 'claude');
	await uploadClaudeJson(page, 1);
	await expect(page.getByTestId('import-preview-summary')).toContainText('Chats found', { timeout: 30000 });
	await page.getByTestId('account-import-start').click();
	await expect(page.getByTestId('import-results-container')).toContainText('3 messages imported', { timeout: 60000 });
	const scanBody = calls.find((call: { path: string }) => call.path.endsWith('/scan'))?.body as { batch_id: string; chats: Array<{ messages: unknown[] }> };
	expect(scanBody.batch_id).toMatch(/^scan-[0-9a-f]{16}-0$/);
	expect(scanBody.chats[0].messages).toHaveLength(3);
	const persistBody = persistPayloads(calls)[0] as { chats: Array<Record<string, unknown>> };
	expect(persistBody.chats).toHaveLength(1);
	expect(JSON.stringify(persistBody)).not.toContain('Synthetic web import user message');
	const stats = await page.evaluate(() => (window as any).__openmatesRustTransferStats?.() ?? null);
	expect(stats.calls, 'parse plus scan batch plan ran on the transfer unit').toBeGreaterThanOrEqual(3);
	expect(stats.failures).toBe(0);
});

/** Text entries of a zip (central directory, stored or deflated); no zip dependency in the browser test profile. */
function readZipEntries(zip: Buffer): Record<string, string> {
	const entries: Record<string, string> = {};
	const end = zip.lastIndexOf(Buffer.from([0x50, 0x4b, 0x05, 0x06]));
	expect(end, 'zip end-of-central-directory record').toBeGreaterThanOrEqual(0);
	let offset = zip.readUInt32LE(end + 16);
	for (let index = zip.readUInt16LE(end + 10); index > 0; index--) {
		expect(zip.readUInt32LE(offset), 'central directory signature').toBe(0x02014b50);
		const method = zip.readUInt16LE(offset + 10);
		const compressedSize = zip.readUInt32LE(offset + 20);
		const nameLength = zip.readUInt16LE(offset + 28);
		const extraLength = zip.readUInt16LE(offset + 30);
		const commentLength = zip.readUInt16LE(offset + 32);
		const localOffset = zip.readUInt32LE(offset + 42);
		const name = zip.subarray(offset + 46, offset + 46 + nameLength).toString('utf8');
		offset += 46 + nameLength + extraLength + commentLength;
		if (name.endsWith('/')) continue;
		const dataStart = localOffset + 30 + zip.readUInt16LE(localOffset + 26) + zip.readUInt16LE(localOffset + 28);
		const data = zip.subarray(dataStart, dataStart + compressedSize);
		expect([0, 8], `zip entry ${name} compression method`).toContain(method);
		entries[name] = (method === 8 ? inflateRawSync(data) : data).toString('utf8');
	}
	return Object.fromEntries(Object.entries(entries).sort(([a], [b]) => (a < b ? -1 : 1)));
}

/** The chat download is a zip (metadata, YAML, Markdown, embeds): returns its name and every text entry. */
async function downloadActiveChat(page: any, chatId: string): Promise<{ filename: string; entries: Record<string, string> }> {
	// Fresh realm: the unit client is per page load.
	await page.goto(`/#chat-id=${chatId}`, { waitUntil: 'domcontentloaded' });
	await page.reload({ waitUntil: 'domcontentloaded' });
	await expect(page.getByTestId('message-user').first()).toBeVisible({ timeout: 60000 });
	const activityHistory = page.getByTestId('activity-history-wrapper');
	if (!(await activityHistory.isVisible({ timeout: 2000 }).catch(() => false))) {
		await page.getByTestId('sidebar-toggle').click({ timeout: 10000 });
		await expect(activityHistory).toBeVisible({ timeout: 10000 });
	}
	const activeChatItem = page.locator('[data-testid="chat-item-wrapper"].active');
	await expect(activeChatItem).toBeVisible({ timeout: 15000 });
	const downloadPromise = page.waitForEvent('download', { timeout: 30000 });
	await activeChatItem.click({ button: 'right' });
	await expect(page.getByTestId('context-menu')).toBeVisible({ timeout: 5000 });
	await page.getByTestId('chat-context-download').click();
	const download = await downloadPromise;
	const stream = await download.createReadStream();
	const chunks: Buffer[] = [];
	for await (const chunk of stream) chunks.push(Buffer.from(chunk));
	const entries = readZipEntries(Buffer.concat(chunks));
	return { filename: download.suggestedFilename(), entries };
}

// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
test('chat download builds the YAML file on the shared Rust transfer unit', async ({ page }: { page: any }, testInfo: any) => {
	test.slow();
	test.setTimeout(420000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	const log = createSignupLogger('RUST_TRANSFER_EXPORT');
	const screenshot = createStepScreenshotter(log);
	await loginToTestAccount(page, log, screenshot);
	await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 30000 });
	await page.waitForTimeout(5000);
	const newChatButton = page.getByTestId('new-chat-button');
	if (await newChatButton.isVisible()) {
		await newChatButton.click();
		await page.waitForTimeout(2000);
	}

	// The saved chat comes from the TS composer; export is the only Rust-owned step here.
	await sendMessage(page, withMockMarker('Please explain how leaves use sunlight in a few words.', 'chat_flow_capital', 'fast'), log, screenshot, 'export-send');
	await expect.poll(() => page.url().match(/chat-id=([a-f0-9-]{36})/)?.[1] ?? null, { timeout: 30000 }).not.toBeNull();
	const chatId = page.url().match(/chat-id=([a-f0-9-]{36})/)![1];
	await expect(page.getByTestId('message-assistant').last()).toBeVisible({ timeout: 60000 });
	await expect(page.getByTestId('typing-indicator')).toHaveCount(0, { timeout: 60000 });
	// Let title generation and the server sync settle so the export sees the final chat state.
	await page.waitForTimeout(8000);

	const exported = await downloadActiveChat(page, chatId);
	const stats = await page.evaluate(() => (window as any).__openmatesRustTransferStats?.() ?? null);
	expect(stats, 'Rust loaded the transfer unit client').not.toBeNull();
	expect(stats.calls, 'filename, YAML and the zip plan were built on the transfer unit').toBeGreaterThanOrEqual(3);
	expect(stats.failures, 'no transfer unit call failed').toBe(0);
	const instances = await rustCoreInstances(page);
	expect(instances.wasmMainThreadInstantiations, 'no WASM on the page realm').toBe(0);
	expect(instances.workers.filter((worker: { name: string }) => worker.name === 'shared.worker').length, 'one shared Rust core Worker').toBe(1);
	expect(instances.sharedWorkerWasm, 'one WASM instance in the shared Worker').toBe(1);

	// Only the export timestamp varies between downloads.
	const withoutExportTime = (text: string) => text.replace(/^ {2}exported_at: .*$/m, '  exported_at: <time>');
	expect(exported.filename, 'download filename is a zip').toMatch(/\.zip$/);
	const names = Object.keys(exported.entries);
	for (const required of ['export-metadata.json']) {
		expect(names, `the zip holds ${required}`).toContain(required);
	}
	const markdownName = names.find((name) => name.endsWith('.md'));
	expect(markdownName, 'the zip holds the chat Markdown').toBeTruthy();
	expect(exported.entries[markdownName!]).toContain('## You - ');
	const yamlName = names.find((name) => name.endsWith('.yml'));
	expect(yamlName, 'the zip holds the chat YAML').toBeTruthy();
	const yaml = exported.entries[yamlName!];
	expect(yaml).toContain('Please explain how leaves use sunlight in a few words.');
	expect(yaml).toMatch(/^chat:\n {2}title: /);
	await testInfo.attach('chat-export.yaml', { body: withoutExportTime(yaml), contentType: 'text/yaml' });

	await deleteActiveChat(page, log, screenshot, 'export-cleanup');
});

/** Downloads the Account Export V1 archive of the mocked job on the Rust unit. */
async function downloadAccountExport(page: any): Promise<{ filename: string; entries: Record<string, string> }> {
	// Fresh realm: the unit client is per page load.
	await page.goto('/', { waitUntil: 'domcontentloaded' });
	await expect(page.getByTestId('profile-container')).toBeVisible({ timeout: 30000 });
	await page.getByTestId('profile-container').click();
	const settingsMenu = page.getByTestId('settings-menu');
	await expect(settingsMenu).toBeVisible({ timeout: 10000 });
	await settingsMenu.getByRole('menuitem', { name: /^account$/i }).click();
	await settingsMenu.getByRole('menuitem', { name: /export/i }).click();
	const exportButton = page.getByRole('button', { name: /export my data/i });
	await expect(exportButton).toBeVisible({ timeout: 15000 });
	await page.getByRole('button', { name: /deselect all/i }).click();
	await page.getByLabel(/all your chats and conversations/i).check();
	await page.getByLabel(/usage history and credit transactions/i).check();
	const downloadPromise = page.waitForEvent('download', { timeout: 120000 });
	await exportButton.click();
	const download = await downloadPromise;
	const chunks: Buffer[] = [];
	for await (const chunk of await download.createReadStream()) chunks.push(Buffer.from(chunk));
	return { filename: download.suggestedFilename(), entries: readZipEntries(Buffer.concat(chunks)) };
}

// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
test('account export builds the archive on the shared Rust transfer unit', async ({ page }: { page: any }, testInfo: any) => {
	test.slow();
	test.setTimeout(300000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	await installAccountExportMock(page, { exportId: 'rust-transfer-export', selectedDomains: ['chats', 'usage'] });
	await loginToTestAccount(page, () => undefined, async () => undefined, {
		credentials: { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY },
	});

	const archive = await downloadAccountExport(page);
	const stats = await page.evaluate(() => (window as any).__openmatesRustTransferStats?.() ?? null);
	expect(stats, 'Rust loaded the transfer unit client').not.toBeNull();
	expect(stats.calls, 'the archive was assembled on the transfer unit').toBeGreaterThanOrEqual(1);
	expect(stats.failures, 'no transfer unit call failed').toBe(0);
	const instances = await rustCoreInstances(page);
	expect(instances.wasmMainThreadInstantiations, 'no WASM on the page realm').toBe(0);
	expect(instances.sharedWorkerWasm, 'one WASM instance in the shared Worker').toBe(1);

	// Only the README export time varies between downloads.
	const withoutExportTime = (text: string) => text.replace(/^Exported at: .*$/m, 'Exported at: <time>');
	const names = Object.keys(archive.entries);
	for (const required of ['README.md', 'manifest.yml', 'manifest.json', 'export-report.yml', 'domains/chats.json', 'domains/usage.json']) {
		expect(names, `the archive holds ${required}`).toContain(required);
	}
	expect(names.some((name) => name.startsWith('chats/') && name.endsWith('.md')), 'per-chat Markdown').toBe(true);
	await testInfo.attach('account-export-report.yml', { body: withoutExportTime(archive.entries['export-report.yml']), contentType: 'text/yaml' });
});
