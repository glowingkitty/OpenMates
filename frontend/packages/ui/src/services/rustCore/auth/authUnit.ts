/**
 * `auth` namespace installer of the shared Rust core Worker (refactored from the
 * removed dedicated auth.worker.ts entry). Runs login/session/logout policy on
 * the realm's single WASM binding; it performs no Fetch, cookie or storage IO
 * itself (the page executes the requests Rust describes).
 *
 * Pre-bind: the page opens it outside any generation (login runs before a
 * principal exists), so the router never hands it a principal and unbind does
 * not close it. It holds no per-account state between calls; the realm itself
 * is terminated by the page after a key-deriving login and on logout.
 *
 * Unit port protocol: unchanged auth protocol v1 (authProtocol.ts). The unit
 * posts `{v:1,ready:true}` once installed. `AUTH_UNIT_CLOSE` or any malformed
 * frame disposes the dispatcher (in-flight logins are freed) and closes the port.
 */
import { isAuthUnitClose } from './authProtocol';
import { installAuthWorker, isRustWebAuthBinding } from './authWorkerRuntime';
import type { UnitInstallContext } from '../host/sharedWorkerProtocol';

export function installAuthUnit(context: UnitInstallContext): () => void {
	if (context.ports.length !== 1 || !isRustWebAuthBinding(context.binding)) throw new Error('unavailable');
	const port = context.ports[0];
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
	function control(event: MessageEvent<unknown>): void {
		if (!isAuthUnitClose(event.data)) return;
		event.stopImmediatePropagation();
		dispose();
	}
	// Registered first so the close frame never reaches the auth dispatcher.
	port.addEventListener('message', control);
	disposeRuntime = installAuthWorker({
		postMessage: (message) => { if (!disposed) port.postMessage(message); },
		addEventListener: (type, listener) => port.addEventListener(type, listener),
		close: dispose,
	}, context.binding);
	port.start();
	context.signal.addEventListener('abort', dispose, { once: true });
	return dispose;
}
