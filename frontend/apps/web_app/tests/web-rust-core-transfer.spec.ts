/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Opt-in shared Rust core (WASM) — Account Import V1 parsing on the shared
 * Worker `transfer` unit, VITE_OPENMATES_RUST_CORE=1 build.
 *
 * Engineering migration check (web lane: import/export). For each supported
 * export (Claude JSON, ChatGPT ZIP, OpenCode JSON, OpenMates Export V1 ZIP and a
 * generic role/content transcript) alternating reloads parse the same file on
 * the TypeScript parser (measurement opt-out `openmates_rust_core_transfer=ts`)
 * and on the Rust unit. Both arms must send an identical import preview (source,
 * parser, chat count, source fingerprints, token estimates and the byte size of
 * the parsed chats), and the Rust arm must route through the unit with exactly
 * one shared Worker, one WASM instance and none on the page. A full Claude
 * import then runs on the Rust arm through scan and encrypted persistence.
 * Runs only in the CI lane that builds the Rust core package (web-rust-core-* specs).
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { rustCoreInstances } = require('./helpers/rust-core-instances');
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
const TRANSFER_OPT_OUT_KEY = 'openmates_rust_core_transfer';

const FORMATS: Array<{ name: string; source: string; upload: (page: any) => Promise<void> }> = [
	{ name: 'claude-json', source: 'claude', upload: (page) => uploadClaudeJson(page, 3) },
	{ name: 'chatgpt-zip', source: 'chatgpt', upload: uploadChatGPTZip },
	{ name: 'opencode-json', source: 'opencode', upload: uploadOpenCodeJson },
	{ name: 'openmates-zip', source: 'openmates', upload: uploadOpenMatesZip },
	{ name: 'generic-json', source: 'other', upload: uploadGenericJson },
];

async function openImport(page: any, arm: 'ts' | 'rust'): Promise<void> {
	await page.evaluate(([key, ts]: [string, boolean]) => { if (ts) localStorage.setItem(key, 'ts'); else localStorage.removeItem(key); },
		[TRANSFER_OPT_OUT_KEY, arm === 'ts']);
	// Fresh realm per arm: the parser choice and the unit client are per page load.
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

// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,sdk.web.before-after-performance
test('account import parses every export format identically on the shared Rust transfer unit', async ({ page }: { page: any }, testInfo: any) => {
	test.slow();
	test.setTimeout(420000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	const calls = await installAccountImportMock(page, { importId: 'web-rust-transfer-preview', maxBatchCount: 5, defaultSelectionCount: 5 });
	await loginToTestAccount(page, () => undefined, async () => undefined, {
		credentials: { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY },
	});

	const report: Record<string, unknown> = {};
	for (const format of FORMATS) {
		const bodies: Record<string, unknown> = {};
		for (const arm of ['ts', 'rust'] as const) {
			await openImport(page, arm);
			bodies[arm] = await previewBody(page, calls, format);
			const stats = await page.evaluate(() => (window as any).__openmatesRustTransferStats?.() ?? null);
			if (arm === 'rust') {
				expect(stats, `${format.name}: Rust arm loaded the transfer unit client`).not.toBeNull();
				expect(stats.calls, `${format.name}: Rust arm parsed through the transfer unit`).toBeGreaterThanOrEqual(2);
				expect(stats.failures, `${format.name}: no transfer unit call failed`).toBe(0);
				const instances = await rustCoreInstances(page);
				expect(instances.wasmMainThreadInstantiations, 'no WASM on the page realm').toBe(0);
				expect(instances.workers.filter((worker: { name: string }) => worker.name === 'shared.worker').length, 'one shared Rust core Worker').toBe(1);
				expect(instances.rustWorkers, 'no other Rust core Worker').toBe(1);
				expect(instances.sharedWorkerWasm, 'one WASM instance in the shared Worker').toBe(1);
			} else {
				expect(stats, `${format.name}: TS arm never loaded the Rust transfer adapter`).toBeNull();
			}
		}
		expect(bodies.rust, `${format.name}: Rust preview equals the TypeScript preview`).toEqual(bodies.ts);
		report[format.name] = bodies.rust;
	}
	await testInfo.attach('transfer-preview-parity.json', { body: JSON.stringify(report, null, 2), contentType: 'application/json' });
	await page.evaluate((key: string) => localStorage.removeItem(key), TRANSFER_OPT_OUT_KEY);
});

// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
test('Rust-parsed Claude import completes scan and encrypted persistence', async ({ page }: { page: any }) => {
	test.setTimeout(240000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	const calls = await installAccountImportMock(page, { importId: 'web-rust-transfer-claude' });
	await loginToTestAccount(page, () => undefined, async () => undefined, {
		credentials: { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY },
	});
	await openImport(page, 'rust');
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
