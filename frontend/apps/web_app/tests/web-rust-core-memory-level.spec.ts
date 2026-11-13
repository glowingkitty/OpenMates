/* eslint-disable @typescript-eslint/no-require-imports -- Playwright CommonJS specs. */
/**
 * Same-tab memory level of the Rust history path against TS (VITE_OPENMATES_RUST_CORE=1
 * build, web-rust-core-* CI lane). Engineering measurement, not a product flow.
 *
 * One code-embed chat is seeded through the normal TS send, then the same tab
 * reloads it in 12 counterbalanced ts/rust pairs (bench-stats pairOrder, one
 * discarded warm-up pair). Every reload is measured after a GC-first memory-infra
 * dump (helpers/web-rust-core-reload-memory.ts); each Rust sample is compared with
 * the TS level interpolated around it, per process type and per renderer allocator
 * (PartitionAlloc buffer/array_buffer, malloc, V8, Blink GC). Attaches
 * web-rust-core-reload-memory.json and a markdown table. The per-reload slope runs
 * in web-rust-core-reload-memory.spec.ts.
 * Gates: >= 12 usable pairs, Rust total RSS level <= TS + 30 MB (approved
 * migration budget), at most one Rust core Worker and one WASM instance per Rust load.
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const bench = require('./helpers/web-rust-core-bench-run');
const { runReloadMemory, reloadMemoryTable } = require('./helpers/web-rust-core-reload-memory');
const { createSignupLogger, createStepScreenshotter, getE2EDebugUrl } = require('./signup-flow-helpers');
const { seedCodeEmbedChat } = require('./helpers/embed-ready-metrics');

const LEVEL_PAIRS = 12;
const RSS_LIMIT_BYTES = 30 * 1024 * 1024;

test.afterEach(bench.benchFailureDiagnostics);

// contract-test: tooling

test('same-tab memory level TS vs Rust on counterbalanced pairs', async ({ page }: { page: any }, testInfo: any) => {
	test.slow();
	test.setTimeout(1500000);
	bench.skipWithoutCredentials(test, bench.TEST_EMAIL, bench.TEST_PASSWORD, bench.TEST_OTP_KEY);
	const log = createSignupLogger('WEB_RUST_CORE_MEMORY_LEVEL');
	const screenshot = createStepScreenshotter(log);
	const chatId = await seedCodeEmbedChat(page, log, screenshot);
	const report = await runReloadMemory(page, chatId, {
		blockSize: 0,
		levelPairs: LEVEL_PAIRS,
		waitAllReady: bench.waitAllReady,
		optOutKey: bench.HISTORY_OPT_OUT_KEY,
		chatUrl: getE2EDebugUrl,
		log
	});
	const table = reloadMemoryTable(report);
	log('memory level table\n' + table, { liveCounts: report.liveCounts });
	await testInfo.attach('web-rust-core-reload-memory.json', { body: JSON.stringify(report, null, 2), contentType: 'application/json' });
	await testInfo.attach('web-rust-core-reload-memory.md', { body: table, contentType: 'text/markdown' });

	expect(report.levels.totalRssBytes.pairs, 'usable level pairs').toBeGreaterThanOrEqual(LEVEL_PAIRS);
	expect(report.liveCounts.rust.maxWasmMainThread, 'no WASM on the page realm').toBe(0);
	expect(report.liveCounts.rust.maxRustWorkers, 'at most one Rust core Worker per Rust load').toBeLessThanOrEqual(1);
	expect(report.liveCounts.rust.maxWasmInstantiations, 'at most one WASM instance per Rust load').toBeLessThanOrEqual(1);
	expect(report.levels.totalRssBytes.ci95[1], 'Rust RSS level <= TS + 30 MB').toBeLessThanOrEqual(RSS_LIMIT_BYTES);
});
