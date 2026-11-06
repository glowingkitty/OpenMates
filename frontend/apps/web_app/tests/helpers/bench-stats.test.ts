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
	assert.ok(result.ci95[0] > 1.03);
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

test('default margin is the approved +3%', () => {
	const ts = [1000, 1010, 990, 1000, 1005, 995, 1000, 1000];
	assert.equal(summarizePaired(pairsOf(ts, ts.map((v) => v * 1.04))).verdict, 'rust_worse');
	assert.equal(summarizePaired(pairsOf(ts, ts.map((v) => v * 1.02))).verdict, 'rust_not_worse');
});
