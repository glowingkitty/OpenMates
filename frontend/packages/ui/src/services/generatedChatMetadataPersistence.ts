import type { Chat } from '../types/chat';

/** Already encrypted optional metadata is patched in one transaction. No
 * decryption/key await can overwrite a concurrent draft, queue or sync write. */
export async function persistGeneratedChatMetadata(
  database: { db: IDBDatabase | null; CHATS_STORE_NAME: string; init(): Promise<void> },
  baseline: Chat,
  patch: Partial<Chat>,
  isCurrent: () => boolean,
  filterPatch: (patch: Partial<Chat>) => Partial<Chat> = (value) => value,
): Promise<Chat | null> {
  if (!database.db) await database.init();
  if (!database.db || !isCurrent()) return null;
  return new Promise((resolve, reject) => {
    const transaction = database.db!.transaction(database.CHATS_STORE_NAME, 'readwrite');
    const store = transaction.objectStore(database.CHATS_STORE_NAME);
    let updated: Chat | null = null;
    const request = store.get(baseline.chat_id);
    request.onsuccess = () => {
      const latest = request.result as Chat | undefined;
      if (!latest || !isCurrent() || latest.encrypted_chat_key !== baseline.encrypted_chat_key) return;
      const accepted = { ...filterPatch(patch) };
      if (accepted.metadata_v !== undefined && (latest.metadata_v ?? 0) > accepted.metadata_v) {
        updated = latest;
        return;
      }
      if (latest.title_v !== baseline.title_v) {
        delete accepted.encrypted_title; delete accepted.title_v;
      }
      if (latest.encrypted_chat_summary !== baseline.encrypted_chat_summary) delete accepted.encrypted_chat_summary;
      updated = { ...latest, ...accepted };
      store.put(updated);
    };
    transaction.oncomplete = () => resolve(updated);
    transaction.onerror = () => reject(transaction.error ?? new Error('Generated chat metadata write failed'));
    transaction.onabort = () => reject(transaction.error ?? new Error('Generated chat metadata write aborted'));
  });
}
