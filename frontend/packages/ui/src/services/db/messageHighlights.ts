// frontend/packages/ui/src/services/db/messageHighlights.ts
//
// IndexedDB data-access for message_highlights rows. Highlights are stored
// DECRYPTED locally (speed) but ONLY after the chat key has decrypted the
// ciphertext received over the wire. The encrypted blob never hits this store.
//
// See the feature plan for the full E2EE contract.

import type { MessageHighlight } from "../../types/chat";

const STORE_NAME = "message_highlights";

type HighlightsDb = {
  db: IDBDatabase | null;
  MESSAGE_HIGHLIGHTS_STORE_NAME: string;
};

function assertDb(instance: HighlightsDb): IDBDatabase {
  if (!instance.db) throw new Error("[messageHighlights] DB not initialized");
  return instance.db;
}

/** Write-through upsert by id. Used for both local authoring and inbound WS events. */
export async function upsertHighlight(
  instance: HighlightsDb,
  highlight: MessageHighlight,
): Promise<void> {
  const db = assertDb(instance);
  return new Promise((resolve, reject) => {
    const tx = db.transaction([STORE_NAME], "readwrite");
    tx.objectStore(STORE_NAME).put(highlight);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

/** Bulk upsert — used on phased-sync / cold-boot where the server sends many rows. */
export async function upsertHighlights(
  instance: HighlightsDb,
  highlights: MessageHighlight[],
): Promise<void> {
  if (highlights.length === 0) return;
  const db = assertDb(instance);
  return new Promise((resolve, reject) => {
    const tx = db.transaction([STORE_NAME], "readwrite");
    const store = tx.objectStore(STORE_NAME);
    for (const h of highlights) store.put(h);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

export async function deleteHighlightById(
  instance: HighlightsDb,
  id: string,
): Promise<void> {
  const db = assertDb(instance);
  return new Promise((resolve, reject) => {
    const tx = db.transaction([STORE_NAME], "readwrite");
    tx.objectStore(STORE_NAME).delete(id);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

/** Load all highlights for a given message, ordered by created_at. */
export async function getHighlightsForMessage(
  instance: HighlightsDb,
  chatId: string,
  messageId: string,
): Promise<MessageHighlight[]> {
  const db = assertDb(instance);
  return new Promise((resolve, reject) => {
    const tx = db.transaction([STORE_NAME], "readonly");
    const index = tx.objectStore(STORE_NAME).index("chat_id_message_id");
    const req = index.getAll(IDBKeyRange.only([chatId, messageId]));
    req.onsuccess = () => {
      const rows = (req.result ?? []) as MessageHighlight[];
      rows.sort((a, b) => a.created_at - b.created_at);
      resolve(rows);
    };
    req.onerror = () => reject(req.error);
  });
}

/** Load all highlights for a chat (used by ChatHeader pill count). */
export async function getHighlightsForChat(
  instance: HighlightsDb,
  chatId: string,
): Promise<MessageHighlight[]> {
  const db = assertDb(instance);
  return new Promise((resolve, reject) => {
    const tx = db.transaction([STORE_NAME], "readonly");
    const index = tx.objectStore(STORE_NAME).index("chat_id");
    const req = index.getAll(IDBKeyRange.only(chatId));
    req.onsuccess = () => resolve((req.result ?? []) as MessageHighlight[]);
    req.onerror = () => reject(req.error);
  });
}

/** Remove all highlights for a message. Called when a message is deleted/edited. */
export async function deleteHighlightsForMessage(
  instance: HighlightsDb,
  chatId: string,
  messageId: string,
): Promise<void> {
  const db = assertDb(instance);
  const rows = await getHighlightsForMessage(instance, chatId, messageId);
  if (rows.length === 0) return;
  return new Promise((resolve, reject) => {
    const tx = db.transaction([STORE_NAME], "readwrite");
    const store = tx.objectStore(STORE_NAME);
    for (const h of rows) store.delete(h.id);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

/** Remove all highlights for an entire chat. Called when a chat is deleted. */
export async function deleteHighlightsForChat(
  instance: HighlightsDb,
  chatId: string,
): Promise<void> {
  const db = assertDb(instance);
  const rows = await getHighlightsForChat(instance, chatId);
  if (rows.length === 0) return;
  return new Promise((resolve, reject) => {
    const tx = db.transaction([STORE_NAME], "readwrite");
    const store = tx.objectStore(STORE_NAME);
    for (const h of rows) store.delete(h.id);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}
