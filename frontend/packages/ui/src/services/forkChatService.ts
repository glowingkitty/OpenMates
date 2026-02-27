// frontend/packages/ui/src/services/forkChatService.ts
//
// Implements the "Fork Conversation" feature.
//
// A fork creates a brand-new chat that contains a copy of all messages from
// the source chat up to and including a selected message. Everything runs
// entirely on the client (zero-knowledge: the server never decrypts anything).
//
// Architecture overview:
//   1. Fetch all messages for the source chat from IndexedDB (already decrypted).
//   2. Slice the list to include only messages up to the fork point.
//   3. Generate a new chat ID and new AES chat key.
//   4. Re-encrypt every message field with the new key.
//   5. Save the new chat + all copied messages in one IndexedDB transaction.
//   6. Sync to the server using the existing chat_message_added WebSocket flow
//      (each message is sent individually so the server persists them normally).
//   7. Update forkProgressStore throughout to drive UI.
//   8. On completion: fire a "fork complete" notification that opens the new chat.
//
// Background processing:
//   The caller can navigate away freely while the fork runs. The operation is
//   async and non-blocking. forkProgressStore is global and survives navigation.

import { chatDB } from "./db";
import { forkProgressStore } from "../stores/forkProgressStore";
import { notificationStore } from "../stores/notificationStore";
import { activeChatStore } from "../stores/activeChatStore";
import { webSocketService } from "./websocketService";
import { websocketStatus } from "../stores/websocketStatusStore";
import {
  generateChatKey,
  encryptWithChatKey,
  encryptChatKeyWithMasterKey,
} from "./cryptoService";
import { get } from "svelte/store";
import type { Message, Chat } from "../types/chat";

// How many messages to encrypt per "tick" before yielding to the event loop.
// Keeps the UI responsive during large chats.
const BATCH_SIZE = 10;

// Delay between batches (ms) to allow the UI to breathe.
const BATCH_DELAY_MS = 0; // Use microtask-level yield (requestAnimationFrame below)

// ---------------------------------------------------------------------------
// Main entry point
// ---------------------------------------------------------------------------

/**
 * Start a background fork operation.
 *
 * @param sourceChatId   The chat being forked.
 * @param upToMessageId  The ID of the last message to include (inclusive).
 * @param forkTitle      Plaintext title for the new chat.
 * @returns              The new chat ID (so the caller can deep-link to it later).
 */
export async function startFork(
  sourceChatId: string,
  upToMessageId: string,
  forkTitle: string,
): Promise<string> {
  // Guard: only one fork at a time
  const current = forkProgressStore.getSnapshot();
  if (current.status === "running") {
    console.warn(
      "[ForkChatService] Fork already in progress — ignoring new request",
    );
    return current.forkChatId ?? "";
  }

  // Generate new identifiers for the fork
  const newChatId = crypto.randomUUID();

  // Fetch + slice messages synchronously before yielding
  let messages: Message[];
  try {
    messages = await chatDB.getMessagesForChat(sourceChatId);
  } catch (err) {
    console.error("[ForkChatService] Failed to fetch messages for fork:", err);
    throw err;
  }

  // Sort by created_at ascending (IndexedDB returns them sorted already, but be safe)
  messages.sort((a, b) => (a.created_at ?? 0) - (b.created_at ?? 0));

  // Slice: include only messages up to and including the fork point
  const forkIndex = messages.findIndex((m) => m.message_id === upToMessageId);
  if (forkIndex === -1) {
    console.error(
      "[ForkChatService] upToMessageId not found in messages:",
      upToMessageId,
    );
    throw new Error("Fork point message not found");
  }
  const messagesToCopy = messages.slice(0, forkIndex + 1);

  // Register in the progress store — UI components can now render progress
  forkProgressStore.start(
    sourceChatId,
    newChatId,
    forkTitle,
    messagesToCopy.length,
  );

  // Run the actual work asynchronously so the caller returns immediately
  runForkAsync(sourceChatId, newChatId, forkTitle, messagesToCopy).catch(
    (err) => {
      console.error("[ForkChatService] Fork failed:", err);
      forkProgressStore.fail(err?.message ?? "Unknown error");
      notificationStore.error("fork.error_notification");
    },
  );

  return newChatId;
}

// ---------------------------------------------------------------------------
// Internal async implementation
// ---------------------------------------------------------------------------

async function runForkAsync(
  sourceChatId: string,
  newChatId: string,
  forkTitle: string,
  messagesToCopy: Message[],
): Promise<void> {
  console.info(
    `[ForkChatService] Starting fork: ${sourceChatId} → ${newChatId} ` +
      `(${messagesToCopy.length} messages, title: "${forkTitle}")`,
  );

  // Step 1: Generate a fresh AES key for the new chat
  const newChatKey = generateChatKey();

  // Step 2: Encrypt the new chat key with the user's master key so it can be
  //         stored in IndexedDB + sent to the server in encrypted form.
  const encryptedNewChatKey = await encryptChatKeyWithMasterKey(newChatKey);
  if (!encryptedNewChatKey) {
    throw new Error("Failed to encrypt new chat key with master key");
  }

  // Step 3: Encrypt the fork title with the new chat key
  const encryptedTitle = await encryptWithChatKey(forkTitle, newChatKey);

  // Step 4: Build the new Chat record
  const nowTimestamp = Math.floor(Date.now() / 1000);
  const newChatRecord: Chat = {
    chat_id: newChatId,
    encrypted_title: encryptedTitle,
    encrypted_chat_key: encryptedNewChatKey,
    messages_v: messagesToCopy.length,
    title_v: 1,
    last_edited_overall_timestamp: nowTimestamp,
    unread_count: 0,
    created_at: nowTimestamp,
    updated_at: nowTimestamp,
    // Inherit user ownership from the source chat (resolved below)
    user_id: undefined,
  };

  // Resolve user ownership from the source chat
  try {
    const sourceChat = await chatDB.getChat(sourceChatId);
    if (sourceChat?.user_id) {
      newChatRecord.user_id = sourceChat.user_id;
    }
  } catch {
    // Non-fatal — continue without user_id
  }

  // Step 5: Re-encrypt all messages with the new chat key in batches
  const reencryptedMessages: Message[] = [];
  const newChatSuffix = newChatId.slice(-10);
  let processed = 0;

  for (let i = 0; i < messagesToCopy.length; i += BATCH_SIZE) {
    const batch = messagesToCopy.slice(i, i + BATCH_SIZE);

    for (const sourceMsg of batch) {
      const newMessageId = `${newChatSuffix}-${crypto.randomUUID()}`;
      const reencrypted = await reencryptMessage(
        sourceMsg,
        newChatId,
        newMessageId,
        newChatKey,
      );
      reencryptedMessages.push(reencrypted);
    }

    processed += batch.length;
    forkProgressStore.updateProgress(processed);

    // Yield to the event loop so the UI stays responsive
    await yieldToEventLoop();
  }

  // Step 6: Save the new chat to IndexedDB
  // We set the chat key in the db instance cache directly so encryptChatForStorage
  // will find it and skip re-generation.
  chatDB.setChatKey(newChatId, newChatKey);
  // Save the pre-built record (already has encrypted_chat_key set)
  await chatDB.addChat(newChatRecord);

  // Step 7: Save all re-encrypted messages
  await chatDB.batchSaveMessages(reencryptedMessages);

  // Step 8: Sync to the server via WebSocket.
  // We send each message through the chat_message_added flow so the server
  // persists them to Directus. If offline, we queue them for later.
  await syncForkToServer(newChatId, encryptedNewChatKey, reencryptedMessages);

  // Step 9: Also sync the title to the server
  syncForkTitleToServer(newChatId, encryptedTitle);

  // Done!
  forkProgressStore.complete();
  console.info(`[ForkChatService] Fork complete: new chat ${newChatId}`);

  // Show a "fork complete" notification that opens the forked chat on click
  notificationStore.addNotificationWithOptions("success", {
    message: "chats.fork.complete_notification",
    duration: 12000,
    dismissible: true,
    onAction: () => {
      activeChatStore.setActiveChat(newChatId);
      forkProgressStore.reset();
    },
    actionLabel: "chats.fork.complete_notification",
  });
}

// ---------------------------------------------------------------------------
// Re-encrypt a single message with a new chat key
// ---------------------------------------------------------------------------

/**
 * Create a copy of `sourceMsg` with:
 * - New message_id (based on the new chat's suffix)
 * - New chat_id (the fork's chat ID)
 * - All encrypted fields re-encrypted with the new chat key
 * - Plaintext fields removed (zero-knowledge)
 */
async function reencryptMessage(
  sourceMsg: Message,
  newChatId: string,
  newMessageId: string,
  newChatKey: Uint8Array,
): Promise<Message> {
  // Start with a clean copy (no encrypted_ fields yet)
  const newMsg: Message = {
    message_id: newMessageId,
    chat_id: newChatId,
    role: sourceMsg.role,
    created_at: sourceMsg.created_at,
    status: "synced",
    // Preserve pair linkage semantics — note: user_message_id will point to the
    // source chat's original IDs, which won't exist in the fork. We clear it to
    // avoid stale references. This is acceptable: pair linking is only used for
    // the "delete paired message" feature.
    user_message_id: undefined,
  };

  // Re-encrypt content (should already be decrypted since getMessagesForChat decrypts)
  if (sourceMsg.content) {
    const contentString =
      typeof sourceMsg.content === "string"
        ? sourceMsg.content
        : JSON.stringify(sourceMsg.content);
    newMsg.encrypted_content = await encryptWithChatKey(
      contentString,
      newChatKey,
    );
  } else if (sourceMsg.encrypted_content) {
    // Fallback: content wasn't decrypted (demo chat or already-encrypted blob)
    // For demo chats we store as-is; for others this should not normally happen
    newMsg.encrypted_content = sourceMsg.encrypted_content;
  }

  // Re-encrypt sender_name
  if (sourceMsg.sender_name) {
    newMsg.encrypted_sender_name = await encryptWithChatKey(
      sourceMsg.sender_name,
      newChatKey,
    );
  }

  // Re-encrypt category
  if (sourceMsg.category) {
    newMsg.encrypted_category = await encryptWithChatKey(
      sourceMsg.category,
      newChatKey,
    );
  }

  // Re-encrypt model_name
  if (sourceMsg.model_name) {
    newMsg.encrypted_model_name = await encryptWithChatKey(
      sourceMsg.model_name,
      newChatKey,
    );
  }

  // We intentionally do NOT copy thinking_content, thinking_signature, or
  // pii_mappings — they are sensitive and not needed in a fork context.

  return newMsg;
}

// ---------------------------------------------------------------------------
// Server sync helpers
// ---------------------------------------------------------------------------

/**
 * Send all forked messages to the server one by one via WebSocket.
 * If the WebSocket is disconnected, we fall back to saving them as offline
 * messages — the existing sync_offline_changes flow will pick them up on reconnect.
 *
 * NOTE: We do NOT use the sync_offline_changes payload here because that payload
 * only supports title/draft changes. Instead we send individual chat_message_added
 * events, which is how all normal messages are persisted.
 */
async function syncForkToServer(
  newChatId: string,
  encryptedChatKey: string,
  messages: Message[],
): Promise<void> {
  const isConnected = get(websocketStatus).status === "connected";

  if (!isConnected) {
    // Offline: messages are already saved in IndexedDB. When the user comes back
    // online, the phased sync will detect the new chat via initial_sync and the
    // server will request the missing messages.
    console.info(
      `[ForkChatService] WebSocket offline — fork messages saved locally, ` +
        `will sync via initial_sync on reconnect`,
    );
    return;
  }

  // Send messages in small batches to avoid flooding the WebSocket
  const SEND_BATCH = 5;
  for (let i = 0; i < messages.length; i += SEND_BATCH) {
    const batch = messages.slice(i, i + SEND_BATCH);
    for (const msg of batch) {
      try {
        await webSocketService.sendMessage("chat_message_added", {
          chat_id: newChatId,
          message: msg,
          encrypted_chat_key: encryptedChatKey,
          is_fork: true, // Hint to server: skip AI triggering for fork messages
        });
      } catch (err) {
        // Non-fatal: if a single message fails to send, log and continue.
        // The initial_sync mechanism will reconcile on next login.
        console.warn(
          `[ForkChatService] Failed to sync message ${msg.message_id}:`,
          err,
        );
      }
    }
    await yieldToEventLoop();
  }
}

/**
 * Send the fork chat's title to the server via the update_title WebSocket event.
 */
function syncForkTitleToServer(
  newChatId: string,
  encryptedTitle: string,
): void {
  const isConnected = get(websocketStatus).status === "connected";
  if (!isConnected) return;

  webSocketService
    .sendMessage("update_title", {
      chat_id: newChatId,
      encrypted_title: encryptedTitle,
    })
    .catch((err) => {
      console.warn("[ForkChatService] Failed to sync fork title:", err);
    });
}

// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------

/**
 * Yield execution to the event loop so the browser can process other tasks
 * (re-renders, user input, etc.) between encryption batches.
 */
function yieldToEventLoop(): Promise<void> {
  return new Promise((resolve) => {
    if (typeof requestAnimationFrame !== "undefined") {
      requestAnimationFrame(() => resolve());
    } else {
      setTimeout(resolve, BATCH_DELAY_MS);
    }
  });
}
