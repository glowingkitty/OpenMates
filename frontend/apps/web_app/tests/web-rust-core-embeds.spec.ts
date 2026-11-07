/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Opt-in shared Rust core (WASM) — saved embeds behind Rust history, VITE_OPENMATES_RUST_CORE=1 build.
 *
 * Engineering migration check (web lane: history/admission). A code embed chat is
 * seeded through the normal send (CI mock replay). After reload the normal chat UI
 * (ActiveChat, Rust-decrypted history) shows the chat; the embed preview must
 * finish, the shared fullscreen must open from it and closing it must return to
 * the chat. Rust reloads must open the stored embed rows in the shared Worker
 * (embed keys resolved there by Rust, `embedWrite` unit; row counters, no
 * failures) and decode their TOON content with the Rust parser (`embedData`
 * unit); the other arms never use either. The seeding send streams the code embed
 * through the Rust `embedWrite` unit (streamed write counter).
 * Records embed ready time, browser CPU and memory over three alternating
 * pure-TS / Rust reload pairs: TS reloads opt out of Rust history AND the Rust
 * crypto unit; Rust reloads route both through the one shared Worker. Gated
 * (medians, approved migration budget): embed ready wall time, browser CPU and RSS. A third,
 * recorded arm (Rust history, TS crypto) separates the crypto unit's share.
 * Runs only in the CI lane that builds the Rust core package (web-rust-core-* specs).
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { createSignupLogger, createStepScreenshotter, getTestAccount, getE2EDebugUrl } = require('./signup-flow-helpers');
const { openFullscreen, closeFullscreen } = require('./helpers/embed-test-helpers');
const { seedCodeEmbedChat, measureEmbedReady } = require('./helpers/embed-ready-metrics');
const { rustCoreInstances } = require('./helpers/rust-core-instances');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
/** Measurement-only opt-out of the Rust history source (rustChatHistoryBootstrap.ts). */
const HISTORY_OPT_OUT_KEY = 'openmates_rust_core_history';
/** Measurement-only opt-out of the Rust crypto unit (webCryptoRegistration.ts). */
const CRYPTO_OPT_OUT_KEY = 'openmates_rust_core_crypto';
const OPT_OUT_KEYS = [HISTORY_OPT_OUT_KEY, CRYPTO_OPT_OUT_KEY];

/**
 * Approved "not noticeable" migration budget (.claude/rules/cli-sdk.md, user decision 2026-11-06):
 * wall time <= max(+10%, +50 ms), CPU <= +15%, memory <= TS + 30 MB (one shared WASM instance).
 */
function budgetLimit(key: string, ts: number): number {
	if (key === 'browserCpuMs') return ts * 1.15;
	if (key === 'browserRssBytes') return ts + 30 * 1024 * 1024;
	return Math.max(ts * 1.1, ts + 50);
}

// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,apps.results.shared-fullscreen,sdk.web.before-after-performance
let consoleForFailure: string[] = [];
test.afterEach(async ({ page }: { page: any }, testInfo: any) => {
	if (testInfo.status !== testInfo.expectedStatus) {
		console.log('--- failure url ---\n' + page.url());
		console.log('--- browser console (errors/warnings/send/rust, last 150) ---\n'
			+ consoleForFailure.filter((line) => /error|warn|fail|send|rust|draft/i.test(line)).slice(-150).join('\n'));
	}
});

test('Rust core decrypts saved embeds; preview renders and fullscreen opens', async ({ page }: { page: any }, testInfo: any) => {
	test.slow();
	test.setTimeout(300000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	const log = createSignupLogger('WEB_RUST_CORE_EMBEDS');
	const screenshot = createStepScreenshotter(log);
	const consoleLines: string[] = [];
	consoleForFailure = consoleLines;
	page.on('console', (msg: any) => { consoleLines.push(`[${msg.type()}] ${msg.text()}`.slice(0, 400)); });
	page.on('pageerror', (error: Error) => { consoleLines.push(`[pageerror] ${error.message}`.slice(0, 400)); });

	const chatId = await seedCodeEmbedChat(page, log, screenshot);
	// The finalized streamed code embed was chosen, encrypted and stored by the Rust embedWrite unit.
	await expect.poll(() => page.evaluate(() => (window as any).__openmatesRustEmbedStats?.()?.streamedWrites ?? 0),
		{ message: 'streamed embed written by the Rust embedWrite unit', timeout: 30000 }).toBeGreaterThan(0);
	// The embed status gate of the AI-stream handlers ran its decision in the Rust embedData unit.
	await expect.poll(() => page.evaluate(() => (window as any).__openmatesRustEmbedStats?.()?.admissions ?? 0),
		{ message: 'embed event admitted by the Rust embedData unit', timeout: 30000 }).toBeGreaterThan(0);

	await page.goto(getE2EDebugUrl(`/#chat-id=${chatId}`));
	await page.reload();
	const preview = page.locator('[data-testid="message-assistant"] [data-testid="embed-preview"][data-app-id="code"][data-status="finished"]').first();
	await expect(preview, 'saved code embed preview renders after reload').toBeVisible({ timeout: 60000 });
	await expect.poll(() => page.evaluate(() => document.documentElement.dataset.rustCoreHistory ?? null),
		{ message: 'Rust supplied the reopened chat history' }).toMatch(/^rust:\d+$/);
	await screenshot(page, 'rust-embed-preview');

	const overlay = await openFullscreen(page, preview);
	await expect(overlay).toBeVisible();
	await expect(page.getByTestId('embed-fullscreen-container').first()).toBeVisible();
	await screenshot(page, 'rust-embed-fullscreen');
	await closeFullscreen(page, overlay);
	await expect(preview, 'chat returns after fullscreen closes').toBeVisible({ timeout: 15000 });

	// Alternate pure-TS (both measurement opt-outs) and Rust reloads of the same saved
	// chat in this build, so the medians share one runner and page. The recorded
	// `history` arm (Rust history, TS crypto) attributes the crypto unit's own share.
	const samples: Record<'ts' | 'rust' | 'history', Record<string, any>[]> = { ts: [], rust: [], history: [] };
	for (const path of ['ts', 'rust', 'history', 'ts', 'rust', 'history', 'ts', 'rust', 'history'] as const) {
		await page.evaluate(([path, history, crypto]: [string, string, string]) => {
			if (path === 'ts') localStorage.setItem(history, 'ts'); else localStorage.removeItem(history);
			if (path === 'rust') localStorage.removeItem(crypto); else localStorage.setItem(crypto, 'ts');
		}, [path, HISTORY_OPT_OUT_KEY, CRYPTO_OPT_OUT_KEY]);
		const sample = (await measureEmbedReady(page, chatId, '[data-testid="message-assistant"]', 1) as any).samples[0];
		expect('rust:history-request' in sample.rustStages, `${path} reload ${path === 'ts' ? 'did not use' : 'used'} Rust history`).toBe(path !== 'ts');
		// Shared-Worker bench counters for this reload.
		Object.assign(sample, await rustCoreInstances(page));
		expect(sample.wasmMainThreadInstantiations, `${path}: no WASM on the page realm`).toBe(0);
		// Every arm (Rust auth restores the session in each, web-rust-core-chat.spec.ts):
		// one shared Rust core Worker holding the tab's single WASM instance.
		expect(sample.sharedWorkerWasm, `${path}: the shared Worker holds the WASM instance`).toBe(1);
		expect(sample.wasmInstantiations, `${path}: one WASM instance in the tab`).toBe(1);
		const workers = sample.workers as { name: string; wasm: number }[];
		expect(workers.filter((worker) => worker.name === 'production.worker').length, 'no dedicated history Worker').toBe(0);
		expect(workers.filter((worker) => worker.name === 'shared.worker').length, `${path}: one shared Rust core Worker`).toBe(1);
		const embedStats = () => page.evaluate(() => (window as any).__openmatesRustEmbedStats?.() ?? null);
		if (path === 'rust') {
			await expect.poll(async () => (await embedStats())?.rows ?? 0, { message: 'rust: embed fields opened by the embedData unit' }).toBeGreaterThan(0);
			expect((await embedStats()).failures, 'rust: no embedData failures').toBe(0);
			expect((await embedStats()).toonDecodes, 'rust: TOON content decoded by the Rust parser').toBeGreaterThan(0);
		} else {
			expect((await embedStats())?.rows ?? 0, `${path}: embedData unused with TS crypto`).toBe(0);
			expect((await embedStats())?.toonDecodes ?? 0, `${path}: Rust TOON unused with TS crypto`).toBe(0);
		}
		sample.rustEmbedData = await embedStats();
		samples[path].push(sample);
	}
	await page.evaluate((keys: string[]) => { for (const key of keys) localStorage.removeItem(key); }, OPT_OUT_KEYS);
	const median = (rows: Record<string, any>[], key: string) => {
		const values = rows.map((row) => row[key]).filter((v): v is number => typeof v === 'number').sort((a, b) => a - b);
		return values.length ? values[Math.floor(values.length / 2)] : null;
	};
	const medians = (rows: Record<string, any>[]) => Object.fromEntries(['embedReadyMs', 'assistantRowMs', 'browserCpuMs', 'browserRssBytes', 'mainHeapBytes', 'dedicatedWorkers', 'rustWorkers', 'wasmInstantiations', 'sharedWorkerWasm']
		.map((key) => [key, median(rows, key)]));
	const rustReady = median(samples.rust, 'embedReadyMs'), tsReady = median(samples.ts, 'embedReadyMs');
	const historyReady = median(samples.history, 'embedReadyMs');
	const metrics = { path: 'rust', samples: samples.rust, median: medians(samples.rust), tsHistory: { samples: samples.ts, median: medians(samples.ts) },
		rustHistoryTsCrypto: { samples: samples.history, median: medians(samples.history) },
		rustToTsEmbedReadyRatio: rustReady && tsReady ? rustReady / tsReady : null,
		rustCryptoToTsCryptoEmbedReadyRatio: rustReady && historyReady ? rustReady / historyReady : null };
	log('embed ready metrics', metrics);
	await testInfo.attach('embed-ready-metrics.json', { body: JSON.stringify(metrics, null, 2), contentType: 'application/json' });
	expect(rustReady, 'embed became ready on every Rust reload').not.toBeNull();
	expect(tsReady, 'embed became ready on every TS reload').not.toBeNull();
	// Strict user-facing gate (attached above, so a failing run keeps its numbers).
	for (const key of ['embedReadyMs', 'browserCpuMs', 'browserRssBytes']) {
		const rust = median(samples.rust, key), ts = median(samples.ts, key);
		expect(rust, `embed-ready Rust median ${key}`).not.toBeNull();
		expect(ts, `embed-ready TS median ${key}`).not.toBeNull();
		expect.soft(rust!, `embed-ready ${key}: Rust ${rust} vs TS ${ts}`).toBeLessThanOrEqual(budgetLimit(key, ts!));
	}
});
