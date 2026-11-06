/**
 * Worker-side handle on the page's existing `chats_db` for the embed units.
 * Opens the current version only (never creates or upgrades: the page owns the
 * schema) and closes itself on `versionchange`, so a page upgrade or a logout
 * delete is never blocked by the Worker. The next call reopens.
 */
export type ChatsDbOpener = () => Promise<IDBDatabase>;

export function createWorkerChatsDb(factory: IDBFactory = indexedDB): { open: ChatsDbOpener; close(): void } {
	let current: Promise<IDBDatabase> | null = null;
	const drop = (db: IDBDatabase) => {
		db.close();
		current = null;
	};
	return {
		open() {
			current ??= new Promise<IDBDatabase>((resolve, reject) => {
				const request = factory.open('chats_db');
				request.onupgradeneeded = () => {
					request.transaction?.abort();
					reject(new Error('embed_store_unavailable'));
				};
				request.onerror = () => reject(new Error('embed_store_unavailable'));
				request.onblocked = () => reject(new Error('embed_store_unavailable'));
				request.onsuccess = () => {
					const db = request.result;
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
