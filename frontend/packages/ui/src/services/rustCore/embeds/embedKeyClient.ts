/**
 * embedStore read hook for Worker-side embed key resolution (U9 slice 2;
 * VITE_OPENMATES_RUST_CORE builds only; each embedStore call site is a
 * compile-time ternary, so default builds keep `getEmbedKey` and drop this).
 *
 * Instead of unwrapping the embed key on the page, the stored row goes to the
 * `embedWrite` unit (`openStoredRows`): Rust resolves the key from the
 * Worker's `embed_keys` rows (TS getEmbedKey order, embedKeyResolution.ts) and
 * opens content, type and preview. The page receives the fields and the
 * `WORKER_RESOLVED_EMBED_KEY` marker, never key bytes or wrappers. When a
 * wrapper's chat key is not in the Worker yet, the page installs the chat key
 * its ChatKeyManager holds (`adoptPageChatKey`) and retries once; a chat whose
 * key is not loaded is marked pending (`_decryptionPending`), as in TS.
 *
 * A key the page set explicitly (share/open-by-link flows, `setEmbedKeyInCache`)
 * is the page's own key and is used as before. The TS callback runs only when
 * the Rust crypto arm is inactive (measurement opt-out). Worker failures reject.
 */
import { computeSHA256 } from '../../../message_parsing/utils';
import { chatDB } from '../../db';
import { chatKeyManager } from '../../encryption/ChatKeyManager';
import { rememberOpenedRow, rustEmbedData, WORKER_RESOLVED_EMBED_KEY } from './embedDataClient';
import type { StoredRowRequest, StoredRowResult } from './embedDataProtocol';
import type { EmbedWriteClient } from './embedWriteClient';
import { discardRustEmbedWriter, rustEmbedReader } from './embedWriteSession';
import { UnitPortError } from '../host/unitPort';

/** The embedStore state the hook needs (bound methods of the store). */
export interface EmbedKeyHost {
	/** A key the page holds itself (explicitly set, or unwrapped by a remaining page caller). */
	getEmbedKeyFromCache(embedId: string, hashedChatId?: string): Uint8Array | null;
	markEmbedKeyPendingForChat(chatId: string, embedId: string): void;
}

type StoredRow = { encrypted_content?: unknown; encrypted_type?: unknown; encrypted_text_preview?: unknown };

/** One Worker open per stored row object (content/type/preview sites share it). */
let resolutions: WeakMap<object, Promise<Uint8Array | null>> | null = null;

async function chatIdsByHash(hashes: string[]): Promise<Map<string, string>> {
	const { chatListCache } = await import('../../chatListCache');
	const { anonymousChatStorage } = await import('../../anonymousChatStorage');
	const chats = [...(chatListCache.getCache() ?? (await chatDB.getAllChats())), ...(await anonymousChatStorage.getAllChats())];
	const wanted = new Set(hashes);
	const found = new Map<string, string>();
	for (const chat of chats) {
		const hash = await computeSHA256(chat.chat_id);
		if (wanted.has(hash)) found.set(hash, chat.chat_id);
	}
	return found;
}

/** Installs the page-held chat keys of `hashes`; marks the rest pending. True when one was installed. */
async function adoptPendingChatKeys(writer: EmbedWriteClient, hashes: string[], embedId: string, host: EmbedKeyHost): Promise<boolean> {
	let installed = false;
	for (const chatId of (await chatIdsByHash(hashes)).values()) {
		const chatKey = await chatKeyManager.getKey(chatId);
		if (!chatKey) {
			host.markEmbedKeyPendingForChat(chatId, embedId);
			continue;
		}
		// A copy crosses (the Worker zeroes it); the ChatKeyManager keeps its own.
		await writer.unit.request('adoptPageChatKey', { chatId, key: new Uint8Array(chatKey) });
		installed = true;
	}
	return installed;
}

async function openInWorker(embedId: string, hashedChatId: string | undefined, row: StoredRow, host: EmbedKeyHost): Promise<Uint8Array | null> {
	const text = (value: unknown) => (typeof value === 'string' ? value : null);
	const request: StoredRowRequest = {
		embedId,
		hashedChatId: hashedChatId ?? null,
		encrypted_content: text(row.encrypted_content)?.trim() ?? null,
		encrypted_type: text(row.encrypted_type),
		encrypted_text_preview: text(row.encrypted_text_preview)
	};
	const writer = await rustEmbedReader();
	const open = async (): Promise<StoredRowResult> => {
		const [result] = await writer.unit.request('openStoredRows', { rows: [request] });
		return result;
	};
	let result: StoredRowResult;
	try {
		const first = await open();
		result = first;
		if ('pendingChatHashes' in first && first.pendingChatHashes.length && (await adoptPendingChatKeys(writer, first.pendingChatHashes, embedId, host))) {
			result = await open();
		}
	} catch (error) {
		// A stalled unit would time out every later call too: reopen it on the next read.
		if (error instanceof UnitPortError && error.code === 'unit_timeout') discardRustEmbedWriter(writer);
		throw error;
	}
	const stats = rustEmbedData()?.stats;
	if (stats) {
		stats.requests += 1;
		stats.rows += 1;
	}
	if (!result.ok) return null;
	rememberOpenedRow(row, result.fields);
	return WORKER_RESOLVED_EMBED_KEY;
}

/**
 * embedStore read sites' key lookup in Rust mode: `WORKER_RESOLVED_EMBED_KEY`
 * when the Worker opened the row, an explicitly set page key, or null
 * (unavailable; pending when a chat key is missing).
 */
export function workerEmbedKey(embedId: string, hashedChatId: string | undefined, row: StoredRow, host: EmbedKeyHost,
	typescript: () => Promise<Uint8Array | null>): Promise<Uint8Array | null> {
	if (!rustEmbedData()) return typescript();
	const explicit = host.getEmbedKeyFromCache(embedId, hashedChatId);
	if (explicit) return Promise.resolve(explicit);
	const known = resolutions?.get(row);
	if (known) return known;
	const resolution = openInWorker(embedId, hashedChatId, row, host);
	(resolutions ??= new WeakMap()).set(row, resolution);
	// Only an opened row is shared; a miss is retried on the next read (e.g. once its chat key loads).
	const forget = () => { if (resolutions?.get(row) === resolution) resolutions.delete(row); };
	resolution.then((key) => { if (!key) forget(); }, forget);
	return resolution;
}
