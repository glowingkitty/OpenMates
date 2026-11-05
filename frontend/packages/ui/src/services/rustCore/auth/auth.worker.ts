/// <reference lib="webworker" />
/**
 * Rust web auth Worker (VITE_OPENMATES_RUST_CORE builds only). Loads the shared
 * browser WASM package and runs login/session/logout policy. It performs no
 * Fetch, cookie or storage IO itself; the page executes the described requests.
 */
import { loadBinding } from 'virtual:openmates-rust-core-package';
import { AUTH_PROTOCOL_VERSION } from './authProtocol';
import { installAuthWorker, isRustWebAuthBinding } from './authWorkerRuntime';

const scope = self as unknown as DedicatedWorkerGlobalScope;

loadBinding().then((binding) => {
	if (!isRustWebAuthBinding(binding)) throw new Error('unavailable');
	installAuthWorker(scope, binding);
}).catch(() => {
	scope.postMessage({ v: AUTH_PROTOCOL_VERSION, ready: false });
	scope.close();
});
