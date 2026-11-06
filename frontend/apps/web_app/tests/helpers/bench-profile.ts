/* eslint-disable @typescript-eslint/no-explicit-any -- Playwright Page/Worker/CDP handles are untyped in these CommonJS specs. */
/* eslint-disable @typescript-eslint/no-require-imports -- Playwright CommonJS specs. */
/**
 * Opt-in attribution profile for the interleaved TS-vs-Rust web benchmark
 * (web-rust-core-bench.spec.ts with OPENMATES_BENCH_PROFILE=1, or the
 * web-rust-core-profile.spec.ts entry). Measurement only; it changes no product
 * behaviour. Per profiled reload it captures:
 *   - a Chromium trace with the V8 sampling profiler: top self-time functions and
 *     top trace events (inclusive, by name) per thread, wasm compile/cache events;
 *   - per-process RSS/PSS/anonymous memory from /proc (Linux runner);
 *   - WebAssembly.Memory byteLength of each Rust Worker (automation-only hook in
 *     the Rust core package loader) at instantiation and after the chat rendered;
 *   - fixed-name `openmates:rust:*` marks/measures of the page and every Worker;
 *   - the WASM asset size (raw/brotli) and its served Content-Type.
 * Only summaries leave the browser; no message content is ever read.
 */
export {};

const fs = require('node:fs');
const { brotliCompressSync, gzipSync, constants } = require('node:zlib');

const TRACE_CATEGORIES = [
	'disabled-by-default-v8.cpu_profiler', 'v8', 'v8.wasm', 'disabled-by-default-v8.wasm.detailed',
	'devtools.timeline', 'disabled-by-default-devtools.timeline', 'blink', 'toplevel'
];
const TOP = 25;

function round(value: number): number {
	return Math.round(value * 10) / 10;
}

function topEntries(map: Map<string, number>, limit = TOP): { name: string; ms: number }[] {
	return [...map.entries()].sort((a, b) => b[1] - a[1]).slice(0, limit).map(([name, ms]) => ({ name, ms: round(ms) }));
}

/** Summarizes a Chromium trace: per thread, top self-time JS/WASM functions and top events. */
function summarizeTrace(trace: any): Record<string, any> {
	const events: any[] = Array.isArray(trace) ? trace : trace.traceEvents ?? [];
	const threadNames = new Map<string, string>();
	for (const event of events) {
		if (event.ph === 'M' && event.name === 'thread_name') threadNames.set(`${event.pid}:${event.tid}`, String(event.args?.name ?? ''));
	}
	const threadOf = (event: any) => `${event.pid}:${event.tid}`;
	// V8 sampling profiles: Profile (start) + ProfileChunk events keyed by pid+id.
	const profiles = new Map<string, { thread: string; nodes: Map<number, string>; self: Map<string, number> }>();
	const eventTotals = new Map<string, Map<string, number>>();
	const wasm = new Map<string, { count: number; ms: number }>();
	for (const event of events) {
		if (event.name === 'Profile' || event.name === 'ProfileChunk') {
			const key = `${event.pid}:${event.id}`;
			let profile = profiles.get(key);
			if (!profile) {
				profile = { thread: threadOf(event), nodes: new Map(), self: new Map() };
				profiles.set(key, profile);
			}
			const cpuProfile = event.args?.data?.cpuProfile;
			for (const node of cpuProfile?.nodes ?? []) {
				const frame = node.callFrame ?? {};
				const url = String(frame.url ?? '').split('?')[0].split('/').pop() ?? '';
				profile.nodes.set(node.id, `${frame.functionName || '(anonymous)'}${url ? ` @${url}` : ''}`);
			}
			const samples: number[] = cpuProfile?.samples ?? [];
			const deltas: number[] = event.args?.data?.timeDeltas ?? [];
			for (let index = 0; index < samples.length; index += 1) {
				const name = profile.nodes.get(samples[index]) ?? '(unknown)';
				const ms = (deltas[index + 1] ?? deltas[index] ?? 0) / 1000;
				if (ms > 0) profile.self.set(name, (profile.self.get(name) ?? 0) + ms);
			}
			continue;
		}
		if (event.ph !== 'X' || typeof event.dur !== 'number') continue;
		const thread = threadOf(event);
		const totals = eventTotals.get(thread) ?? new Map<string, number>();
		totals.set(event.name, (totals.get(event.name) ?? 0) + event.dur / 1000);
		eventTotals.set(thread, totals);
		if (/wasm/i.test(event.name)) {
			const entry = wasm.get(event.name) ?? { count: 0, ms: 0 };
			entry.count += 1;
			entry.ms += event.dur / 1000;
			wasm.set(event.name, entry);
		}
	}
	const threads: Record<string, any> = {};
	const label = (thread: string) => `${threadNames.get(thread) || 'thread'} (${thread})`;
	const selfByThread = new Map<string, Map<string, number>>();
	for (const profile of profiles.values()) {
		const merged = selfByThread.get(profile.thread) ?? new Map<string, number>();
		for (const [name, ms] of profile.self) merged.set(name, (merged.get(name) ?? 0) + ms);
		selfByThread.set(profile.thread, merged);
	}
	for (const [thread, self] of selfByThread) {
		const entry = threads[label(thread)] ??= {};
		entry.sampledMs = round([...self.values()].reduce((sum, ms) => sum + ms, 0));
		entry.topSelf = topEntries(self);
	}
	for (const [thread, totals] of eventTotals) {
		const entry = threads[label(thread)] ??= {};
		entry.topEvents = topEntries(totals, 15);
	}
	return {
		threads: Object.fromEntries(Object.entries(threads).filter(([, value]: [string, any]) => (value.sampledMs ?? 0) > 1 || value.topEvents?.[0]?.ms > 5)),
		wasmEvents: [...wasm.entries()].map(([name, value]) => ({ name, count: value.count, ms: round(value.ms) }))
	};
}

/** Per-process memory from /proc for the processes Chromium reports (Linux runner only). */
async function processMemory(browserSession: any): Promise<any[]> {
	const info = await browserSession.send('SystemInfo.getProcessInfo');
	return (info.processInfo ?? []).map((row: any) => {
		const result: Record<string, any> = { type: row.type, cpuSeconds: row.cpuTime };
		try {
			const rollup = fs.readFileSync(`/proc/${row.id}/smaps_rollup`, 'utf8');
			for (const field of ['Rss', 'Pss', 'Anonymous']) {
				const match = new RegExp(`^${field}:\\s+(\\d+) kB$`, 'm').exec(rollup);
				if (match) result[`${field.toLowerCase()}MiB`] = round(Number(match[1]) / 1024);
			}
		} catch {
			result.unavailable = true;
		}
		return result;
	});
}

async function workerSnapshots(page: any): Promise<any[]> {
	const out: any[] = [];
	for (const worker of page.workers()) {
		const name = (worker.url().split('?')[0].split('/').pop() ?? '').replace(/-[A-Za-z0-9_-]{6,}\.js$/, '');
		const snapshot = await worker.evaluate(() => ({
			timeOrigin: performance.timeOrigin,
			wasmBytes: typeof (globalThis as any).__openmatesRustCoreWasmBytes === 'function' ? (globalThis as any).__openmatesRustCoreWasmBytes() : null,
			entries: performance.getEntries().filter((entry) => entry.name.startsWith('openmates:rust:'))
				.map((entry) => ({ name: entry.name, type: entry.entryType, start: Math.round(entry.startTime * 10) / 10, ms: Math.round(entry.duration * 10) / 10,
					...((entry as PerformanceMark).detail?.wasmBytes ? { wasmBytes: (entry as PerformanceMark).detail.wasmBytes } : {}) }))
		})).catch(() => null);
		out.push({ name, ...(snapshot ?? { unavailable: true }) });
	}
	return out;
}

/** Aggregates the worker measures by name (count, total ms) for compact tables. */
function measureTotals(entries: any[]): Record<string, { count: number; ms: number }> {
	const totals: Record<string, { count: number; ms: number }> = {};
	for (const entry of entries ?? []) {
		if (entry.type !== 'measure') continue;
		const total = totals[entry.name] ??= { count: 0, ms: 0 };
		total.count += 1;
		total.ms = round(total.ms + entry.ms);
	}
	return totals;
}

async function wasmAsset(page: any, workers: any[]): Promise<Record<string, any> | null> {
	for (const worker of workers) {
		const url = await worker.evaluate(() => performance.getEntriesByType('resource').map((entry) => entry.name)
			.find((name) => name.includes('openmates_browser_bg'))).catch(() => undefined);
		if (!url) continue;
		const response = await page.request.get(url);
		const body: Buffer = await response.body();
		return {
			contentType: response.headers()['content-type'] ?? null,
			rawBytes: body.length,
			gzipBytes: gzipSync(body, { level: 9 }).length,
			brotliBytes: brotliCompressSync(body, { params: { [constants.BROTLI_PARAM_QUALITY]: 6 } }).length
		};
	}
	return null;
}

/** One profiler per bench run; begin/end wrap exactly one reload sample. */
async function createBenchProfiler(page: any): Promise<{
	begin(): Promise<void>;
	end(): Promise<Record<string, any>>;
	close(): Promise<void>;
}> {
	const browser = page.context().browser();
	const browserSession = await browser.newBrowserCDPSession();
	return {
		async begin() {
			await browser.startTracing(page, { categories: TRACE_CATEGORIES });
		},
		async end() {
			const trace = JSON.parse((await browser.stopTracing()).toString('utf8'));
			const workers = await workerSnapshots(page);
			const pageEntries = await page.evaluate(() => performance.getEntries().filter((entry) => entry.name.startsWith('openmates:rust:'))
				.map((entry) => ({ name: entry.name, type: entry.entryType, start: Math.round(entry.startTime * 10) / 10, ms: Math.round(entry.duration * 10) / 10 })));
			return {
				trace: summarizeTrace(trace),
				processes: await processMemory(browserSession),
				wasmBytesAfterInstantiate: workers.flatMap((worker) => (worker.entries ?? [])
					.filter((entry: any) => entry.name === 'openmates:rust:wasm-instantiate-end').map((entry: any) => ({ name: worker.name, wasmBytes: entry.wasmBytes ?? null }))),
				workers: workers.map((worker) => ({ ...worker, measureTotals: measureTotals(worker.entries) })),
				pageMarks: pageEntries,
				wasmAsset: await wasmAsset(page, page.workers())
			};
		},
		async close() {
			await browserSession.detach().catch(() => undefined);
		}
	};
}

module.exports = { createBenchProfiler, summarizeTrace };
