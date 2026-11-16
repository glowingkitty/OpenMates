// Registers the Rust web crypto facades over the shared Rust core Worker's
// `crypto` unit (VITE_OPENMATES_RUST_CORE builds only; called from
// sharedWorkerStart, which only the root layout's flag guard imports, so
// default builds contain none of this). After registration the TS crypto
// modules (MessageEncryptor, MetadataEncryptor, share/embed-share/short-URL,
// media, chat-key write guard) delegate to Rust. The unit port opens lazily on
// the first crypto call. No WASM is instantiated on the page.
import type { SharedRustCore } from '@openmates/ui/src/services/rustCore/host/sharedCoreRegistry';
import { registerRustWebCrypto, type WebCryptoClient } from '@openmates/ui/src/services/rustCore/crypto/webCryptoClient';
import { createSharedCryptoEndpoint } from '@openmates/ui/src/services/rustCore/crypto/sharedCryptoEndpoint';

declare global {
	interface Window {
		/** Read-only call/failure counters for diagnostics and E2E assertions. */
		__openmatesRustCryptoStats?: () => WebCryptoClient['stats'];
		/** E2E proof hooks (corpus + benchmark); automation-controlled browsers only. */
		__openmatesRustCryptoProof?: () => Promise<typeof import('./testing/webCryptoProof')>;
	}
}

let installed: WebCryptoClient | null = null;

export function installRustWebCrypto(core: SharedRustCore): WebCryptoClient | null {
	if (installed) return installed;
	const client = registerRustWebCrypto(() => createSharedCryptoEndpoint(core));
	installed = client;
	window.__openmatesRustCryptoStats = () => structuredClone(client.stats);
	// Test-only harness: installed only under browser automation (Playwright sets
	// navigator.webdriver), so user sessions never expose the proof hooks.
	if (navigator.webdriver) window.__openmatesRustCryptoProof = () => import('./testing/webCryptoProof');
	return client;
}
