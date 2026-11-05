/**
 * Starts the dedicated Rust auth Worker. Loaded only from the flag-on branch of
 * authOperation, so default builds never bundle the Worker or the WASM loader.
 */
import { createAuthClient, RustAuthError, type AuthHttpExecutor, type RustAuthClient } from './authClient';

export function createWorkerAuthClient(execute: AuthHttpExecutor): RustAuthClient {
	if (typeof Worker === 'undefined') throw new RustAuthError('rust_core_unavailable');
	const worker = new Worker(new URL('./auth.worker.ts', import.meta.url), { type: 'module', name: 'openmates-rust-auth' });
	return createAuthClient(worker, execute);
}
