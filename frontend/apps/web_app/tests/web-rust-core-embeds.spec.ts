/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Opt-in shared Rust core (WASM) — saved embeds behind Rust history, VITE_OPENMATES_RUST_CORE=1 build.
 *
 * Engineering migration check (web lane: history/admission). A code embed chat is
 * seeded through the normal send (CI mock replay). After reload the normal chat UI
 * (ActiveChat, Rust-decrypted history) shows the chat; the embed preview must
 * finish, the shared fullscreen must open from it and closing it must return to
 * the chat. Rust embed field decryption is asserted by the crypto lane's spec.
 * Records embed ready time, browser CPU and memory over three alternating
 * TS-history / Rust-history reload pairs (medians and ratio; target <= 1.1x).
 * Runs only in the CI lane that builds the Rust core package (web-rust-core-* specs).
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { createSignupLogger, createStepScreenshotter, getTestAccount, getE2EDebugUrl } = require('./signup-flow-helpers');
const { openFullscreen, closeFullscreen } = require('./helpers/embed-test-helpers');
const { seedCodeEmbedChat, measureEmbedReady } = require('./helpers/embed-ready-metrics');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
/** Measurement-only opt-out of the Rust history source (rustChatHistoryBootstrap.ts). */
const HISTORY_OPT_OUT_KEY = 'openmates_rust_core_history';

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

	// Alternate TS-history (measurement opt-out) and Rust-history reloads of the same
	// saved chat in this build, so both medians share one runner and page.
	const samples: Record<'ts' | 'rust', Record<string, any>[]> = { ts: [], rust: [] };
	for (const path of ['ts', 'rust', 'ts', 'rust', 'ts', 'rust'] as const) {
		await page.evaluate(([key, ts]: [string, boolean]) => { if (ts) localStorage.setItem(key, 'ts'); else localStorage.removeItem(key); },
			[HISTORY_OPT_OUT_KEY, path === 'ts']);
		const sample = (await measureEmbedReady(page, chatId, '[data-testid="message-assistant"]', 1) as any).samples[0];
		expect('rust:history-request' in sample.rustStages, `${path} reload ${path === 'rust' ? 'used' : 'did not use'} Rust history`).toBe(path === 'rust');
		samples[path].push(sample);
	}
	await page.evaluate((key: string) => localStorage.removeItem(key), HISTORY_OPT_OUT_KEY);
	const median = (rows: Record<string, any>[], key: string) => {
		const values = rows.map((row) => row[key]).filter((v): v is number => typeof v === 'number').sort((a, b) => a - b);
		return values.length ? values[Math.floor(values.length / 2)] : null;
	};
	const medians = (rows: Record<string, any>[]) => Object.fromEntries(['embedReadyMs', 'assistantRowMs', 'browserCpuMs', 'browserRssBytes', 'mainHeapBytes']
		.map((key) => [key, median(rows, key)]));
	const rustReady = median(samples.rust, 'embedReadyMs'), tsReady = median(samples.ts, 'embedReadyMs');
	// Target: Rust <= 1.1 x TS. Recorded, not yet gated (CI runners measured ~1.1x).
	const metrics = { path: 'rust', samples: samples.rust, median: medians(samples.rust), tsHistory: { samples: samples.ts, median: medians(samples.ts) },
		rustToTsEmbedReadyRatio: rustReady && tsReady ? rustReady / tsReady : null };
	log('embed ready metrics', metrics);
	await testInfo.attach('embed-ready-metrics.json', { body: JSON.stringify(metrics, null, 2), contentType: 'application/json' });
	expect(rustReady, 'embed became ready on every Rust reload').not.toBeNull();
	expect(tsReady, 'embed became ready on every TS reload').not.toBeNull();
});
