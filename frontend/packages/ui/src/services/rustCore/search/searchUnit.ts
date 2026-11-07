/**
 * `search` namespace installer of the shared Rust core Worker.
 *
 * Owns the chat message search index in the realm's single WASM binding
 * (`ChatSearchIndex`: packages/openmates-rust/src/web_search_chats.rs and
 * web_search_query.rs). The page transfers each chat's entries once when it
 * (re)indexes the chat from its source (decrypted IndexedDB rows) and keeps no
 * copy; a query runs titles, snippets, metadata, ranking, embeds and catalog
 * filters here and only flat result rows plus the result texts go back.
 *
 * The unit holds only plaintext the page already decrypted and no key material.
 * It may open unbound for signed-out public chats; the page reopens it under
 * the current generation after login, so unbind closes the account's index, and
 * it sends `close` on logout before the realm is terminated. A Worker crash loses
 * the index with the realm; the page then re-indexes from the source on demand.
 *
 * Unit port protocol: searchUnitProtocol.ts over unitPort.ts.
 */
import { serveUnitPort, UnitRefusal } from '../host/unitPort';
import type { UnitInstallContext } from '../host/sharedWorkerProtocol';
import { isIngestRequest, isQueryRequest, type SearchQueryReply, type SearchUnitProtocol } from './searchUnitProtocol';

/** The wasm-bindgen class surface this unit needs (browser_search_pii.rs). */
export interface ChatSearchIndexBinding {
	ingest_chat(handle: number, messageIds: string[], contents: string[], createdAt: Float64Array, metaEntries: Uint32Array, metaMasks: Uint16Array, metaValues: string[]): Uint32Array;
	remove_chat(handle: number): void;
	clear(): void;
	chat_count(): number;
	query(
		query: string, flags: number, handles: Uint32Array, chatMasks: Uint8Array, chatValues: string[], tagCounts: Uint32Array, lastEdited: Float64Array,
		catalogFlags: Uint8Array, catalogLabels: string[], catalogKeywordCounts: Uint32Array, catalogKeywords: string[],
	): SearchQueryReply;
	free(): void;
}

interface SearchBinding { ChatSearchIndex: new () => ChatSearchIndexBinding }

export function isRustWebSearchBinding(binding: unknown): binding is SearchBinding {
	return typeof binding === 'object' && binding !== null
		&& typeof (binding as Record<string, unknown>).ChatSearchIndex === 'function';
}

/** The binding rejects malformed columns with the string code `protocol`. */
function bindingCall<T>(run: () => T): T {
	try {
		return run();
	} catch (error) {
		if (error === 'protocol') throw new UnitRefusal('protocol');
		throw error;
	}
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
		ingest(payload) {
			if (!isIngestRequest(payload)) throw new UnitRefusal('protocol');
			const target = live();
			for (const handle of payload.removes) target.remove_chat(handle);
			const { chat } = payload;
			const started = performance.now();
			const evicted = bindingCall(() => target.ingest_chat(chat.handle, chat.messageIds, chat.contents, chat.createdAt, chat.metaEntries, chat.metaMasks, chat.metaValues));
			return { evicted, workerMs: performance.now() - started };
		},
		query(payload) {
			if (!isQueryRequest(payload)) throw new UnitRefusal('protocol');
			const target = live();
			for (const handle of payload.removes) target.remove_chat(handle);
			const started = performance.now();
			const reply = bindingCall(() => target.query(
				payload.query, payload.flags, payload.handles, payload.chatMasks, payload.chatValues, payload.tagCounts, payload.lastEdited,
				payload.catalogFlags, payload.catalogLabels, payload.catalogKeywordCounts, payload.catalogKeywords,
			));
			reply.workerMs = performance.now() - started;
			return reply;
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
