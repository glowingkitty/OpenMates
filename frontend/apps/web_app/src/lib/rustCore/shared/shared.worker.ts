/// <reference lib="webworker" />
/**
 * The single shared Rust core Worker (VITE_OPENMATES_RUST_CORE builds only).
 * Exactly one `loadBinding()` per realm, loaded lazily on the first `open`, so
 * every unit reuses one WASM instance. Control envelopes arrive on the Worker's
 * own channel; each namespace gets its own transferred MessagePort.
 */
import { loadBinding } from 'virtual:openmates-rust-core-package';
import { createSharedWorkerRouter } from '@openmates/ui/src/services/rustCore/host/sharedWorkerProtocol';
import { preloadSharedUnitModules, SHARED_UNIT_INSTALLERS } from './sharedWorkerUnits';

const scope = self as unknown as DedicatedWorkerGlobalScope;

const router = createSharedWorkerRouter({
	installers: SHARED_UNIT_INSTALLERS,
	loadBinding,
	reply: (reply) => scope.postMessage(reply)
});

scope.addEventListener('message', (event: MessageEvent<unknown>) => {
	if (!scope.isSecureContext) { scope.close(); return; }
	void router.handle(event.data, event.ports);
});

// After startup work has had its turn: unit modules are loaded ahead of their first use.
setTimeout(preloadSharedUnitModules, 3000);
