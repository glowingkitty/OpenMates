/* eslint-disable @typescript-eslint/no-explicit-any -- Playwright Page/CDP handles and bench reports are untyped in these CommonJS specs. */
/* eslint-disable @typescript-eslint/no-require-imports -- Playwright CommonJS specs. */
/**
 * Same-tab reload memory measurement for the TS-vs-Rust web benchmark
 * (VITE_OPENMATES_RUST_CORE=1 build, web-rust-core-* CI lane). Engineering
 * measurement only; it changes no product behaviour. Only sizes and counts leave
 * the browser; no message content is read and nothing is sent.
 *
 * Slope phase (web-rust-core-reload-memory.spec.ts): one context and tab reload
 * the same saved chat, after WARMUP_RELOADS discarded TS reloads (first-load
 * allocations), in ABBA blocks (ts x T, rust x 2T, ts x T). Before, between
 * and after the blocks a checkpoint runs CHECKPOINT_RELOADS TS reloads, each
 * followed by one deterministic (GC-first) memory-infra dump. Memory a load leaves
 * behind survives the GC and shows up at the next checkpoint, so the per-reload
 * slope of each arm is the coefficient of a least-squares fit
 *   level = a + slopeTs * (TS reloads so far) + slopeRust * (Rust reloads so far)
 * over the checkpoint samples, with a seeded residual-bootstrap 95% CI. Gated
 * metrics: retained renderer allocators (PartitionAlloc + malloc + V8 page/Worker
 * heaps + Blink GC) and total process RSS read before each dump. Gate: Rust's slope
 * CI upper bound <= max(TS slope, 0) + 1 MiB per reload. The plain (no GC) RSS of
 * every block reload is fitted the same way plus an arm level term and reported:
 * that is the "+40 MB per reload" the paired bench sees without a forced GC.
 *
 * Level phase (web-rust-core-memory-level.spec.ts): counterbalanced ts/rust pairs
 * (bench-stats pairOrder), each reload followed by the dump; every Rust sample is
 * compared with the TS level interpolated around it (interpolatedBaselinePairs).
 *
 * The memory-infra dump maps tracing buffers, so the RSS read right after it is
 * inflated (bimodal); RSS is therefore read before the dump and allocators from it.
 */
export {};

const { summarizeMemoryDump, processMemory } = require('./bench-profile');
const { pairOrder, interpolatedBaselinePairs, summarizePaired } = require('./bench-stats');
const { rustCoreInstances } = require('./rust-core-instances');
const { armSlopes, slopeVerdict, metricValue, SLOPE_ALLOWANCE_BYTES } = require('./reload-memory-stats');

const MIB = 1024 * 1024;
const SETTLE_MS = 1000;
const CHECKPOINT_RELOADS = 5;
const WARMUP_RELOADS = 3;
/** Reloads that may fail to render the seeded chat before one measured reload is declared failed (loaded pages are still counted). */
const MAX_UNUSABLE_LOADS = 1;
/** Renderer allocator prefixes reported per dump (memory-infra paths, depth 2-3). */
const RENDERER_ALLOCATORS = [
	'partition_alloc/partitions', 'partition_alloc/partitions/buffer', 'partition_alloc/partitions/array_buffer',
	'partition_alloc/partitions/fast_malloc', 'malloc/partitions', 'malloc/allocated_objects',
	'v8/main', 'v8/workers', 'blink_gc/main', 'cc/tile_memory', 'web_cache/Script_resources', 'parkable_strings/<unspecified>'
];
/** Disjoint allocators whose sum is the retained renderer heap (gated). */
const RETAINED_ALLOCATORS = ['partition_alloc/partitions', 'malloc/partitions', 'v8/main', 'v8/workers', 'blink_gc/main'];
const GATED_METRICS = ['retainedBytes', 'totalRssBytes'] as const;

type Arm = 'ts' | 'rust';
type Sample = Record<string, any>;

/** RSS per process type from /proc for the processes Chromium reports. */
async function processRss(browserSession: any): Promise<{ totalRssBytes: number; byType: Record<string, { count: number; rssBytes: number }> }> {
	const byType: Record<string, { count: number; rssBytes: number }> = {};
	let totalRssBytes = 0;
	for (const row of await processMemory(browserSession)) {
		if (row.unavailable || typeof row.rssMiB !== 'number') continue;
		const entry = byType[row.type] ??= { count: 0, rssBytes: 0 };
		entry.count += 1;
		entry.rssBytes += row.rssMiB * MIB;
		totalRssBytes += row.rssMiB * MIB;
	}
	return { totalRssBytes, byType };
}

/** One deterministic (GC-first) memory-infra dump: renderer allocator sizes. */
async function gcDump(page: any, browserSession: any): Promise<{ dumpOk: boolean; allocators: Record<string, number | null>; retainedBytes: number | null }> {
	const browser = page.context().browser();
	await browser.startTracing(undefined, { categories: ['disabled-by-default-memory-infra'] });
	const dump = await browserSession.send('Tracing.requestMemoryDump', { deterministic: true, levelOfDetail: 'detailed' });
	const trace = JSON.parse((await browser.stopTracing()).toString('utf8'));
	const renderer = summarizeMemoryDump(trace, dump?.success ? String(dump.dumpGuid) : null).processes.find((row: any) => row.name === 'Renderer');
	const allocators: Record<string, number | null> = {};
	for (const prefix of RENDERER_ALLOCATORS) {
		const mib = renderer?.allocatorsMiB?.[prefix];
		allocators[prefix] = typeof mib === 'number' ? mib * MIB : null;
	}
	const retained = RETAINED_ALLOCATORS.map((prefix) => allocators[prefix]);
	return { dumpOk: dump?.success === true, allocators, retainedBytes: retained.every((value) => typeof value === 'number') ? retained.reduce((sum, value) => sum + (value as number), 0) : null };
}

/**
 * The TS arm is the flag-off behaviour: besides the history opt-out it must also opt out of
 * Rust crypto (which gates the embedData/embedWrite Worker paths) With
 * the history opt-out alone no Worker session is bound, so embed reads wait for a bind that
 * never comes (embed_write_not_bound) and the embed preview never finishes.
 */
const CRYPTO_OPT_OUT_KEY = 'openmates_rust_core_crypto';
function tsArmOptOutKeys(historyKey: string): string[] {
	return [historyKey, CRYPTO_OPT_OUT_KEY];
}

/** Reloads the chat tab once in `arm`, waits until usable, reads RSS and (with `dump`) the GC-first dump. */
async function measuredReload(page: any, arm: Arm, deps: { browserSession: any; waitAllReady: any; optOutKey: string; pageEvents: string[] }, dump: boolean): Promise<Sample> {
	const failures: string[] = [];
	let ready: Record<string, any>;
	for (;;) {
		await page.evaluate(([keys, ts]: [string[], boolean]) => { for (const key of keys) { if (ts) localStorage.setItem(key, 'ts'); else localStorage.removeItem(key); } }, [tsArmOptOutKeys(deps.optOutKey), arm === 'ts']);
		await page.reload();
		ready = await page.evaluate(deps.waitAllReady, arm === 'rust');
		if (ready.chatRenderedMs !== undefined && ready.embedReadyMs !== undefined) break;
		const embeds = await page.evaluate(() => [...document.querySelectorAll('[data-testid="embed-preview"]')].map((node) => `${(node as HTMLElement).dataset.appId}:${(node as HTMLElement).dataset.status}`));
		failures.push(`${arm}: reload did not become usable (marker ${ready.marker}; rendered=${ready.chatRenderedMs !== undefined}; embeds=${JSON.stringify(embeds)}; page events: ${JSON.stringify(deps.pageEvents.slice(-25))})`);
		// A reload that never rendered still loaded the page (its memory is real, so it is counted); a repeat failure is a defect, not noise.
		if (failures.length > MAX_UNUSABLE_LOADS) throw new Error(failures.join('\n'));
	}
	if (arm === 'rust' && !String(ready.marker).startsWith('rust:')) throw new Error(`rust: history marker ${ready.marker}`);
	if (arm === 'ts' && ready.marker !== null) throw new Error(`ts: history marker ${ready.marker}`);
	await page.waitForTimeout(SETTLE_MS);
	const instances = await rustCoreInstances(page);
	const rss = await processRss(deps.browserSession);
	const targets = await deps.browserSession.send('Target.getTargets');
	const targetTypes: Record<string, number> = {};
	for (const info of targets.targetInfos ?? []) targetTypes[info.type] = (targetTypes[info.type] ?? 0) + 1;
	return {
		arm, dumped: dump, chatRenderedMs: ready.chatRenderedMs, unusableLoads: failures.length, unusableDetail: failures,
		totalRssBytes: rss.totalRssBytes,
		rendererRssBytes: rss.byType.renderer?.rssBytes ?? null,
		rendererCount: rss.byType.renderer?.count ?? 0,
		byType: rss.byType,
		...(dump ? await gcDump(page, deps.browserSession) : {}),
		targetTypes,
		dedicatedWorkers: instances.dedicatedWorkers, rustWorkers: instances.rustWorkers,
		wasmInstantiations: instances.wasmInstantiations, wasmMainThreadInstantiations: instances.wasmMainThreadInstantiations
	};
}

function rssMetrics(samples: Sample[]): string[] {
	const types = new Set<string>();
	for (const sample of samples) for (const type of Object.keys(sample.byType ?? {})) types.add(type);
	return ['totalRssBytes', 'rendererRssBytes', ...[...types].sort().map((type) => `byType.${type}.rssBytes`)];
}

function dumpMetrics(samples: Sample[]): string[] {
	return ['retainedBytes', ...rssMetrics(samples), ...RENDERER_ALLOCATORS.map((prefix) => `allocators.${prefix}`)];
}

/** Per-reload log line, so a run cut short still leaves the numbers in the job log. */
function progressLine(phase: string, sample: Sample): Record<string, any> {
	const mib = (value: unknown) => (typeof value === 'number' ? Math.round((value / MIB) * 10) / 10 : null);
	return {
		phase, arm: sample.arm, ts: sample.tsReloads, rust: sample.rustReloads, unusableLoads: sample.unusableLoads,
		totalMiB: mib(sample.totalRssBytes), rendererMiB: mib(sample.rendererRssBytes), retainedMiB: mib(sample.retainedBytes),
		byTypeMiB: Object.fromEntries(Object.entries(sample.byType ?? {}).map(([type, value]: [string, any]) => [type, mib(value.rssBytes)])),
		...(sample.dumped ? { allocatorsMiB: Object.fromEntries(Object.entries(sample.allocators ?? {}).map(([key, value]) => [key, mib(value)])) } : {}),
		workers: sample.dedicatedWorkers, rustWorkers: sample.rustWorkers, wasm: sample.wasmInstantiations, targets: sample.targetTypes
	};
}

/**
 * Runs the slope phase (`blockSize` > 0) and/or the level phase (`levelPairs` > 0)
 * on a page that already shows the seeded chat `chatId`. Returns the report; the
 * caller attaches and gates it.
 */
async function runReloadMemory(page: any, chatId: string, options: {
	blockSize: number; levelPairs: number; waitAllReady: any; optOutKey: string; chatUrl: (hash: string) => string; log: (step: string, data?: any) => void;
}): Promise<Record<string, any>> {
	const browserSession = await page.context().browser().newBrowserCDPSession();
	// Failed HTTP responses, page errors and console errors of the tab; only named in the error of an unusable reload.
	const pageEvents: string[] = [];
	const onResponse = (response: any) => { if (response.status() >= 400) pageEvents.push(`http ${response.status()} ${new URL(response.url()).pathname}`.slice(0, 200)); };
	const onPageError = (error: Error) => { pageEvents.push(`pageerror ${error.message}`.slice(0, 200)); };
	const onConsole = (message: any) => { if (message.type() === 'error') pageEvents.push(`console ${message.text()}`.slice(0, 200)); };
	page.on('response', onResponse);
	page.on('pageerror', onPageError);
	page.on('console', onConsole);
	const deps = { browserSession, waitAllReady: options.waitAllReady, optOutKey: options.optOutKey, pageEvents };
	const counts = { ts: 0, rust: 0 };
	const reload = async (phase: string, arm: Arm, dump: boolean, extra: Sample = {}): Promise<Sample> => {
		const sample = await measuredReload(page, arm, deps, dump);
		counts[arm] += 1 + sample.unusableLoads;
		Object.assign(sample, { phase, tsReloads: counts.ts, rustReloads: counts.rust }, extra);
		options.log('reload', progressLine(phase, sample));
		return sample;
	};
	const checkpoints: Sample[] = [];
	const plain: Sample[] = [];
	const level: Sample[] = [];
	try {
		await page.goto(options.chatUrl(`/#chat-id=${chatId}`));
		if (options.blockSize > 0) {
			// One-time first-load allocations (caches, lazily compiled code) are not per-reload growth.
			for (let k = 0; k < WARMUP_RELOADS; k += 1) await reload('warmup', 'ts', false);
			const checkpoint = async (id: number) => {
				for (let k = 0; k < CHECKPOINT_RELOADS; k += 1) checkpoints.push(await reload('checkpoint', 'ts', true, { checkpoint: id, afterGc: k > 0 }));
			};
			await checkpoint(0);
			const blocks: [Arm, number][] = [['ts', options.blockSize], ['rust', 2 * options.blockSize], ['ts', options.blockSize]];
			for (const [index, [arm, size]] of blocks.entries()) {
				for (let k = 0; k < size; k += 1) plain.push(await reload('plain', arm, false));
				await checkpoint(index + 1);
			}
		}
		for (let index = 0; options.levelPairs > 0 && index <= options.levelPairs; index += 1) {
			for (const arm of pairOrder(index)) level.push(await reload('level', arm, true, { warmUp: index === 0 }));
		}
		if (level.length && level[level.length - 1].arm === 'rust') level.push(await reload('level', 'ts', true, { trailing: true }));
	} finally {
		page.off('response', onResponse);
		page.off('pageerror', onPageError);
		page.off('console', onConsole);
		await page.evaluate((keys: string[]) => keys.forEach((key) => localStorage.removeItem(key)), tsArmOptOutKeys(options.optOutKey)).catch(() => undefined);
		await browserSession.detach().catch(() => undefined);
	}

	const retained: Record<string, any> = {};
	if (checkpoints.length) {
		// RSS is read before the dump, so only checkpoint reloads that follow a GC-first dump count for RSS.
		const rssMetricSet = new Set(rssMetrics(checkpoints));
		for (const metric of dumpMetrics(checkpoints)) retained[metric] = armSlopes(rssMetricSet.has(metric) ? checkpoints.filter((sample) => sample.afterGc) : checkpoints, metric, false);
		for (const metric of GATED_METRICS) retained[metric].gate = slopeVerdict(retained[metric]);
	}
	const plainSlopes: Record<string, any> = {};
	if (plain.length) for (const metric of rssMetrics(plain)) plainSlopes[metric] = armSlopes(plain, metric, true);

	const levels: Record<string, any> = {};
	if (level.length) {
		for (const metric of dumpMetrics(level)) {
			levels[metric] = summarizePaired(interpolatedBaselinePairs(level.map((sample) => ({ arm: sample.arm, value: sample.warmUp && sample.arm === 'rust' ? null : metricValue(sample, metric) }))), { mode: 'difference', gate: false });
		}
	}
	const all = [...checkpoints, ...plain, ...level];
	const maxOf = (arm: Arm, key: string) => Math.max(0, ...all.filter((sample) => sample.arm === arm).map((sample) => Number(sample[key]) || 0));
	const counters = (arm: Arm) => ({ maxRustWorkers: maxOf(arm, 'rustWorkers'), maxWasmInstantiations: maxOf(arm, 'wasmInstantiations'), maxWasmMainThread: maxOf(arm, 'wasmMainThreadInstantiations'), maxDedicatedWorkers: maxOf(arm, 'dedicatedWorkers'), maxRenderers: maxOf(arm, 'rendererCount') });
	return {
		method: 'same-tab reloads; retained slopes = least squares of GC-first checkpoint levels on cumulative TS/Rust reload counts (ABBA blocks ts,rust x2,ts); plain = same fit with an arm level term on un-GCed RSS; levels = Rust vs interpolated TS on counterbalanced pairs; 95% CIs by seeded bootstrap',
		blockSize: options.blockSize, checkpointReloads: CHECKPOINT_RELOADS, levelPairs: options.levelPairs, slopeAllowanceBytes: SLOPE_ALLOWANCE_BYTES,
		retainedSlopes: retained, plainSlopes, levels,
		liveCounts: { ts: counters('ts'), rust: counters('rust') },
		unusableLoads: { ts: all.filter((sample) => sample.arm === 'ts').reduce((sum, sample) => sum + sample.unusableLoads, 0), rust: all.filter((sample) => sample.arm === 'rust').reduce((sum, sample) => sum + sample.unusableLoads, 0) },
		samples: all.map(({ byType, ...rest }) => ({ ...rest, byTypeMiB: Object.fromEntries(Object.entries(byType ?? {}).map(([type, value]: [string, any]) => [type, Math.round(value.rssBytes / MIB)])) }))
	};
}

/** Markdown summary in MiB (per reload for slopes). */
function reloadMemoryTable(report: Record<string, any>): string {
	const mib = (value: unknown) => (typeof value === 'number' ? (value / MIB).toFixed(2) : '-');
	const ci = (pair: unknown) => (Array.isArray(pair) ? `[${mib(pair[0])}, ${mib(pair[1])}]` : '-');
	const rows = ['| phase | metric | TS MiB/reload [95% CI] | Rust MiB/reload [95% CI] | n | verdict |', '|---|---|---|---|---|---|'];
	for (const [phase, slopes] of [['retained (GC)', report.retainedSlopes], ['plain (no GC)', report.plainSlopes]] as [string, Record<string, any>][]) {
		for (const [metric, s] of Object.entries(slopes)) {
			rows.push(`| ${phase} | ${metric} | ${mib(s.ts?.slope)} ${ci(s.ts?.ci95)} | ${mib(s.rust?.slope)} ${ci(s.rust?.ci95)} | ${s.n} | ${s.gate?.verdict ?? (s.rustLevel !== undefined ? `rust level ${mib(s.rustLevel)}` : 'reported')} |`);
		}
	}
	if (Object.keys(report.levels).length) {
		rows.push('', '| level metric | pairs | TS median MiB | Rust median MiB | Rust-TS MiB [95% CI] |', '|---|---|---|---|---|');
		for (const [metric, s] of Object.entries(report.levels) as [string, any][]) rows.push(`| ${metric} | ${s.pairs} | ${mib(s.tsMedian)} | ${mib(s.rustMedian)} | ${mib(s.median)} ${ci(s.ci95)} |`);
	}
	return rows.join('\n');
}

module.exports = { runReloadMemory, reloadMemoryTable, GATED_METRICS };
