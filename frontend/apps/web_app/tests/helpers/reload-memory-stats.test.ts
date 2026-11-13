/**
 * Unit tests for the per-reload slope statistics (tooling only).
 */

// contract-test-file: tooling

/* eslint-disable @typescript-eslint/no-require-imports */

const assert = require('node:assert/strict');
const test = require('node:test');
const { armSlopes, slopeVerdict, leastSquares } = require('./reload-memory-stats.ts');

const MIB_UNIT = 1024 * 1024;

/** ABBA checkpoint-style samples: level = base + ts*slopeTs + rust*slopeRust + deterministic noise. */
function samples(slopeTs: number, slopeRust: number, noiseMiB: number, rustLevel = 0): Record<string, any>[] {
	const out: Record<string, any>[] = [];
	let ts = 0;
	let rust = 0;
	let k = 0;
	for (const [arm, size] of [['ts', 15], ['rust', 30], ['ts', 15]] as ['ts' | 'rust', number][]) {
		for (let i = 0; i < size; i += 1) {
			if (arm === 'ts') ts += 1; else rust += 1;
			const noise = (((k * 7919) % 13) / 6 - 1) * noiseMiB * MIB_UNIT;
			k += 1;
			out.push({ arm, tsReloads: ts, rustReloads: rust, value: 1000 * MIB_UNIT + ts * slopeTs + rust * slopeRust + (arm === 'rust' ? rustLevel : 0) + noise });
		}
	}
	return out;
}

test('leastSquares recovers an exact plane', () => {
	const rows = [[1, 0, 0], [1, 1, 0], [1, 0, 1], [1, 2, 3]];
	const fit = leastSquares(rows, rows.map((r) => 5 + 2 * r[1] - 3 * r[2]));
	assert.ok(fit);
	assert.ok(Math.abs(fit[0] - 5) < 1e-9 && Math.abs(fit[1] - 2) < 1e-9 && Math.abs(fit[2] + 3) < 1e-9);
});

test('flat noisy levels pass the slope gate', () => {
	const result = armSlopes(samples(0, 0, 10), 'value', true);
	assert.ok(Math.abs(result.rust.slope) < 0.5 * MIB_UNIT);
	assert.equal(slopeVerdict(result).verdict, 'rust_not_worse');
});

test('a Rust-only leak of 5 MiB per reload is rust_worse', () => {
	const result = armSlopes(samples(0, 5 * MIB_UNIT, 10), 'value', true);
	assert.ok(Math.abs(result.rust.slope - 5 * MIB_UNIT) < 1 * MIB_UNIT);
	assert.equal(slopeVerdict(result).verdict, 'rust_worse');
});

test('equal growth in both arms is not charged to Rust, and the arm level term absorbs a constant offset', () => {
	const result = armSlopes(samples(4 * MIB_UNIT, 4 * MIB_UNIT, 5, 30 * MIB_UNIT), 'value', true);
	assert.ok(Math.abs(result.ts.slope - 4 * MIB_UNIT) < 1 * MIB_UNIT);
	assert.ok(Math.abs(result.rustLevel - 30 * MIB_UNIT) < 10 * MIB_UNIT);
	assert.equal(slopeVerdict(result).verdict, 'rust_not_worse');
});

test('a falling TS level gives Rust no credit', () => {
	assert.equal(slopeVerdict({ ts: { slope: -5 * MIB_UNIT, ci95: [-6 * MIB_UNIT, -4 * MIB_UNIT] }, rust: { slope: 1.5 * MIB_UNIT, ci95: [1.2 * MIB_UNIT, 1.8 * MIB_UNIT] } }).verdict, 'rust_worse');
});

test('too few samples are inconclusive', () => {
	const result = armSlopes(samples(0, 0, 1).slice(0, 4), 'value', true);
	assert.equal(slopeVerdict(result).verdict, 'inconclusive');
});
