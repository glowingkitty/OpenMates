// frontend/packages/ui/src/services/db/messageEviction.ts
// Cache eviction of one confirmed message when the "is it safe" verdict arrives
// asynchronously (shared Rust core Worker). An IndexedDB transaction cannot wait
// for such a verdict, so the verdict is taken on a snapshot read in its own
// transaction and the delete transaction only checks, synchronously and without
// interpreting the fields, that the row still carries the snapshot's policy fields.
import type { Message } from "../../types/chat";

const MESSAGES_STORE_NAME = "messages";

/** The fields isSafeToEvictMessage reads. */
const EVICTION_FIELDS = [
  "status",
  "pending_turn_preflight_v1",
  "pending_encrypted_turn_preflight_v1",
  "pending_encrypted_embed_bundle_v1",
] as const;

interface EvictionDatabase {
  getTransaction(
    storeNames: string | string[],
    mode: IDBTransactionMode,
  ): Promise<IDBTransaction>;
}

function unchangedSince(snapshot: Message, current: Message | undefined): boolean {
  if (!current) return false;
  const before = snapshot as unknown as Record<string, unknown>;
  const now = current as unknown as Record<string, unknown>;
  return EVICTION_FIELDS.every((field) => before[field] === now[field]);
}

/** Delete `messageId` when `isSafe(snapshot)` holds and the row did not change meanwhile. */
export async function deleteConfirmedMessageAfterDecision(
  dbInstance: EvictionDatabase,
  messageId: string,
  isSafe: (message: Message | undefined) => Promise<boolean>,
): Promise<boolean> {
  const readTransaction = await dbInstance.getTransaction(MESSAGES_STORE_NAME, "readonly");
  const snapshot = await new Promise<Message | undefined>((resolve, reject) => {
    const request = readTransaction.objectStore(MESSAGES_STORE_NAME).get(messageId);
    request.onsuccess = () => resolve(request.result as Message | undefined);
    request.onerror = () => reject(request.error);
  });
  if (!snapshot || !(await isSafe(snapshot))) return false;

  const transaction = await dbInstance.getTransaction(MESSAGES_STORE_NAME, "readwrite");
  return new Promise((resolve, reject) => {
    const store = transaction.objectStore(MESSAGES_STORE_NAME);
    let deleted = false;
    const request = store.get(messageId);
    request.onsuccess = () => {
      if (!unchangedSince(snapshot, request.result as Message | undefined)) return;
      store.delete(messageId);
      deleted = true;
    };
    request.onerror = () => reject(request.error);
    transaction.oncomplete = () => resolve(deleted);
    transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () => reject(transaction.error ?? new Error("Cache eviction aborted"));
  });
}
