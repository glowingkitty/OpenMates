/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Opt-in shared Rust core (WASM) — IndexedDB message-row policy on the shared
 * Worker `persist` unit, VITE_OPENMATES_RUST_CORE=1 build.
 *
 * Engineering migration check (web lane: persistence). A logged-in account sends
 * one message (new chat: placeholder rows, status upgrades and the confirmed save
 * all run through the `messages` store write policy), then alternating reloads
 * re-sync the chat on the TypeScript policy (measurement opt-out
 * `openmates_rust_core_persist=ts`) and on the Rust unit. Existing stored rows
 * must keep reading unchanged: every reload renders the decrypted user and
 * assistant messages. The Rust arm must route the save/duplicate decisions
 * through the unit with zero failures, one shared Worker and no WASM on the page;
 * the TS arm must never load the adapter. IndexedDB stays the store.
 * Runs only in the CI lane that builds the Rust core package (web-rust-core-* specs).
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { createSignupLogger, createStepScreenshotter, getTestAccount, getE2EDebugUrl, withMockMarker } = require('./signup-flow-helpers');
const { loginToTestAccount, sendMessage, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { rustCoreInstances } = require('./helpers/rust-core-instances');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const PERSIST_OPT_OUT_KEY = 'openmates_rust_core_persist';
const RELOADS = 4;

async function reloadAndRender(page: any, chatId: string): Promise<void> {
	await page.goto(getE2EDebugUrl(`/#chat-id=${chatId}`));
	await page.reload({ waitUntil: 'domcontentloaded' });
	for (const role of ['message-user', 'message-assistant']) {
		await expect(page.getByTestId(role).first().getByTestId('message-content')).not.toBeEmpty({ timeout: 60000 });
	}
}

// contract-test: supporting surface=gui.web assertions=storage.client.shared-policy-existing-adapters,chats.persistence.client-encrypted
test('message row decisions run on the shared Rust persist unit and stored chats still read unchanged', async ({ page }: { page: any }) => {
	test.slow();
	test.setTimeout(420000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	const log = createSignupLogger('WEB_RUST_CORE_PERSIST');
	const screenshot = createStepScreenshotter(log);
	const persistErrors: string[] = [];
	page.on('console', (msg: any) => {
		const text = msg.text();
		if (/\[ChatDatabase\].*(Error|Failed)|UnitPortError/.test(text)) persistErrors.push(text.slice(0, 300));
	});
	await page.goto(getE2EDebugUrl('/'));
	await loginToTestAccount(page, log, screenshot);
	await sendMessage(page, withMockMarker('Please explain how photosynthesis works in detail.', 'chat_flow_capital', 'fast'), log, screenshot, 'persist-send');
	const chatIdOf = () => page.url().match(/chat-id=([a-f0-9-]{36})/)?.[1] ?? null;
	await expect.poll(chatIdOf, { timeout: 30000 }).not.toBeNull();
	const chatId: string = chatIdOf()!;
	await expect(page.getByTestId('message-assistant').first().getByTestId('message-content')).not.toBeEmpty({ timeout: 90000 });
	const sendStats = await page.evaluate(() => (window as any).__openmatesRustPersistStats?.() ?? null);
	expect(sendStats, 'the first (flag-on) send routed message save decisions through the unit').not.toBeNull();
	expect(sendStats.failures, 'no persist unit call failed while sending').toBe(0);
	expect(Object.keys(sendStats.ops), 'the new chat row defaults were decided by the unit').toContain('chatDefaults');

	try {
		for (let i = 0; i < RELOADS; i++) {
			const path = i % 2 === 0 ? 'ts' : 'rust';
			await page.evaluate(([key, ts]: [string, boolean]) => { if (ts) localStorage.setItem(key, 'ts'); else localStorage.removeItem(key); },
				[PERSIST_OPT_OUT_KEY, path === 'ts']);
			await reloadAndRender(page, chatId);
			const stats = await page.evaluate(() => (window as any).__openmatesRustPersistStats?.() ?? null);
			if (path === 'rust') {
				// A reload of an unchanged chat may legitimately make no row decisions,
				// so the client can stay unloaded; any call that did run must not fail.
				expect(stats?.failures ?? 0, 'no persist unit call failed').toBe(0);
				// K3: the reloaded page bulk-loads chat keys from IndexedDB; batch plan decided by Rust.
				await expect.poll(() => page.evaluate(() => (window as any).__openmatesRustCryptoStats?.()?.calls?.keysBulkBatches ?? 0),
					{ message: 'bulk chat-key load batch plan decided by Rust (K3)', timeout: 30000 }).toBeGreaterThan(0);
			} else {
				expect(stats, 'TS arm never loaded the Rust persist adapter').toBeNull();
			}
			const instances = await rustCoreInstances(page);
			expect(instances.wasmMainThreadInstantiations, `${path}: no WASM on the page realm`).toBe(0);
			expect(instances.workers.filter((worker: { name: string }) => worker.name === 'shared.worker').length, `${path}: one shared Rust core Worker`).toBe(1);
			expect(instances.sharedWorkerWasm, `${path}: one WASM instance in the shared Worker`).toBe(1);
		}
		expect(persistErrors, 'no ChatDatabase errors in either arm').toEqual([]);
	} finally {
		await page.evaluate((key: string) => localStorage.removeItem(key), PERSIST_OPT_OUT_KEY);
		await deleteActiveChat(page, log, screenshot, 'persist-cleanup');
	}
});
