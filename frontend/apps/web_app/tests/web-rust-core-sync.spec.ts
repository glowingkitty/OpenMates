/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Opt-in shared Rust core (WASM) — web chat-sync decision policy on the shared
 * Worker `sync` unit, VITE_OPENMATES_RUST_CORE=1 build.
 *
 * Engineering migration check (web lane: sync policy). A logged-in account sends
 * one message (new chat), then alternating reloads run phased sync on the
 * TypeScript policy (measurement opt-out `openmates_rust_core_sync=ts`) and on
 * the Rust unit. Every reload must list the chat in the sidebar and render the
 * decrypted user and assistant messages (existing chats keep decrypting and
 * syncing). The Rust arm must route its sync decisions (merge, key admission)
 * through the unit with zero failures, one shared Worker and no WASM on the
 * page; the TS arm must never load the adapter. Records reload -> rendered chat
 * latency per arm (paired medians, approved not-noticeable budget, soft gate).
 * Runs only in the CI lane that builds the Rust core package (web-rust-core-* specs).
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { createSignupLogger, createStepScreenshotter, getTestAccount, getE2EDebugUrl, withMockMarker } = require('./signup-flow-helpers');
const { loginToTestAccount, sendMessage, deleteActiveChat, setChatSidebarOpen } = require('./helpers/chat-test-helpers');
const { rustCoreInstances } = require('./helpers/rust-core-instances');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const SYNC_OPT_OUT_KEY = 'openmates_rust_core_sync';
const PAIRS = 3;

async function reloadAndRender(page: any, chatId: string): Promise<number> {
	await page.goto(getE2EDebugUrl(`/#chat-id=${chatId}`));
	const started = Date.now();
	await page.reload({ waitUntil: 'domcontentloaded' });
	for (const role of ['message-user', 'message-assistant']) {
		await expect(page.getByTestId(role).first().getByTestId('message-content')).not.toBeEmpty({ timeout: 60000 });
	}
	return Date.now() - started;
}

// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,chats.persistence.client-encrypted,sdk.web.before-after-performance
test('phased sync decisions run on the shared Rust sync unit and existing chats still sync and decrypt', async ({ page }: { page: any }, testInfo: any) => {
	test.slow();
	test.setTimeout(420000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	const log = createSignupLogger('WEB_RUST_CORE_SYNC');
	const screenshot = createStepScreenshotter(log);
	const syncErrors: string[] = [];
	page.on('console', (msg: any) => {
		const text = msg.text();
		if (/\[ChatSyncService\].*(Error|Failed)|sync_merge_unsettled|UnitPortError/.test(text)) syncErrors.push(text.slice(0, 300));
	});
	await page.goto(getE2EDebugUrl('/'));
	await loginToTestAccount(page, log, screenshot);
	await sendMessage(page, withMockMarker('Please explain how photosynthesis works in detail.', 'chat_flow_capital', 'fast'), log, screenshot, 'sync-send');
	const chatIdOf = () => page.url().match(/chat-id=([a-f0-9-]{36})/)?.[1] ?? null;
	await expect.poll(chatIdOf, { timeout: 30000 }).not.toBeNull();
	const chatId: string = chatIdOf()!;
	await expect(page.getByTestId('message-assistant').first().getByTestId('message-content')).not.toBeEmpty({ timeout: 90000 });

	const samples: Record<'ts' | 'rust', Record<string, unknown>[]> = { ts: [], rust: [] };
	try {
		for (let i = 0; i < PAIRS * 2; i++) {
			const path = i % 2 === 0 ? 'ts' : 'rust';
			await page.evaluate(([key, ts]: [string, boolean]) => { if (ts) localStorage.setItem(key, 'ts'); else localStorage.removeItem(key); },
				[SYNC_OPT_OUT_KEY, path === 'ts']);
			const renderMs = await reloadAndRender(page, chatId);
			await setChatSidebarOpen(page, true);
			await expect(page.getByTestId('chat-item-wrapper').first())
				.toBeVisible({ timeout: 30000 });
			const readStats = () => page.evaluate(() => (window as any).__openmatesRustSyncStats?.() ?? null);
			if (path === 'rust') {
				await expect.poll(async () => (await readStats())?.calls ?? 0, { timeout: 45000 }).toBeGreaterThan(0);
			}
			const stats = await readStats();
			if (path === 'rust') {
				const decisions = (stats.ops.merge ?? 0) + (stats.ops.admission ?? 0) + (stats.ops.messageKeyPlan ?? 0);
				expect(decisions, 'Rust arm routed sync decisions (merge/admission/message keys) through the unit').toBeGreaterThan(0);
				expect(stats.failures, 'no sync unit call failed').toBe(0);
			} else {
				expect(stats, 'TS arm never loaded the Rust sync adapter').toBeNull();
			}
			const instances = await rustCoreInstances(page);
			expect(instances.wasmMainThreadInstantiations, `${path}: no WASM on the page realm`).toBe(0);
			expect(instances.workers.filter((worker: { name: string }) => worker.name === 'shared.worker').length, `${path}: one shared Rust core Worker`).toBe(1);
			samples[path].push({ renderMs, stats, ...instances });
		}
		expect(syncErrors, 'no chat-sync errors in either arm').toEqual([]);
	} finally {
		await page.evaluate((key: string) => localStorage.removeItem(key), SYNC_OPT_OUT_KEY);
		await deleteActiveChat(page, log, screenshot, 'sync-cleanup');
	}
	const median = (values: number[]) => [...values].sort((a, b) => a - b)[Math.floor(values.length / 2)];
	const rust = median(samples.rust.map((row) => Number(row.renderMs)));
	const ts = median(samples.ts.map((row) => Number(row.renderMs)));
	const limit = Math.max(ts * 1.1, ts + 50);
	const metrics = { pairs: PAIRS, rustMedianMs: rust, tsMedianMs: ts, verdict: rust <= limit ? 'rust_not_worse' : 'rust_worse', samples };
	console.log(`[web-rust-core-sync] ${JSON.stringify({ rustMedianMs: rust, tsMedianMs: ts, verdict: metrics.verdict })}`);
	await testInfo.attach('sync-reload-latency.json', { body: JSON.stringify(metrics, null, 2), contentType: 'application/json' });
	expect.soft(rust, `reload-to-rendered chat: Rust ${rust} ms vs TS ${ts} ms`).toBeLessThanOrEqual(limit);
});
