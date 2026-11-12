/**
 * Worker-side handle on the page's existing `chats_db` for the embed units.
 * Opens the current version only (never creates or upgrades: the page owns the
 * schema) and closes itself on `versionchange`, so a page upgrade or a logout
 * delete is never blocked by the Worker. The next call reopens.
 */
export type ChatsDbOpener = () => Promise<IDBDatabase>;

/** An open that neither succeeds nor fails (blocked by a stalled connection) is abandoned after this. */
export const CHATS_DB_OPEN_TIMEOUT_MS = 10_000;

export function createWorkerChatsDb(factory: IDBFactory = indexedDB, openTimeoutMs = CHATS_DB_OPEN_TIMEOUT_MS): { open: ChatsDbOpener; close(): void } {
	let current: Promise<IDBDatabase> | null = null;
	const drop = (db: IDBDatabase) => {
		db.close();
		current = null;
	};
	return {
		open() {
			current ??= new Promise<IDBDatabase>((resolve, reject) => {
				let settled = false;
				const fail = () => {
					if (settled) return;
					settled = true;
					clearTimeout(timer);
					reject(new Error('embed_store_unavailable'));
				};
				// A late success after the timeout closes its connection; the next call reopens.
				const timer = setTimeout(fail, openTimeoutMs);
				const request = factory.open('chats_db');
				request.onupgradeneeded = () => {
					request.transaction?.abort();
					fail();
				};
				request.onerror = fail;
				request.onblocked = fail;
				request.onsuccess = () => {
					const db = request.result;
					if (settled) {
						db.close();
						return;
					}
					settled = true;
					clearTimeout(timer);
					db.onversionchange = () => drop(db);
					resolve(db);
				};
			});
			const opening = current;
			opening.catch(() => { if (current === opening) current = null; });
			return opening;
		},
		close() {
			const opened = current;
			current = null;
			void opened?.then((db) => db.close(), () => undefined);
		}
	};
}
