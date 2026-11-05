/**
 * Spawns the shared Rust core Worker once per tab and registers it for
 * @openmates/ui services. Imported only from the flag-on branch of
 * +layout.svelte, so default builds never bundle the Worker or the WASM loader.
 */
import {
	createSharedCoreClient,
	registerSharedRustCore,
	type SharedRustCore
} from '@openmates/ui/src/services/rustCore/host/sharedCoreRegistry';

let started: { core: SharedRustCore; unregister: () => void } | null = null;

function spawnSharedWorker(): Worker {
	return new Worker(new URL('./shared.worker.ts', import.meta.url), { type: 'module', name: 'openmates-rust-shared' });
}

/** Idempotent: returns the tab's single shared core, spawning its Worker on first use. */
export function startSharedRustCore(): SharedRustCore {
	if (started) return started.core;
	if (typeof Worker === 'undefined') throw new Error('rust_core_unavailable');
	const core = createSharedCoreClient(spawnSharedWorker);
	started = { core, unregister: registerSharedRustCore(core) };
	return core;
}

/** Terminates the Worker and unregisters it (page teardown). */
export function stopSharedRustCore(): void {
	if (!started) return;
	const { core, unregister } = started;
	started = null;
	unregister();
	core.terminate();
}
