// frontend/packages/ui/src/services/db/offlineChangesAndUpdates.ts
// Handles offline changes and chat update operations for the ChatDatabase class.
// These operations are extracted from db.ts for better code organization.
//
// This module contains:
// - Offline changes CRUD operations (for sync queue)
// - Chat component version updates
// - Chat timestamp updates
// - Chat scroll position and read status updates

import type { Chat, OfflineChange, ChatComponentVersions } from "../../types/chat";
import { get } from "svelte/store";
import { forcedLogoutInProgress, isLoggingOut } from "../../stores/signupState";
import { getWorkspaceCacheEpoch } from "../workspaceCacheLifecycle";
import * as chatCrudOps from "./chatCrudOperations";

// Type for ChatDatabase instance to avoid circular import
// Only includes properties/methods needed by this module
interface ChatDatabaseInstance {
  db: IDBDatabase | null;
  CHATS_STORE_NAME: string;
  init(): Promise<void>;
  getTransaction(
    storeNames: string | string[],
    mode: IDBTransactionMode,
  ): Promise<IDBTransaction>;

  // Chat key management methods (needed for chatCrudOps)
  getChatKey(chatId: string): Uint8Array | null;
  setChatKey(chatId: string, chatKey: Uint8Array): void;
  clearChatKey(chatId: string): void;
}

// Store name constants (must match db.ts)
const OFFLINE_CHANGES_STORE_NAME = "pending_sync_changes";

// Multiple calls sharing one caller-owned transaction can queue their reads
// before either put. Reserve their orders until that transaction is collected.
const offlineOrdersByTransaction = new WeakMap<IDBTransaction, number>();

// ============================================================================
// OFFLINE CHANGES OPERATIONS
// ============================================================================

/**
 * Add an offline change to the sync queue with durable insertion order.
 * IndexedDB serializes readwrite transactions on this store across tabs, so the
 * maximum read and the write must stay in the same transaction.
 */
export async function addOfflineChange(
  dbInstance: ChatDatabaseInstance,
  change: OfflineChange,
  transaction?: IDBTransaction,
): Promise<void> {
  const epoch = getWorkspaceCacheEpoch();
  const contextChanged = () => epoch !== getWorkspaceCacheEpoch()
    || get(forcedLogoutInProgress) || get(isLoggingOut);
  if (contextChanged()) throw new Error("Offline change workspace changed");
  await dbInstance.init();
  if (contextChanged()) throw new Error("Offline change workspace changed");
  const currentTransaction =
    transaction ||
    (await dbInstance.getTransaction(OFFLINE_CHANGES_STORE_NAME, "readwrite"));
  if (contextChanged()) {
    currentTransaction.abort();
    throw new Error("Offline change workspace changed");
  }
  return new Promise((resolve, reject) => {
    const store = currentTransaction.objectStore(OFFLINE_CHANGES_STORE_NAME);
    const request = store.getAll();
    request.onerror = () => reject(request.error);
    request.onsuccess = () => {
      if (contextChanged()) {
        reject(new Error("Offline change workspace changed"));
        currentTransaction.abort();
        return;
      }
      let maximumOrder = offlineOrdersByTransaction.get(currentTransaction) ?? 0;
      for (const queued of request.result as OfflineChange[]) {
        const order = queued.queue_order;
        if (typeof order === "number" && Number.isSafeInteger(order) && order > 0) {
          maximumOrder = Math.max(maximumOrder, order);
        }
      }
      if (maximumOrder === Number.MAX_SAFE_INTEGER) {
        reject(new Error("Offline change queue insertion order exhausted"));
        currentTransaction.abort();
        return;
      }
      try {
        // Queue synchronously in the read callback to keep the transaction
        // active. Replacing a change_id is a new insertion: its content may have
        // changed, so retaining its older order could replay it too early.
        const write = store.put({ ...change, queue_order: maximumOrder + 1, queue_token: crypto.randomUUID() });
        offlineOrdersByTransaction.set(currentTransaction, maximumOrder + 1);
        write.onsuccess = () => { if (transaction) resolve(); };
        write.onerror = () => reject(write.error);
      } catch (error) {
        reject(error);
        currentTransaction.abort();
      }
    };
    if (!transaction) {
      currentTransaction.oncomplete = () => resolve();
      currentTransaction.onerror = () => reject(currentTransaction.error);
      currentTransaction.onabort = () => reject(currentTransaction.error ?? new Error("Offline change save aborted"));
    } else {
      // The caller owns commit acknowledgement and its event properties.
      currentTransaction.addEventListener("abort", () => reject(
        currentTransaction.error ?? new Error("Offline change save aborted"),
      ), { once: true });
    }
  });
}

/**
 * Get all pending offline changes
 */
export async function getOfflineChanges(
  dbInstance: ChatDatabaseInstance,
  transaction?: IDBTransaction,
): Promise<OfflineChange[]> {
  await dbInstance.init();
  const currentTransaction =
    transaction ||
    (await dbInstance.getTransaction(OFFLINE_CHANGES_STORE_NAME, "readonly"));
  return new Promise((resolve, reject) => {
    const store = currentTransaction.objectStore(OFFLINE_CHANGES_STORE_NAME);
    const request = store.getAll();
    request.onsuccess = () => resolve(request.result || []);
    request.onerror = () => reject(request.error);
  });
}

/**
 * Delete an offline change from the sync queue
 */
export async function deleteOfflineChange(
  dbInstance: ChatDatabaseInstance,
  change_id: string,
  transaction?: IDBTransaction,
  expected?: { queueOrder: number | undefined; queueToken?: string },
): Promise<void> {
  await dbInstance.init();
  const currentTransaction =
    transaction ||
    (await dbInstance.getTransaction(OFFLINE_CHANGES_STORE_NAME, "readwrite"));
  return new Promise((resolve, reject) => {
    const store = currentTransaction.objectStore(OFFLINE_CHANGES_STORE_NAME);
    const remove = () => {
      const request = store.delete(change_id);
      request.onsuccess = () => { if (transaction) resolve(); };
      request.onerror = () => reject(request.error);
    };
    if (expected) {
      const read = store.get(change_id);
      read.onerror = () => reject(read.error);
      read.onsuccess = () => {
        // A late ACK must not delete a replacement saved under the same ID.
        if (read.result && read.result.queue_order === expected.queueOrder &&
          read.result.queue_token === expected.queueToken) remove();
        else if (transaction) resolve();
      };
    } else remove();
    if (!transaction) {
      currentTransaction.oncomplete = () => resolve();
      currentTransaction.onerror = () => reject(currentTransaction.error);
      currentTransaction.onabort = () => reject(currentTransaction.error ?? new Error("Offline change removal aborted"));
    }
  });
}

// ============================================================================
// CHAT COMPONENT VERSION UPDATES
// ============================================================================

/**
 * Update a specific component version of a chat (draft_v, messages_v, or title_v)
 *
 * CRITICAL: This function gets the chat WITHOUT a transaction first to allow
 * async decryption work to complete, then creates a new transaction for the update.
 * This prevents "transaction no longer active" errors that occur when async work
 * (like decryption) happens while a transaction is open.
 */
export async function updateChatComponentVersion(
  dbInstance: ChatDatabaseInstance,
  chat_id: string,
  component: keyof ChatComponentVersions,
  version: number,
): Promise<void> {
  await dbInstance.init();

  // CRITICAL FIX: Get chat WITHOUT transaction first to allow async decryption
  // If we pass a transaction to getChat, the async decryption work can cause
  // the transaction to finish before we use it in addChat
  const chat = await chatCrudOps.getChat(dbInstance, chat_id);

  if (!chat) {
    console.warn(
      `[ChatDatabase] Chat ${chat_id} not found when updating component version`,
    );
    return;
  }

  // Now create a transaction for the update operation
  const tx = await dbInstance.getTransaction(
    dbInstance.CHATS_STORE_NAME,
    "readwrite",
  );

  try {
    if (component === "draft_v") {
      chat.draft_v = version;
    } else if (component === "messages_v") {
      chat.messages_v = version;
    } else if (component === "title_v") {
      chat.title_v = version;
    }
    chat.updated_at = Math.floor(Date.now() / 1000);
    await chatCrudOps.addChat(dbInstance, chat, tx);

    return new Promise((resolve, reject) => {
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  } catch (error) {
    if (tx.abort) tx.abort();
    throw error;
  }
}

/**
 * Update the last edited timestamp for a chat
 *
 * CRITICAL: This function gets the chat WITHOUT a transaction first to allow
 * async decryption work to complete, then creates a new transaction for the update.
 * This prevents "transaction no longer active" errors that occur when async work
 * (like decryption) happens while a transaction is open.
 */
export async function updateChatLastEditedTimestamp(
  dbInstance: ChatDatabaseInstance,
  chat_id: string,
  timestamp: number,
): Promise<void> {
  await dbInstance.init();

  // CRITICAL FIX: Get chat WITHOUT transaction first to allow async decryption
  // If we pass a transaction to getChat, the async decryption work can cause
  // the transaction to finish before we use it in addChat
  const chat = await chatCrudOps.getChat(dbInstance, chat_id);

  if (!chat) {
    console.warn(
      `[ChatDatabase] Chat ${chat_id} not found when updating last edited timestamp`,
    );
    return;
  }

  // Now create a transaction for the update operation
  const tx = await dbInstance.getTransaction(
    dbInstance.CHATS_STORE_NAME,
    "readwrite",
  );

  try {
    chat.last_edited_overall_timestamp = timestamp;
    chat.updated_at = Math.floor(Date.now() / 1000);
    await chatCrudOps.addChat(dbInstance, chat, tx);

    return new Promise((resolve, reject) => {
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  } catch (error) {
    if (tx.abort) tx.abort();
    throw error;
  }
}

// ============================================================================
// CHAT SCROLL POSITION AND READ STATUS
// ============================================================================

type ChatViewField = "last_visible_message_id" | "unread_count";

/** Keep a view-only write behind newer encrypted draft and metadata commits. */
async function updateRawChatViewField(
  dbInstance: ChatDatabaseInstance,
  chatId: string,
  field: ChatViewField,
  value: string | number,
): Promise<"updated" | "missing" | "cancelled"> {
  const epoch = getWorkspaceCacheEpoch();
  const contextChanged = () => epoch !== getWorkspaceCacheEpoch()
    || get(forcedLogoutInProgress) || get(isLoggingOut);
  if (contextChanged()) return "cancelled";
  await dbInstance.init();
  if (contextChanged()) return "cancelled";
  const transaction = await dbInstance.getTransaction(dbInstance.CHATS_STORE_NAME, "readwrite");
  return new Promise((resolve, reject) => {
    let result: "updated" | "missing" | "cancelled" = "cancelled";
    transaction.oncomplete = () => resolve(result);
    transaction.onerror = () => reject(transaction.error ?? new Error("Chat view update failed"));
    transaction.onabort = () => reject(transaction.error ?? new Error("Chat view update aborted"));
    const store = transaction.objectStore(dbInstance.CHATS_STORE_NAME);
    const request = store.get(chatId);
    request.onerror = () => reject(request.error ?? new Error("Chat view read failed"));
    request.onsuccess = () => {
      if (contextChanged()) return;
      const chat = request.result as Chat | undefined;
      if (!chat) {
        result = "missing";
        return;
      }
      // The read and put share one transaction; no decryption or other await
      // can let an older chat snapshot overwrite a newer encrypted draft.
      store.put({ ...chat, [field]: value });
      result = "updated";
    };
  });
}

/** Update the scroll position without changing sort order or encrypted fields. */
export async function updateChatScrollPosition(
  dbInstance: ChatDatabaseInstance,
  chat_id: string,
  message_id: string,
): Promise<void> {
  const result = await updateRawChatViewField(dbInstance, chat_id, "last_visible_message_id", message_id);
  if (result === "missing") {
    console.warn(
      `[ChatDatabase] Chat ${chat_id} not found when updating scroll position`,
    );
    return;
  }

  if (result === "updated") console.debug(
    `[ChatDatabase] Updated scroll position for chat ${chat_id}: message ${message_id}`,
  );
}

/** Update read status without changing sort order or encrypted fields. */
export async function updateChatReadStatus(
  dbInstance: ChatDatabaseInstance,
  chat_id: string,
  unread_count: number,
): Promise<void> {
  const result = await updateRawChatViewField(dbInstance, chat_id, "unread_count", unread_count);
  if (result === "missing") {
    console.warn(
      `[ChatDatabase] Chat ${chat_id} not found when updating read status`,
    );
    return;
  }

  if (result === "updated") console.debug(
    `[ChatDatabase] Updated read status for chat ${chat_id}: unread_count = ${unread_count}`,
  );
}
