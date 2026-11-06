/* eslint-disable @typescript-eslint/no-require-imports -- Playwright CommonJS specs. */
/**
 * Interleaved TS-vs-Rust web benchmark (VITE_OPENMATES_RUST_CORE=1 build).
 *
 * Engineering benchmark for the Rust migration, not a product flow. One code-embed
 * chat is seeded through the normal TS send. The same saved chat is then reloaded
 * in counterbalanced pairs (TS,Rust then Rust,TS alternately) inside one job on
 * one runner and one page, N pairs (default 12, env OPENMATES_BENCH_PAIRS; one
 * discarded TS,Rust warm-up pair first). Each reload records, from the same navigation:
 *   chatRenderedMs   saved chat open -> decrypted user + assistant rows rendered
 *   embedReadyMs     -> finished code embed preview in the DOM
 *   uiInteractiveMs  boot: -> message editor present
 *   loadChatStageMs  -> first openmates:rust:load-chat mark (Rust arm only; not paired)
 *   browserCpuMs, browserRssBytes, mainHeapBytes, dedicatedWorkers, rustWorkers, wasmInstantiations
 * Summed process RSS climbs with every same-renderer reload whatever the arm, so its
 * gate compares each Rust sample with the TS level interpolated between the TS
 * samples around it (bench-stats.ts interpolatedBaselinePairs).
 * Per metric the median of paired rust/ts ratios (count metrics: paired differences)
 * with a bootstrap 95% CI and a verdict rust_not_worse / rust_worse / inconclusive
 * is attached as web-rust-core-bench.json plus a short markdown table.
 * Resubmit the same source with a new `ci_coordinator.py submit --attempt <n>` for
 * fresh samples. Runs only in the web-rust-core-* CI lane.
 * OPENMATES_BENCH_PROFILE=1 adds the attribution profile (helpers/bench-profile.ts);
 * web-rust-core-profile.spec.ts is the CI entry with it on.
 */

export {};

const { test } = require('./helpers/cookie-audit');
const bench = require('./helpers/web-rust-core-bench-run');

test.afterEach(bench.benchFailureDiagnostics);

// contract-test: tooling

test('interleaved TS vs Rust reload benchmark with paired bootstrap verdicts', async ({ page }: { page: any }, testInfo: any) => {
	test.slow();
	test.setTimeout(1500000);
	bench.skipWithoutCredentials(test, bench.TEST_EMAIL, bench.TEST_PASSWORD, bench.TEST_OTP_KEY);
	await bench.runWebRustCoreBench(page, testInfo, {
		pairs: Math.max(3, Number.parseInt(process.env.OPENMATES_BENCH_PAIRS ?? '12', 10) || 12),
		profile: process.env.OPENMATES_BENCH_PROFILE === '1'
	});
});
