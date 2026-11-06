/* eslint-disable @typescript-eslint/no-require-imports -- Playwright CommonJS specs. */
/**
 * Same-tab reload memory slope of the TS and Rust history paths
 * (VITE_OPENMATES_RUST_CORE=1 build, web-rust-core-* CI lane). Engineering
 * measurement, not a product flow; nothing is sent after the seed.
 *
 * One code-embed chat is seeded through the normal TS send, then the same tab
 * reloads it in ABBA blocks (ts x T, rust x 2T, ts x T; T = OPENMATES_RELOAD_BLOCK,
 * default 20) with a GC-first checkpoint (5 TS reloads, each followed by a
 * memory-infra dump) before, between and after the blocks
 * (helpers/web-rust-core-reload-memory.ts). The CI Playwright command has a
 * 20 minute budget: a plain reload takes about 8 s, a dumped one about 20 s.
 * Attaches web-rust-core-reload-memory.json and a markdown table.
 * Gates (permanent): for retained renderer heap and total RSS, Rust's per-reload
 * slope CI upper bound <= max(TS slope, 0) + 1 MiB; at most one Rust core Worker
 * and one WASM instance per load, none on the page realm.
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const bench = require('./helpers/web-rust-core-bench-run');
const { runReloadMemory, reloadMemoryTable, GATED_METRICS } = require('./helpers/web-rust-core-reload-memory');
const { createSignupLogger, createStepScreenshotter, getE2EDebugUrl } = require('./signup-flow-helpers');
const { seedCodeEmbedChat } = require('./helpers/embed-ready-metrics');

test.afterEach(bench.benchFailureDiagnostics);

// contract-test: tooling

test('same-tab reload memory slope TS vs Rust', async ({ page }: { page: any }, testInfo: any) => {
	test.slow();
	test.setTimeout(1500000);
	bench.skipWithoutCredentials(test, bench.TEST_EMAIL, bench.TEST_PASSWORD, bench.TEST_OTP_KEY);
	const log = createSignupLogger('WEB_RUST_CORE_RELOAD_MEMORY');
	const screenshot = createStepScreenshotter(log);
	const chatId = await seedCodeEmbedChat(page, log, screenshot);
	const report = await runReloadMemory(page, chatId, {
		blockSize: Math.max(5, Number.parseInt(process.env.OPENMATES_RELOAD_BLOCK ?? '20', 10) || 20),
		levelPairs: 0,
		waitAllReady: bench.waitAllReady,
		optOutKey: bench.HISTORY_OPT_OUT_KEY,
		chatUrl: getE2EDebugUrl,
		log
	});
	const table = reloadMemoryTable(report);
	log('reload memory table\n' + table, { liveCounts: report.liveCounts });
	await testInfo.attach('web-rust-core-reload-memory.json', { body: JSON.stringify(report, null, 2), contentType: 'application/json' });
	await testInfo.attach('web-rust-core-reload-memory.md', { body: table, contentType: 'text/markdown' });

	for (const arm of ['ts', 'rust']) {
		expect(report.liveCounts[arm].maxRustWorkers, `${arm}: at most one Rust core Worker per load`).toBeLessThanOrEqual(1);
		expect(report.liveCounts[arm].maxWasmInstantiations, `${arm}: at most one WASM instance per load`).toBeLessThanOrEqual(1);
		expect(report.liveCounts[arm].maxWasmMainThread, `${arm}: no WASM on the page realm`).toBe(0);
	}
	expect(report.unusableLoads.rust, 'reloads whose chat did not render (retried once each, counted in the slopes)').toBeLessThanOrEqual(2);
	for (const metric of GATED_METRICS) {
		expect(report.retainedSlopes[metric].gate.verdict, `${metric}: Rust per-reload slope <= max(TS, 0) + 1 MiB`).toBe('rust_not_worse');
	}
});
