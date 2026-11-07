// frontend/packages/ui/src/services/db/chatRowRewrite.ts
// Read-decide-write of one `chats` row when the decision arrives asynchronously
// (shared Rust core Worker). The decision cannot run inside an IndexedDB
// transaction, so it is taken on a snapshot and the write transaction only checks,
// synchronously and without interpreting fields, that the stored row still equals
// that snapshot before putting the result. A changed row restarts the decision.
import type { Chat } from "../../types/chat";

const MAX_ATTEMPTS = 4;

interface RewriteDatabase {
  CHATS_STORE_NAME: string;
  getTransaction(
    storeNames: string | string[],
    mode: IDBTransactionMode,
  ): Promise<IDBTransaction>;
}

export type ChatRowOutcome =
  | { kind: "skip"; value: Chat | null }
  | { kind: "abort"; message: string }
  | { kind: "write"; next: Chat };

/** Structured-clone rows read from one store keep their key order, so equal rows serialise equally. */
const sameRow = (a: Chat | undefined, b: Chat | undefined): boolean => JSON.stringify(a) === JSON.stringify(b);

function readRow(dbInstance: RewriteDatabase, transaction: IDBTransaction, chatId: string): Promise<Chat | undefined> {
  return new Promise((resolve, reject) => {
    const request = transaction.objectStore(dbInstance.CHATS_STORE_NAME).get(chatId);
    request.onsuccess = () => resolve(request.result as Chat | undefined);
    request.onerror = () => reject(request.error);
  });
}

/**
 * Applies `decide` to the latest row of `chatId`. `canWrite` is the caller's
 * write guard, checked in the write transaction right before the put.
 */
export async function rewriteChatRow(
  dbInstance: RewriteDatabase,
  chatId: string,
  decide: (snapshot: Chat | undefined) => Promise<ChatRowOutcome>,
  canWrite: () => boolean = () => true,
): Promise<Chat | null> {
  for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
    const snapshot = await readRow(dbInstance, await dbInstance.getTransaction(dbInstance.CHATS_STORE_NAME, "readonly"), chatId);
    const outcome = await decide(snapshot);
    if (outcome.kind === "skip") return outcome.value;
    if (outcome.kind === "abort") throw new Error(outcome.message);

    const transaction = await dbInstance.getTransaction(dbInstance.CHATS_STORE_NAME, "readwrite");
    const written = await new Promise<"written" | "refused" | "changed">((resolve, reject) => {
      let state: "written" | "refused" | "changed" = "changed";
      transaction.oncomplete = () => resolve(state);
      transaction.onerror = () => reject(transaction.error ?? new Error("Chat row transaction failed"));
      transaction.onabort = () => reject(transaction.error ?? new Error("Chat row transaction aborted"));
      const store = transaction.objectStore(dbInstance.CHATS_STORE_NAME);
      const request = store.get(chatId);
      request.onerror = () => reject(request.error);
      request.onsuccess = () => {
        if (!sameRow(snapshot, request.result as Chat | undefined)) return;
        if (!canWrite()) { state = "refused"; return; }
        store.put(outcome.next);
        state = "written";
      };
    });
    if (written === "written") return outcome.next;
    if (written === "refused") return null;
  }
  throw new Error(`Chat ${chatId} changed repeatedly while it was being updated`);
}
