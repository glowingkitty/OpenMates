/**
 * Thin IndexedDB adapter for Rust-prepared embed writes. It writes the
 * existing `chats_db` stores unchanged (no schema/version change, existing data
 * keeps decrypting): `embeds` (keyPath `contentRef`), `embed_keys` (composite id
 * `${hashed_embed_id}:${key_type}:${hashed_chat_id||"null"}`) and `embed_diffs`
 * (keyPath id `${embed_id}_v${n}`). Rows arrive fully encrypted from Rust; the
 * only transformation is the embed type registry normalization the legacy
 * `embedStore.putEncrypted` applies.
 */
import type { EncryptedDiffRow, EmbedKeyWrapperRow, PreparedEmbedWrite } from './embedWriteAdapter';

export const EMBEDS_STORE = 'embeds';
export const EMBED_KEYS_STORE = 'embed_keys';
export const EMBED_DIFFS_STORE = 'embed_diffs';

export function embedKeyStorageId(row: EmbedKeyWrapperRow): string {
	return `${row.hashed_embed_id}:${row.key_type}:${row.hashed_chat_id || 'null'}`;
}

function transactionDone(tx: IDBTransaction): Promise<void> {
	return new Promise((resolve, reject) => {
		tx.oncomplete = () => resolve();
		tx.onabort = () => reject(tx.error ?? new Error('embed_write_transaction_aborted'));
		tx.onerror = () => {
			/* onabort owns the terminal rejection. */
		};
	});
}

/**
 * Persist the local entry and its key wrappers atomically: an embed row is
 * never committed without the wrappers needed to decrypt it after reload.
 */
export async function persistPreparedEmbedWrite(
	db: IDBDatabase,
	prepared: PreparedEmbedWrite,
	normalizeType: (type: string) => string
): Promise<void> {
	const stores = prepared.local_key_wrappers.length ? [EMBEDS_STORE, EMBED_KEYS_STORE] : [EMBEDS_STORE];
	const tx = db.transaction(stores, 'readwrite');
	const done = transactionDone(tx);
	const entry = { ...prepared.local_entry, type: normalizeType(prepared.local_entry.type) };
	tx.objectStore(EMBEDS_STORE).put(entry);
	if (prepared.local_key_wrappers.length) {
		const keys = tx.objectStore(EMBED_KEYS_STORE);
		for (const wrapper of prepared.local_key_wrappers) keys.put({ ...wrapper, id: embedKeyStorageId(wrapper) });
	}
	await done;
}

export async function putEmbedDiff(db: IDBDatabase, row: EncryptedDiffRow): Promise<void> {
	const tx = db.transaction(EMBED_DIFFS_STORE, 'readwrite');
	const done = transactionDone(tx);
	tx.objectStore(EMBED_DIFFS_STORE).put(row);
	await done;
}

/** Local revision rows for one embed, ascending by version (embedDiffStore). */
export function getEmbedDiffs(db: IDBDatabase, embedId: string): Promise<EncryptedDiffRow[]> {
	const tx = db.transaction(EMBED_DIFFS_STORE, 'readonly');
	const request = tx.objectStore(EMBED_DIFFS_STORE).index('embed_id').getAll(embedId);
	return new Promise((resolve, reject) => {
		request.onsuccess = () => {
			const rows = ((request.result as EncryptedDiffRow[]) ?? []).slice();
			rows.sort((a, b) => a.version_number - b.version_number);
			resolve(rows);
		};
		request.onerror = () => reject(request.error);
	});
}

function readRequest<T>(request: IDBRequest<T>): Promise<T> {
	return new Promise((resolve, reject) => {
		request.onsuccess = () => resolve(request.result);
		request.onerror = () => reject(request.error ?? new Error('embed_write_read_failed'));
	});
}

/** `embed_keys` wrapper rows of one embed (index `hashed_embed_id`, as embedStore.getEmbedKeyEntries). */
export async function getEmbedKeyRows(db: IDBDatabase, hashedEmbedId: string): Promise<Record<string, unknown>[]> {
	const tx = db.transaction(EMBED_KEYS_STORE, 'readonly');
	return (await readRequest(tx.objectStore(EMBED_KEYS_STORE).index('hashed_embed_id').getAll(hashedEmbedId))) ?? [];
}

/** One stored `embeds` row by `contentRef`, or null. */
export async function getEmbedEntry(db: IDBDatabase, contentRef: string): Promise<Record<string, unknown> | null> {
	const tx = db.transaction(EMBEDS_STORE, 'readonly');
	return ((await readRequest(tx.objectStore(EMBEDS_STORE).get(contentRef))) as Record<string, unknown> | undefined) ?? null;
}
