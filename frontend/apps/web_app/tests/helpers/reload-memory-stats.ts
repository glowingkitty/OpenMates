/* eslint-disable @typescript-eslint/no-explicit-any -- Playwright Page/CDP handles and bench reports are untyped in these CommonJS specs. */
/**
 * Per-reload slope statistics for the same-tab reload memory measurement
 * (web-rust-core-reload-memory.ts). Tooling only, no imports, so node:test can
 * load it directly (reload-memory-stats.test.ts); like bench-stats.ts it is a
 * CommonJS script without `export`.
 *
 * armSlopes fits level = a + slopeTs * tsReloads + slopeRust * rustReloads
 * (+ rustLevel * isRust with armTerm) by least squares over the samples and gives
 * each slope a seeded residual-bootstrap 95% CI. slopeVerdict applies the gate:
 * Rust CI upper bound <= max(TS slope, 0) + 1 MiB per reload.
 */
const STATS_MIB = 1024 * 1024;
/** Approved slope gate: Rust per-reload growth CI upper bound <= max(TS slope, 0) + 1 MiB. */
const SLOPE_ALLOWANCE_BYTES = 1 * STATS_MIB;
const STATS_RESAMPLES = 4000;

type SlopeSample = Record<string, any>;

/** Value of a dotted metric of a sample, e.g. `byType.GPU.rssBytes` or `allocators.v8/main`. */
function metricValue(sample: SlopeSample, metric: string): number | null {
	if (metric.startsWith('allocators.')) return sample.allocators?.[metric.slice('allocators.'.length)] ?? null;
	let value: any = sample;
	for (const part of metric.split('.')) value = value?.[part];
	return Number.isFinite(value) ? value : null;
}

/** Least squares by normal equations (few columns); null when singular. */
function leastSquares(rows: number[][], y: number[]): number[] | null {
	const n = rows[0].length;
	const a = Array.from({ length: n }, (_, i) => [...Array.from({ length: n }, (_, j) => rows.reduce((sum, row) => sum + row[i] * row[j], 0)), rows.reduce((sum, row, k) => sum + row[i] * y[k], 0)]);
	for (let col = 0; col < n; col += 1) {
		let pivot = col;
		for (let r = col + 1; r < n; r += 1) if (Math.abs(a[r][col]) > Math.abs(a[pivot][col])) pivot = r;
		if (Math.abs(a[pivot][col]) < 1e-9) return null;
		[a[col], a[pivot]] = [a[pivot], a[col]];
		for (let r = 0; r < n; r += 1) {
			if (r === col) continue;
			const factor = a[r][col] / a[col][col];
			for (let c = col; c <= n; c += 1) a[r][c] -= factor * a[col][c];
		}
	}
	return a.map((row, i) => row[n] / row[i]);
}

/** Deterministic PRNG (same seed, same interval). */
function seeded(seed: number): () => number {
	let state = seed >>> 0;
	return () => {
		state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
		return state / 4294967296;
	};
}

function percentile(sorted: number[], q: number): number {
	const position = (sorted.length - 1) * q;
	const low = Math.floor(position);
	return sorted[low] + (sorted[Math.ceil(position)] - sorted[low]) * (position - low);
}

/**
 * Per-arm per-reload slopes of `metric`: least squares of the level on the
 * cumulative TS and Rust reload counts (plus an arm level term with `armTerm`),
 * 95% CI by residual bootstrap.
 */
function armSlopes(samples: SlopeSample[], metric: string, armTerm: boolean): Record<string, any> {
	const rows: number[][] = [];
	const y: number[] = [];
	for (const sample of samples) {
		const value = metricValue(sample, metric);
		if (value === null) continue;
		rows.push([1, sample.tsReloads, sample.rustReloads, ...(armTerm ? [sample.arm === 'rust' ? 1 : 0] : [])]);
		y.push(value);
	}
	const fit = rows.length > rows[0]?.length + 2 ? leastSquares(rows, y) : null;
	if (!fit) return { n: rows.length, ts: null, rust: null };
	const predicted = rows.map((row) => row.reduce((sum, x, i) => sum + x * fit[i], 0));
	const residuals = y.map((value, k) => value - predicted[k]);
	const random = seeded(20261106);
	const tsDraws: number[] = [];
	const rustDraws: number[] = [];
	for (let r = 0; r < STATS_RESAMPLES; r += 1) {
		const draw = leastSquares(rows, predicted.map((value) => value + residuals[Math.floor(random() * residuals.length)]));
		if (!draw) continue;
		tsDraws.push(draw[1]);
		rustDraws.push(draw[2]);
	}
	tsDraws.sort((p, q) => p - q);
	rustDraws.sort((p, q) => p - q);
	return {
		n: rows.length,
		ts: { slope: fit[1], ci95: [percentile(tsDraws, 0.025), percentile(tsDraws, 0.975)] },
		rust: { slope: fit[2], ci95: [percentile(rustDraws, 0.025), percentile(rustDraws, 0.975)] },
		...(armTerm ? { rustLevel: fit[3] } : {})
	};
}

/** Gate: Rust slope CI upper bound <= max(TS slope, 0) + allowance (a falling TS level is noise, not a credit). */
function slopeVerdict(slopes: Record<string, any>): Record<string, any> {
	if (!slopes.ts || !slopes.rust) return { verdict: 'inconclusive', reason: 'too few samples' };
	const limit = Math.max(slopes.ts.slope, 0) + SLOPE_ALLOWANCE_BYTES;
	const verdict = slopes.rust.ci95[1] <= limit ? 'rust_not_worse' : slopes.rust.ci95[0] > limit ? 'rust_worse' : 'inconclusive';
	return { verdict, limit, allowanceBytes: SLOPE_ALLOWANCE_BYTES };
}

module.exports = { armSlopes, slopeVerdict, leastSquares, metricValue, SLOPE_ALLOWANCE_BYTES };
