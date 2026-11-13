/* eslint-disable @typescript-eslint/no-require-imports -- Playwright CommonJS specs. */
/**
 * Attribution entry of the interleaved TS-vs-Rust web benchmark
 * (VITE_OPENMATES_RUST_CORE=1 build, web-rust-core-* CI lane): the same paired
 * bench as web-rust-core-bench.spec.ts with fewer pairs (default 4,
 * OPENMATES_BENCH_PAIRS) and the bench-profile.ts attribution always on
 * (CPU profiles per thread, per-process memory, WASM linear memory, Worker
 * stage measures, WASM asset size/Content-Type) attached as
 * web-rust-core-profile.json. Engineering measurement, not a product flow.
 */
export {};

const { test } = require('./helpers/cookie-audit');
const bench = require('./helpers/web-rust-core-bench-run');

test.afterEach(bench.benchFailureDiagnostics);

// contract-test: tooling

test('TS vs Rust reload attribution profile', async ({ page }: { page: any }, testInfo: any) => {
	test.slow();
	test.setTimeout(1500000);
	bench.skipWithoutCredentials(test, bench.TEST_EMAIL, bench.TEST_PASSWORD, bench.TEST_OTP_KEY);
	await bench.runWebRustCoreBench(page, testInfo, {
		pairs: Math.max(3, Number.parseInt(process.env.OPENMATES_BENCH_PAIRS ?? '4', 10) || 4),
		profile: true
	});
});
