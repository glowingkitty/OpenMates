/* eslint-disable @typescript-eslint/no-explicit-any -- CommonJS Playwright helper. */
/**
 * Paired statistics for the interleaved TS-vs-Rust web benchmark
 * (web-rust-core-bench.spec.ts). Pair i is one TS and one Rust sample taken back
 * to back in the same job, in counterbalanced order (pairOrder), so slow-runner
 * drift and carry-over from the previous arm cancel out. Level metrics that
 * accumulate across reloads (RSS) use interpolatedBaselinePairs instead.
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

/** Arm order of paired sample `index` (0 = warm-up): ts,rust then rust,ts alternately (ABBA counterbalancing). */
function pairOrder(index: number): ('ts' | 'rust')[] {
	return index % 2 === 0 ? ['ts', 'rust'] : ['rust', 'ts'];
}

/**
 * Drift-corrected pairs for level metrics such as summed process RSS. A same-renderer
 * reload does not return all freed memory to the OS, so RSS climbs with every reload
 * (about 40 MB per reload in bench 4d5da97f) whatever the arm. Comparing a Rust sample
 * with the TS sample right before it then charges one reload of drift to Rust. Here
 * each Rust sample is compared with the TS level linearly interpolated, at the Rust
 * sample's position, between the nearest TS samples before and after it; a Rust
 * sample without a TS sample on both sides is dropped.
 * @param sequence samples in measurement order
 */
function interpolatedBaselinePairs(sequence: { arm: 'ts' | 'rust'; value: unknown }[]): { ts: number; rust: number }[] {
	const pairs: { ts: number; rust: number }[] = [];
	const usableTs = (i: number) => sequence[i].arm === 'ts' && Number.isFinite(sequence[i].value);
	sequence.forEach((sample, k) => {
		if (sample.arm !== 'rust' || !Number.isFinite(sample.value)) return;
		let before = k - 1;
		while (before >= 0 && !usableTs(before)) before -= 1;
		let after = k + 1;
		while (after < sequence.length && !usableTs(after)) after += 1;
		if (before < 0 || after >= sequence.length) return;
		const low = sequence[before].value as number;
		const high = sequence[after].value as number;
		pairs.push({ ts: low + ((high - low) * (k - before)) / (after - before), rust: sample.value as number });
	});
	return pairs;
}

/**
 * Median increment of a level metric across one reload, by transition (previous arm ->
 * this arm), from each sample's own before/after endpoints. Equal ts->ts and rust->rust
 * increments mean the arms differ in level only; a larger rust->rust increment means
 * memory a Rust load leaves behind after the next reload.
 */
function transitionIncrements(sequence: { arm: 'ts' | 'rust'; before: unknown; after: unknown }[]): Record<string, { n: number; median: number | null }> {
	const groups: Record<string, number[]> = { 'ts->ts': [], 'ts->rust': [], 'rust->ts': [], 'rust->rust': [] };
	for (let k = 1; k < sequence.length; k += 1) {
		const { before, after } = sequence[k];
		if (Number.isFinite(before) && Number.isFinite(after)) groups[`${sequence[k - 1].arm}->${sequence[k].arm}`].push((after as number) - (before as number));
	}
	return Object.fromEntries(Object.entries(groups).map(([key, values]) => [key, { n: values.length, median: values.length ? median(values) : null }]));
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

module.exports = { summarizePaired, markdownTable, median, bootstrapMedianCi, pairOrder, interpolatedBaselinePairs, transitionIncrements };
