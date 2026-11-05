/**
 * `core` namespace installer of the shared Rust core Worker (refactored from the
 * removed dedicated production.worker.ts entry).
 *
 * One installer call = one Worker-side core dispatcher (its own Rust client) on
 * the unit port, sharing the realm's single WASM binding with every other unit.
 * Handshake on the unit port, unchanged from the dedicated Worker: the page posts
 * the closed transport bootstrap (validProductionBootstrap, expectedPrincipal must
 * equal the generation's bound principal), the unit installs the dispatcher and
 * answers `{version:1,ready:true}` or `{version:1,ready:false,code}` and closes.
 * `CORE_UNIT_CLOSE` (sessionBroker lease close) disposes the dispatcher and closes
 * the port without touching the shared Worker.
 *
 * Recovery port position: ports[1] (page `extraPorts[0]`). The Rust recovery
 * capture accepts only the first trusted bootstrap event of a dedicated Worker
 * realm (once per realm), so a shared-realm unit refuses it (`install_failed`)
 * instead of silently dropping recovery. Builds whose binding exposes the
 * initial-sync startup store need that recovery capture and are refused too,
 * exactly as the dedicated entry refused them without a recovery port.
 */
import { artifact } from 'virtual:openmates-rust-core-package';
import { validProductionBootstrap } from '../productionBootstrap';
import { installBrowserCoreWorker } from '@openmates/ui/src/services/rustCore/workerRuntime';
import type { BrowserCoreBinding, WorkerEndpoint } from '@openmates/ui/src/services/rustCore/workerRuntime';
import type { UnitInstallContext } from '@openmates/ui/src/services/rustCore/host/sharedWorkerProtocol';
import { isCoreUnitClose } from '@openmates/ui/src/services/rustCore/host/sessionBroker';

const FAILURE_CODE = /^[a-z][a-z0-9_]{0,63}$/;

export function installCoreUnit(context: UnitInstallContext): () => void {
	const scope = self as unknown as DedicatedWorkerGlobalScope;
	const generated = context.binding as BrowserCoreBinding;
	if (context.ports.length !== 1 || context.principal === null) throw new Error('unavailable');
	if (typeof generated.PreparedBrowserProfile?.from_existing_key !== 'function') throw new Error('unavailable');
	if (typeof generated.capture_initial_sync_store === 'function') throw new Error('unavailable');
	const port = context.ports[0];
	let started = false;
	let disposeRuntime: (() => void) | null = null;
	let disposed = false;
	const dispose = () => {
		if (disposed) return;
		disposed = true;
		port.removeEventListener('message', control);
		disposeRuntime?.();
		disposeRuntime = null;
		port.close();
	};
	// Registered before the dispatcher's listener, so the close frame never reaches it.
	function control(event: MessageEvent<unknown>): void {
		if (isCoreUnitClose(event.data)) {
			event.stopImmediatePropagation();
			dispose();
			return;
		}
		if (started) return;
		started = true;
		const configuration = event.data;
		if (!validProductionBootstrap(configuration, scope.location.origin, artifact)
			|| configuration.expectedPrincipal.toLowerCase() !== context.principal!.toLowerCase() || event.ports.length > 0) {
			port.postMessage({ version: 1, ready: false, code: 'bootstrap_failed' });
			dispose();
			return;
		}
		try {
			disposeRuntime = installBrowserCoreWorker(port as unknown as WorkerEndpoint, generated,
				{ apiUrl: configuration.apiUrl, appOrigin: configuration.appOrigin, sessionId: configuration.sessionId,
					admission: 'existing_key', expectedPrincipal: configuration.expectedPrincipal }, scope.navigator.locks);
			port.postMessage({ version: 1, ready: true });
		} catch (error) {
			const message = error instanceof Error ? error.message : '';
			port.postMessage({ version: 1, ready: false, code: FAILURE_CODE.test(message) ? message : 'bootstrap_failed' });
			dispose();
		}
	}
	port.addEventListener('message', control);
	port.start();
	context.signal.addEventListener('abort', dispose, { once: true });
	return dispose;
}
