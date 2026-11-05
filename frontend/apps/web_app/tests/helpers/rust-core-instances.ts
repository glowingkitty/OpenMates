/* eslint-disable @typescript-eslint/no-explicit-any -- Playwright Page/Worker handles are untyped in these CommonJS specs. */
/**
 * Bench counters for the shared Rust core Worker (web-rust-core-* specs):
 * live dedicated Workers of the page, how many of them are Rust core Workers,
 * and how many WASM instantiations ran in this page load. Each wasm-bindgen
 * instantiation fetches `openmates_browser_bg*.wasm` once per JS realm
 * (loadBinding is memoized per realm), so the per-realm resource entries count
 * instantiations: the page realm (must stay 0) plus every live Worker realm.
 */
export {};

const WASM_ASSET = 'openmates_browser_bg';
/** Rust core Worker entries: the shared core Worker, the removed dedicated history Worker, the auth Worker. */
const RUST_WORKER = /(shared|production|auth)\.worker/;

async function countWasmEntries(target: any): Promise<number> {
	return target.evaluate((asset: string) => performance.getEntriesByType('resource')
		.filter((entry) => entry.name.includes(asset)).length, WASM_ASSET);
}

/** Worker entry name without directory or content hash, e.g. `shared.worker`. */
function workerName(url: string): string {
	const file = url.split('?')[0].split('/').pop() ?? '';
	return file.replace(/-[A-Za-z0-9_]{6,}\.js$/, '').replace(/\.js$/, '');
}

/** Counts after the current page load settled (call once the chat rendered). */
async function rustCoreInstances(page: any): Promise<{
	dedicatedWorkers: number; rustWorkers: number; sharedWorkerWasm: number; wasmInstantiations: number;
	wasmMainThreadInstantiations: number; workers: { name: string; wasm: number }[];
}> {
	const workers: { name: string; wasm: number }[] = [];
	for (const worker of page.workers()) {
		// A Worker that exited between listing and evaluation holds no instance any more.
		workers.push({ name: workerName(worker.url()), wasm: await countWasmEntries(worker).catch(() => 0) });
	}
	const wasmMainThreadInstantiations = await countWasmEntries(page);
	return {
		dedicatedWorkers: workers.length,
		rustWorkers: workers.filter((worker) => RUST_WORKER.test(worker.name)).length,
		sharedWorkerWasm: workers.filter((worker) => worker.name === 'shared.worker').reduce((sum, worker) => sum + worker.wasm, 0),
		wasmInstantiations: workers.reduce((sum, worker) => sum + worker.wasm, 0) + wasmMainThreadInstantiations,
		wasmMainThreadInstantiations,
		workers
	};
}

module.exports = { rustCoreInstances };
