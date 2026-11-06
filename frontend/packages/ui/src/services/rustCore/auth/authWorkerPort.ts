/**
 * Opens the Rust auth unit on the tab's single shared Rust core Worker. Loaded
 * only from the flag-on branch of authOperation, so default builds never bundle
 * it. The unit is pre-bind (opened outside any generation): login and session
 * restore run before a principal is admitted.
 *
 * Closing the client releases only its unit port. `loadSharedAuthRealm().retire`
 * terminates and respawns the whole shared Worker when no principal is bound,
 * so the WASM memory a key-deriving login touched (derived keys, the Argon2
 * arena) never outlives the login, exactly like the removed dedicated auth
 * Worker that was terminated after use.
 */
import { createAuthClient, RustAuthError, type AuthEndpoint, type AuthHttpExecutor, type RustAuthClient } from './authClient';
import { AUTH_UNIT_CLOSE } from './authProtocol';
import { whenSharedRustCore, type SharedRustCore } from '../host/sharedCoreRegistry';

type Listener = (event: MessageEvent<unknown>) => void;

/** Unit port as the auth client's endpoint; `terminate()` releases this port only. */
function unitEndpoint(core: SharedRustCore, port: MessagePort, onClosed: () => void): AuthEndpoint {
	const errorListeners: Listener[] = [];
	let closed = false;
	const stopCrash = core.onCrash(() => { for (const listener of [...errorListeners]) listener(new MessageEvent('error')); });
	return {
		postMessage(message) { if (!closed) port.postMessage(message); },
		addEventListener(type, listener) {
			if (type === 'error') errorListeners.push(listener);
			else port.addEventListener(type, listener);
			if (type === 'message') port.start();
		},
		terminate() {
			if (closed) return;
			closed = true;
			stopCrash();
			port.postMessage(AUTH_UNIT_CLOSE);
			port.close();
			onClosed();
		},
	};
}

/**
 * Resolves with an auth client on a fresh `auth` unit port. `onClosed` runs once
 * when the client ends (close, protocol failure or Worker crash/terminate).
 */
export async function createSharedAuthClient(execute: AuthHttpExecutor, onClosed: () => void): Promise<RustAuthClient> {
	let core: SharedRustCore;
	let port: MessagePort;
	try {
		core = await whenSharedRustCore();
		port = await core.openUnit('auth', { unbound: true });
	} catch {
		throw new RustAuthError('rust_core_unavailable');
	}
	performance.mark('openmates:rust:auth-unit-open');
	return createAuthClient(unitEndpoint(core, port, onClosed), execute);
}

/**
 * Loads the registered shared core and returns its synchronous retirement:
 * terminate the shared Worker and respawn it with a prewarmed, unbound realm.
 * Without `force` it is skipped while a principal is bound (that realm belongs
 * to a live session); logout passes `force`. Every open unit (including auth
 * clients) is told through `onCrash`. A failed respawn is reported, and the next
 * request spawns the Worker again.
 */
export async function loadSharedAuthRealm(): Promise<{ retire(options: { force: boolean }): void }> {
	const core = await whenSharedRustCore();
	return {
		retire(options) {
			if (!options.force && core.generation !== null) return;
			core.terminate();
			performance.mark('openmates:rust:auth-realm-retired');
			core.prewarm().catch((error: unknown) => console.warn('[RustAuth] shared core respawn failed:',
				error instanceof Error ? error.message : 'unknown'));
		},
	};
}
