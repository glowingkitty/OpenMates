/**
 * `presentRemote` unit protocol of the shared Rust core Worker (slides presentation
 * remote, `slides.present.remote-*`). The core (packages/openmates-rust
 * `client/shared_items/present_remote.rs`) owns the state format, the embed-key
 * encryption and the ordering rule; the Worker resolves the deck's embed key by id,
 * so keys never reach the page. Requests carry the camelCase state JSON of
 * `presentRemoteClient.ts`; refusals arrive as the core's stable codes
 * (`present_remote_*`, `embed_key_unavailable`) or `protocol`.
 */
import type { UnitProtocol } from '../host/unitPort';

export type PresentRemoteOrigin = 'presenter' | 'remote';

export interface PresentRemoteState {
	embedId: string;
	sessionId: string;
	seq: number;
	index: number;
	step: number;
	notesVisible: boolean;
	presenting: boolean;
	origin: PresentRemoteOrigin;
}

export interface PresentRemoteUnitProtocol extends UnitProtocol {
	encrypt: { request: { state: PresentRemoteState }; response: string };
	decrypt: { request: { embedId: string; ciphertext: string }; response: PresentRemoteState };
	accept: { request: { state: PresentRemoteState }; response: boolean };
}

/** BrowserCoreClient exports of browser_present_remote.rs (JSON text in and out). */
export interface PresentRemoteClient {
	present_remote_encrypt(handle: string, generation: number, stateJson: string): Promise<string>;
	present_remote_decrypt(handle: string, generation: number, embedId: string, ciphertext: string): Promise<string>;
}

/** Worker module export of browser_present_remote.rs. */
export interface PresentRemoteBinding {
	present_remote_accept(stateJson: string): boolean;
}

export function isPresentRemoteBinding(value: unknown): value is PresentRemoteBinding {
	return typeof value === 'object' && value !== null
		&& typeof (value as Record<string, unknown>).present_remote_accept === 'function';
}
