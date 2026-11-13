/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Paired ABBA latency gate for the Apps request flow (web-rust-core-apps.spec.ts).
 *
 * Applies the web Rust performance budget (.claude/rules/cli-sdk.md, user
 * decision 2026-11-06) to request -> result-ready wall time: the upper bound of
 * the 95% CI of the paired effect must be within max(+10%, +50 ms) (either the
 * ratio or the difference bound passes), and the Rust p95 at most +100 ms over
 * the TS p95. Uses bench-stats.ts (summarizePaired, pairOrder) unchanged.
 */
export {};

const { summarizePaired, pairOrder } = require('./bench-stats');

/** Minimum pairs the budget requires. */
const APPS_BENCH_PAIRS = 12;

function p95(values: number[]): number {
	const sorted = [...values].sort((a, b) => a - b);
	return sorted[Math.min(sorted.length - 1, Math.ceil(sorted.length * 0.95) - 1)];
}

/**
 * Runs `pairs` counterbalanced pairs (`pairOrder`) of `sample(arm)` and returns
 * the budget verdict with both paired summaries and the p95 comparison.
 */
/** Budget outcome: both bench-stats paired summaries plus the p95 tail comparison. */
type AppsLatencyBench = {
	pairs: number;
	rows: { ts: number; rust: number }[];
	ratio: Record<string, unknown>;
	difference: Record<string, unknown>;
	tsP95: number;
	rustP95: number;
	verdict: 'rust_not_worse' | 'rust_worse_or_inconclusive';
};

async function runAppsLatencyPairs(sample: (arm: 'ts' | 'rust') => Promise<number>, pairs = APPS_BENCH_PAIRS): Promise<AppsLatencyBench> {
	const rows: { ts: number; rust: number }[] = [];
	for (let index = 0; index < pairs; index++) {
		const row: Partial<Record<'ts' | 'rust', number>> = {};
		for (const arm of pairOrder(index) as ('ts' | 'rust')[]) row[arm] = await sample(arm);
		rows.push(row as { ts: number; rust: number });
	}
	const ratio = summarizePaired(rows, { mode: 'ratio', margin: 0.10 });
	const difference = summarizePaired(rows, { mode: 'difference', limit: 50 });
	const tsP95 = p95(rows.map((row) => row.ts));
	const rustP95 = p95(rows.map((row) => row.rust));
	const wallPass = ratio.verdict === 'rust_not_worse' || difference.verdict === 'rust_not_worse';
	const tailPass = rustP95 - tsP95 <= 100;
	return { pairs: rows.length, rows, ratio, difference, tsP95, rustP95, verdict: wallPass && tailPass ? 'rust_not_worse' : 'rust_worse_or_inconclusive' };
}

module.exports = { APPS_BENCH_PAIRS, runAppsLatencyPairs };
