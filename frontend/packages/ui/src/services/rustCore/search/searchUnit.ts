/**
 * `search` namespace installer of the shared Rust core Worker.
 *
 * Holds the chat message search index in the realm's single WASM binding
 * (`ChatSearchIndex`, packages/openmates-rust/src/web_search_chats.rs) next to
 * the data: entries cross once when a chat is (re)indexed, a query crosses as
 * text plus chat handles, and only flat result rows (`Uint32Array`) go back.
 *
 * The unit holds only plaintext the page already holds and no key material.
 * It may open unbound for signed-out public chats; the page reopens it under
 * the current generation after login, so unbind closes the account's index,
 * and it sends `clear` on logout before the realm is terminated.
 *
 * Unit port protocol: searchUnitProtocol.ts over unitPort.ts.
 */
import { serveUnitPort, UnitRefusal } from '../host/unitPort';
import type { UnitInstallContext } from '../host/sharedWorkerProtocol';
import { isSearchRequest, type SearchUnitProtocol } from './searchUnitProtocol';

/** The wasm-bindgen class surface this unit needs. */
export interface ChatSearchIndexBinding {
	reset_chat(handle: number): void;
	push_entry(handle: number, messageId: string, text: string, embedId: string, embedTitled: boolean): void;
	remove_chat(handle: number): void;
	clear(): void;
	chat_count(): number;
	search(query: string, handles: Uint32Array, includeEmbeds: boolean): Uint32Array;
	free(): void;
}

interface SearchBinding { ChatSearchIndex: new () => ChatSearchIndexBinding }

export function isRustWebSearchBinding(binding: unknown): binding is SearchBinding {
	return typeof binding === 'object' && binding !== null
		&& typeof (binding as Record<string, unknown>).ChatSearchIndex === 'function';
}

export function installSearchUnit(context: UnitInstallContext): () => void {
	if (context.ports.length !== 1 || !isRustWebSearchBinding(context.binding)) throw new Error('unavailable');
	const port = context.ports[0];
	let index: ChatSearchIndexBinding | null = new context.binding.ChatSearchIndex();
	const live = (): ChatSearchIndexBinding => {
		if (!index) throw new UnitRefusal('unit_closed');
		return index;
	};
	const stopServing = serveUnitPort<SearchUnitProtocol>(port, {
		search(payload) {
			if (!isSearchRequest(payload)) throw new UnitRefusal('protocol');
			const target = live();
			for (const handle of payload.removes) target.remove_chat(handle);
			for (const set of payload.sets) {
				target.reset_chat(set.handle);
				for (let entry = 0; entry < set.messageIds.length; entry++) {
					target.push_entry(set.handle, set.messageIds[entry], set.contents[entry], set.embedIds[entry], set.embedTitled[entry] === 1);
				}
			}
			return { rows: target.search(payload.query, payload.handles, payload.includeEmbeds) };
		},
		clear() {
			const target = live();
			const chats = target.chat_count();
			target.clear();
			return { chats };
		},
		close() {
			const chats = live().chat_count();
			// The reply is posted after this handler returns; dispose on the next task.
			setTimeout(dispose, 0);
			return { chats };
		},
	});
	let disposed = false;
	const dispose = () => {
		if (disposed) return;
		disposed = true;
		stopServing();
		index?.free();
		index = null;
		port.close();
	};
	context.signal.addEventListener('abort', dispose, { once: true });
	return dispose;
}
