/**
 * Page client of the shared Worker's `embedWrite` unit (U9; VITE_OPENMATES_RUST_CORE
 * builds only). Opens the unit in the CURRENT bound generation (the session
 * broker's admission), sends the page's non-extractable master CryptoKey once
 * and returns the typed unit port (EmbedWriteProtocol in embedDataProtocol.ts).
 *
 * Wiring contract for the streamed-embed handlers (coordinator, ws path owner):
 *   1. on chat key load `adoptChatKey`; on synced key rows `adoptEmbedKeyWrapper`;
 *   2. finalized `send_embed_data`: `prepareStreamCompletion` (the Worker persists
 *      the entry + wrappers atomically) -> send `store_payload` / `server_keys` ->
 *      register `embed_ref_registration` and child refs;
 *   3. revision history: `encryptHistoryRow` / `reconcileSealedHistory` /
 *      `adoptCanonicalRow` / `verifyCanonicalHead` around the page's canonical
 *      HTTP reads and diff sends (same order as persistStreamedHistory);
 *   4. `forgetChat` on chat delete/hide/rotation; `close()` before the unbind
 *      of logout/account switch.
 * A crash closes the client (requests reject `unit_closed`). Unbind disposes the
 * Worker-side session and port, but the page end is not told: a request sent
 * after unbind without `close()` fails only by `unit_timeout`.
 */
import type { SharedRustCore } from '../host/sharedCoreRegistry';
import { createUnitPort, type UnitPort } from '../host/unitPort';
import { EMBED_UNIT_CLOSE, type EmbedWriteProtocol } from './embedDataProtocol';

export interface EmbedWriteClient {
	readonly unit: UnitPort<EmbedWriteProtocol>;
	close(): void;
}

export async function openEmbedWriteClient(core: SharedRustCore, masterKey: CryptoKey, signal?: AbortSignal): Promise<EmbedWriteClient> {
	if (core.generation === null) throw new Error('not_bound');
	const raw = await core.openUnit('embedWrite', { signal });
	const unit = createUnitPort<EmbedWriteProtocol>(raw);
	const stopCrashWatch = core.onCrash(() => unit.close());
	const close = () => {
		stopCrashWatch();
		if (unit.closed) return;
		raw.postMessage(EMBED_UNIT_CLOSE);
		unit.close();
	};
	try {
		await unit.request('init', { masterKey }, { signal });
	} catch (error) {
		close();
		throw error;
	}
	return { unit, close };
}
