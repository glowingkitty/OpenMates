/**
 * Unit tests for the paired benchmark statistics (tooling only).
 */

// contract-test-file: tooling

/* eslint-disable @typescript-eslint/no-require-imports */

const assert = require('node:assert/strict');
const test = require('node:test');
const { summarizePaired, markdownTable, median } = require('./bench-stats.ts');

const pairsOf = (ts: number[], rust: number[]) => ts.map((value, i) => ({ ts: value, rust: rust[i] }));

test('median handles odd and even counts', () => {
	assert.equal(median([3, 1, 2]), 2);
	assert.equal(median([4, 1, 2, 3]), 2.5);
});

test('equal-speed noisy pairs are rust_not_worse', () => {
	const ts = [1000, 1400, 900, 1200, 1100, 1300, 1000, 950, 1250, 1050, 1150, 1000];
	const result = summarizePaired(pairsOf(ts, ts));
	assert.equal(result.verdict, 'rust_not_worse');
	assert.equal(result.median, 1);
	assert.equal(result.pairs, 12);
});

test('consistently slower rust is rust_worse', () => {
	const ts = [1000, 1100, 900, 1000, 1050, 980, 1020, 990, 1010, 1000, 1005, 995];
	const result = summarizePaired(pairsOf(ts, ts.map((v) => v * 1.3)));
	assert.equal(result.verdict, 'rust_worse');
	assert.ok(result.ci95[0] > 1.1);
});

test('wide spread around the limit is inconclusive', () => {
	const ts = [1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000];
	const rust = [800, 1500, 900, 1400, 1000, 1300, 700, 1600];
	assert.equal(summarizePaired(pairsOf(ts, rust)).verdict, 'inconclusive');
});

test('too few or non-numeric pairs are inconclusive and do not throw', () => {
	assert.equal(summarizePaired(pairsOf([1, 2], [1, 2])).verdict, 'inconclusive');
	assert.equal(summarizePaired([{ ts: null, rust: 1 }, { ts: 1, rust: undefined }]).verdict, 'inconclusive');
});

test('difference mode covers count metrics with zero TS value', () => {
	const zeros = new Array(8).fill(0);
	assert.equal(summarizePaired(pairsOf(zeros, zeros), { mode: 'difference' }).verdict, 'rust_not_worse');
	assert.equal(summarizePaired(pairsOf(zeros, new Array(8).fill(1)), { mode: 'difference' }).verdict, 'rust_worse');
});

test('result is deterministic and renders a markdown table', () => {
	const ts = [10, 12, 11, 13, 10, 12, 11, 14];
	const rust = [11, 12, 10, 13, 11, 12, 12, 13];
	const a = summarizePaired(pairsOf(ts, rust));
	assert.deepEqual(a, summarizePaired(pairsOf(ts, rust)));
	const table = markdownTable({ wall: a });
	assert.match(table, /\| wall \| 8 \|/);
	assert.equal(table.split('\n').length, 3);
});

test('difference limit and report-only gating', () => {
	const ts = new Array(8).fill(100);
	assert.equal(summarizePaired(pairsOf(ts, ts.map((v) => v + 20)), { mode: 'difference', limit: 30 }).verdict, 'rust_not_worse');
	assert.equal(summarizePaired(pairsOf(ts, ts.map((v) => v + 40)), { mode: 'difference', limit: 30 }).verdict, 'rust_worse');
	assert.equal(summarizePaired(pairsOf(ts, ts.map((v) => v + 40)), { mode: 'difference', gate: false }).verdict, 'reported_only');
});

test('default margin is +10%', () => {
	const ts = [1000, 1010, 990, 1000, 1005, 995, 1000, 1000];
	assert.equal(summarizePaired(pairsOf(ts, ts.map((v) => v * 1.13))).verdict, 'rust_worse');
	assert.equal(summarizePaired(pairsOf(ts, ts.map((v) => v * 1.08))).verdict, 'rust_not_worse');
});

const { pairOrder, interpolatedBaselinePairs, transitionIncrements } = require('./bench-stats.ts');

test('pair order alternates ts-first and rust-first', () => {
	assert.deepEqual([0, 1, 2, 3].map(pairOrder), [['ts', 'rust'], ['rust', 'ts'], ['ts', 'rust'], ['rust', 'ts']]);
});

test('interpolated baseline removes linear reload drift', () => {
	// Level = 1000 + 40 per reload, Rust 10 above TS; counterbalanced order T R R T T R T.
	const arms: ('ts' | 'rust')[] = ['ts', 'rust', 'rust', 'ts', 'ts', 'rust', 'ts'];
	const sequence = arms.map((arm, k) => ({ arm, value: 1000 + 40 * k + (arm === 'rust' ? 10 : 0) }));
	const pairs = interpolatedBaselinePairs(sequence);
	assert.equal(pairs.length, 3);
	for (const pair of pairs) assert.equal(pair.rust - pair.ts, 10);
	// The adjacent-pair difference would have charged the drift to Rust.
	assert.equal(sequence[1].value - sequence[0].value, 50);
});

test('interpolated baseline drops Rust samples without TS on both sides', () => {
	const pairs = interpolatedBaselinePairs([{ arm: 'rust', value: 1 }, { arm: 'ts', value: 2 }, { arm: 'rust', value: 3 }, { arm: 'ts', value: null }]);
	assert.deepEqual(pairs, []);
});

test('transition increments group by previous and current arm', () => {
	const result = transitionIncrements([
		{ arm: 'ts', before: 0, after: 40 }, { arm: 'rust', before: 40, after: 90 },
		{ arm: 'rust', before: 90, after: 130 }, { arm: 'ts', before: 130, after: 160 }, { arm: 'ts', before: 160, after: 200 }
	]);
	assert.deepEqual(result['ts->rust'], { n: 1, median: 50 });
	assert.deepEqual(result['rust->rust'], { n: 1, median: 40 });
	assert.deepEqual(result['rust->ts'], { n: 1, median: 30 });
	assert.deepEqual(result['ts->ts'], { n: 1, median: 40 });
});

test('wall floor: +40 ms on a 100 ms flow (+40%) is within max(+10%, +50 ms)', () => {
	const ts = [100, 101, 99, 100, 102, 98, 100, 101, 99, 100, 100, 100];
	const rust = ts.map((v) => v + 40);
	assert.equal(summarizePaired(pairsOf(ts, rust)).verdict, 'rust_worse');
	const gated = summarizePaired(pairsOf(ts, rust), { floorMs: 50 });
	assert.equal(gated.verdict, 'rust_not_worse');
	assert.ok(Math.abs(gated.limit - 1.5) < 1e-9);
	assert.equal(summarizePaired(pairsOf(ts, ts.map((v) => v + 80)), { floorMs: 50 }).verdict, 'rust_worse');
});

test('wall limit uses +10% when it exceeds the 50 ms floor', () => {
	const ts = [2000, 2010, 1990, 2000, 2020, 1980, 2000, 2010, 1990, 2000, 2000, 2000];
	const result = summarizePaired(pairsOf(ts, ts.map((v) => v * 1.08)), { floorMs: 50 });
	assert.equal(result.verdict, 'rust_not_worse');
	assert.ok(Math.abs(result.limit - 1.1) < 1e-9);
});

test('p95 rule fails a slow tail even when the median passes', () => {
	const ts = [1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000];
	const rust = [1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000, 1400];
	const fail = summarizePaired(pairsOf(ts, rust), { floorMs: 50, p95AllowMs: 100 });
	assert.equal(fail.p95.ok, false);
	assert.equal(fail.verdict, 'rust_worse');
	const cold = summarizePaired(pairsOf(ts, rust.map((v, i) => (i === 11 ? 1250 : v))), { floorMs: 50, p95AllowMs: 200 });
	assert.equal(cold.p95.ok, true);
	assert.equal(cold.verdict, 'rust_not_worse');
});

test('CPU margin 0.15 allows +12% and rejects +30%', () => {
	const ts = [1000, 1010, 990, 1000, 1020, 980, 1000, 1010, 990, 1000, 1000, 1000];
	assert.equal(summarizePaired(pairsOf(ts, ts.map((v) => v * 1.12)), { margin: 0.15 }).verdict, 'rust_not_worse');
	assert.equal(summarizePaired(pairsOf(ts, ts.map((v) => v * 1.3)), { margin: 0.15 }).verdict, 'rust_worse');
});
