/**
 * Worker-side IndexedDB access for opaque live outbox records. Rust owns the
 * cache keys, sealed packet format and merge policy across open editors.
 */
import { createWorkerChatsDb } from '../embeds/embedWorkerIdb';

export const LIVE_OUTBOX_STORE = 'live_item_outbox';

type Change = { expected: string | null; next: string | null };

export function createLiveOutboxStorage(signal: AbortSignal) {
	const db = createWorkerChatsDb();

	async function transact<T>(
		key: string,
		change: Change | undefined,
		readResult: (bytes: string | null, matched: boolean) => T
	): Promise<T> {
		const database = await db.open();
		signal.throwIfAborted();
		return new Promise<T>((resolve, reject) => {
			const tx = change
				? database.transaction(LIVE_OUTBOX_STORE, 'readwrite', { durability: 'strict' })
				: database.transaction(LIVE_OUTBOX_STORE, 'readonly');
			const abort = () => {
				try {
					tx.abort();
				} catch (error) {
					if (!(error instanceof DOMException && error.name === 'InvalidStateError')) {
						reject(error);
					}
				}
			};
			let result: T;
			const finished = () => signal.removeEventListener('abort', abort);
			signal.addEventListener('abort', abort, { once: true });
			tx.oncomplete = () => {
				finished();
				resolve(result);
			};
			tx.onabort = () => {
				finished();
				reject(tx.error ?? new Error('live_outbox_unavailable'));
			};
			const store = tx.objectStore(LIVE_OUTBOX_STORE);
			const request = store.get(key);
			request.onsuccess = () => {
				const value = request.result;
				if (value !== undefined && typeof value !== 'string') {
					abort();
					return;
				}
				const current = value ?? null;
				const matched = change?.expected === current;
				result = readResult(current, matched);
				if (change && matched) {
					if (change.next === null) store.delete(key);
					else store.put(change.next, key);
				}
			};
		});
	}

	async function keys(prefix: string): Promise<string[]> {
		const database = await db.open();
		signal.throwIfAborted();
		return new Promise((resolve, reject) => {
			const tx = database.transaction(LIVE_OUTBOX_STORE, 'readonly');
			const range = IDBKeyRange.bound(prefix, prefix + '\uffff');
			const request = tx.objectStore(LIVE_OUTBOX_STORE).getAllKeys(range);
			tx.onabort = () => reject(tx.error ?? new Error('live_outbox_unavailable'));
			tx.oncomplete = () => {
				if (signal.aborted) {
					reject(signal.reason);
				} else {
					resolve(request.result.filter((key): key is string => typeof key === 'string'));
				}
			};
		});
	}

	return {
		keys,
		read: (key: string) => transact(key, undefined, (bytes) => bytes),
		compareAndPut: (key: string, expected: string | null, next: string | null) =>
			transact(key, { expected, next }, (_, matched) => matched),
		close: db.close
	};
}
