/* eslint-disable @typescript-eslint/no-explicit-any -- CommonJS Playwright helper. */
/**
 * Paired statistics for the interleaved TS-vs-Rust web benchmark
 * (web-rust-core-bench.spec.ts). Pair i is one TS sample and the Rust sample
 * taken right after it in the same job, so slow-runner drift cancels out.
 *
 * Per metric: median of paired ratios (rust / ts) or, for count metrics whose TS
 * value can be zero, of paired differences (rust - ts), with a seeded percentile
 * bootstrap 95% confidence interval of that median and a verdict:
 *   rust_not_worse  CI upper bound <= limit (ratio: 1 + margin, difference: 0)
 *   rust_worse      CI lower bound >  limit
 *   inconclusive    otherwise (too noisy or too few pairs; resubmit with a new attempt)
 */

/** Approved perf gate (.claude/rules/cli-sdk.md): wall/CPU within +3%, RSS within +30 MB, at most one WASM instance. */
const DEFAULT_MARGIN = 0.03;
const DEFAULT_RESAMPLES = 4000;

/** Deterministic PRNG so the same samples always give the same interval. */
function mulberry32(seed: number): () => number {
	let state = seed >>> 0;
	return () => {
		state = (state + 0x6d2b79f5) >>> 0;
		let t = state;
		t = Math.imul(t ^ (t >>> 15), t | 1);
		t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
		return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
	};
}

function median(values: number[]): number {
	const sorted = [...values].sort((a, b) => a - b);
	const mid = sorted.length >> 1;
	return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function quantile(sorted: number[], q: number): number {
	const position = (sorted.length - 1) * q;
	const low = Math.floor(position);
	const high = Math.ceil(position);
	return sorted[low] + (sorted[high] - sorted[low]) * (position - low);
}

function bootstrapMedianCi(values: number[], resamples: number, seed: number): [number, number] {
	const random = mulberry32(seed);
	const medians: number[] = [];
	for (let r = 0; r < resamples; r += 1) {
		const draw: number[] = [];
		for (let i = 0; i < values.length; i += 1) draw.push(values[Math.floor(random() * values.length)]);
		medians.push(median(draw));
	}
	medians.sort((a, b) => a - b);
	return [quantile(medians, 0.025), quantile(medians, 0.975)];
}

/**
 * @param pairs  rows with numeric `ts` and `rust`; pairs where either is not a finite number are dropped
 * @param options.mode 'ratio' (default, needs ts > 0) or 'difference'
 * @param options.margin allowed relative slowdown for ratio metrics (default 0.03)
 * @param options.limit allowed absolute difference for difference metrics (default 0; e.g. 30 MB RSS)
 * @param options.gate false reports the effect only (verdict 'reported_only')
 */
function summarizePaired(pairs: { ts: unknown; rust: unknown }[], options: { mode?: 'ratio' | 'difference'; margin?: number; limit?: number; gate?: boolean; resamples?: number; seed?: number } = {}): Record<string, any> {
	const mode = options.mode ?? 'ratio';
	const margin = options.margin ?? DEFAULT_MARGIN;
	const usable = pairs.filter((p): p is { ts: number; rust: number } => Number.isFinite(p.ts) && Number.isFinite(p.rust) && (mode === 'difference' || (p.ts as number) > 0));
	if (usable.length < 3) {
		return { mode, pairs: usable.length, verdict: 'inconclusive', reason: 'fewer than 3 usable pairs' };
	}
	const effects = usable.map((p) => (mode === 'ratio' ? p.rust / p.ts : p.rust - p.ts));
	const [ciLow, ciHigh] = bootstrapMedianCi(effects, options.resamples ?? DEFAULT_RESAMPLES, options.seed ?? 20260101);
	const limit = mode === 'ratio' ? 1 + margin : (options.limit ?? 0);
	let verdict = 'inconclusive';
	if (options.gate === false) verdict = 'reported_only';
	else if (ciHigh <= limit) verdict = 'rust_not_worse';
	else if (ciLow > limit) verdict = 'rust_worse';
	return {
		mode,
		pairs: usable.length,
		tsMedian: median(usable.map((p) => p.ts)),
		rustMedian: median(usable.map((p) => p.rust)),
		median: median(effects),
		ci95: [ciLow, ciHigh],
		limit,
		verdict,
	};
}

function fmt(value: unknown): string {
	if (typeof value !== 'number') return '-';
	if (Math.abs(value) >= 1000) return value.toFixed(0);
	return String(Math.round(value * 1000) / 1000);
}

/** Short markdown table: one row per metric. */
function markdownTable(summary: Record<string, Record<string, any>>): string {
	const rows = ['| metric | pairs | TS median | Rust median | median paired effect | 95% CI | verdict |', '|---|---|---|---|---|---|---|'];
	for (const [metric, s] of Object.entries(summary)) {
		const effect = s.median === undefined ? '-' : `${fmt(s.median)}${s.mode === 'ratio' ? 'x' : ' (diff)'}`;
		const ci = s.ci95 ? `[${fmt(s.ci95[0])}, ${fmt(s.ci95[1])}]` : '-';
		rows.push(`| ${metric} | ${s.pairs} | ${fmt(s.tsMedian)} | ${fmt(s.rustMedian)} | ${effect} | ${ci} | ${s.verdict} |`);
	}
	return rows.join('\n');
}

module.exports = { summarizePaired, markdownTable, median, bootstrapMedianCi };
