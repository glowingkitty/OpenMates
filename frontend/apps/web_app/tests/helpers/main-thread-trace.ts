/* eslint-disable @typescript-eslint/no-explicit-any -- Playwright Page handles are untyped in these CommonJS specs. */
/**
 * Page-realm main-thread trace for the web-rust-core-* open-to-rendered benches.
 *
 * Installed as an init script (before any app script), it records per page load:
 * - long tasks (start, duration in ms since navigation start);
 * - page-realm IndexedDB requests: opens, `databases()` calls and store/index
 *   reads, each as (label, start, time to its first success). Labels are fixed
 *   database/store names, never keys or values.
 * Worker-realm IndexedDB and tasks are not visible here by design: the trace
 * shows what competes with the TS boot and render on the page's own thread.
 */
export {};

function installMainThreadTrace(): void {
	const trace: { longTasks: number[][]; idb: Array<[string, number, number]> } = { longTasks: [], idb: [] };
	(window as unknown as { __mainThreadTrace: typeof trace }).__mainThreadTrace = trace;
	try {
		new PerformanceObserver((list) => {
			for (const entry of list.getEntries()) trace.longTasks.push([Math.round(entry.startTime), Math.round(entry.duration)]);
		}).observe({ type: 'longtask', buffered: true });
	} catch {
		// Long task timing is Chromium-only; other engines record no tasks.
	}
	const record = (label: string, request: IDBRequest) => {
		const started = performance.now();
		request.addEventListener('success', () => trace.idb.push([label, Math.round(started), Math.round(performance.now() - started)]), { once: true });
	};
	const wrap = (proto: any, method: string, label: (target: any) => string) => {
		const original = proto[method];
		if (typeof original !== 'function') return;
		proto[method] = function (this: any, ...args: unknown[]) {
			const request = original.apply(this, args);
			record(`${method}:${label(this)}`, request);
			return request;
		};
	};
	for (const method of ['get', 'getAll', 'getAllKeys', 'count', 'openCursor', 'openKeyCursor', 'put', 'add', 'delete']) {
		wrap(IDBObjectStore.prototype, method, (store) => store.name);
		if (!['put', 'add', 'delete'].includes(method)) wrap(IDBIndex.prototype, method, (index) => `${index.objectStore.name}.${index.name}`);
	}
	const open = IDBFactory.prototype.open;
	IDBFactory.prototype.open = function (this: IDBFactory, name: string, version?: number) {
		const request = open.call(this, name, version as number);
		record(`open:${name}`, request);
		return request;
	};
	const databases = IDBFactory.prototype.databases;
	if (typeof databases === 'function') {
		IDBFactory.prototype.databases = function (this: IDBFactory) {
			const started = performance.now();
			const pending = databases.call(this);
			void pending.then(() => trace.idb.push(['databases', Math.round(started), Math.round(performance.now() - started)]), () => undefined);
			return pending;
		};
	}
}

/** Summary of the current load up to `until` (ms since navigation start), split at `split`. */
async function readMainThreadTrace(page: any, split: number | null, until: number | null): Promise<Record<string, unknown>> {
	return page.evaluate(([splitAt, untilAt]: [number | null, number | null]) => {
		const trace = (window as unknown as { __mainThreadTrace?: { longTasks: number[][]; idb: Array<[string, number, number]> } }).__mainThreadTrace;
		if (!trace) return { available: false };
		const end = untilAt ?? Number.POSITIVE_INFINITY, cut = splitAt ?? end;
		const tasks = trace.longTasks.filter(([start]) => start <= end);
		const sum = (rows: number[][]) => rows.reduce((total, [, duration]) => total + duration, 0);
		const idb = trace.idb.filter(([, start]) => start <= end);
		const byLabel: Record<string, [number, number]> = {};
		for (const [label, , duration] of idb) {
			const row = byLabel[label] ??= [0, 0];
			row[0]++; row[1] += duration;
		}
		return {
			available: true,
			longTaskMsBeforeSplit: sum(tasks.filter(([start]) => start < cut)),
			longTaskMsAfterSplit: sum(tasks.filter(([start]) => start >= cut)),
			longTasks: tasks.slice(0, 40),
			idbBeforeSplit: idb.filter(([, start]) => start < cut).length,
			idbAfterSplit: idb.filter(([, start]) => start >= cut).length,
			idbByLabel: byLabel,
			idbTimeline: idb.slice(0, 120)
		};
	}, [split, until]);
}

module.exports = { installMainThreadTrace, readMainThreadTrace };
