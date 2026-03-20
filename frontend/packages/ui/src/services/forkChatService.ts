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
//   5. Copy category + icon from source chat (decrypt with source key, re-encrypt with new key).
//   6. Save the new chat + all copied messages in one IndexedDB transaction.
//   7. Sync to the server via encrypted_chat_metadata:
//      - message_history (encrypted) + chat metadata → Directus
//        (permanent encrypted persistence of all messages + title/category/icon)
//   8. Update forkProgressStore throughout to drive UI.
//   9. On completion: fire a "fork complete" notification that opens the new chat.
//
// AI context on first follow-up:
//   The forked chat has no server-side AI cache. When the user sends their first
//   follow-up message, the backend sends request_chat_history, and the client
//   responds with all messages from IndexedDB (including active_focus_id). This
//   is the same recovery mechanism used by all client-created chats (inspiration,
//   onboarding, etc.) — no proactive plaintext sync is needed.
//
// Background processing:
//   The caller can navigate away freely while the fork runs. The operation is
//   async and non-blocking. forkProgressStore is global and survives navigation.

import { chatDB } from "./db";
import { chatKeyManager } from "./encryption/ChatKeyManager";
import { forkProgressStore } from "../stores/forkProgressStore";
import { notificationStore } from "../stores/notificationStore";
import { activeChatStore } from "../stores/activeChatStore";
import { webSocketService } from "./websocketService";
import { websocketStatus } from "../stores/websocketStatusStore";
import {
  generateChatKey,
  encryptWithChatKey,
  decryptWithChatKey,
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

  // Step 5: Copy category and icon from the source chat.
  //
  // The source chat's encrypted_category and encrypted_icon are decrypted using
  // the source chat key, then re-encrypted with the new chat key. This ensures
  // the forked chat appears in the chats list with the correct category and icon
  // immediately — without waiting for the AI to re-categorize on the first message.
  let encryptedNewCategory: string | undefined;
  let encryptedNewIcon: string | undefined;

  try {
    const sourceChat = await chatDB.getChat(sourceChatId);
    if (sourceChat?.user_id) {
      newChatRecord.user_id = sourceChat.user_id;
    }

    const sourceChatKey = await chatKeyManager.getKey(sourceChatId);
    if (sourceChatKey) {
      // Re-encrypt category
      if (sourceChat?.encrypted_category) {
        const category = await decryptWithChatKey(
          sourceChat.encrypted_category,
          sourceChatKey,
        );
        if (category) {
          encryptedNewCategory = await encryptWithChatKey(category, newChatKey);
          newChatRecord.encrypted_category = encryptedNewCategory;
          console.debug(
            `[ForkChatService] Copied category from source chat: "${category}"`,
          );
        }
      }

      // Re-encrypt icon
      if (sourceChat?.encrypted_icon) {
        const icon = await decryptWithChatKey(
          sourceChat.encrypted_icon,
          sourceChatKey,
        );
        if (icon) {
          encryptedNewIcon = await encryptWithChatKey(icon, newChatKey);
          newChatRecord.encrypted_icon = encryptedNewIcon;
          console.debug(
            `[ForkChatService] Copied icon from source chat: "${icon}"`,
          );
        }
      }
    } else {
      console.warn(
        "[ForkChatService] Source chat key not in cache — cannot copy category/icon",
      );
    }
  } catch (err) {
    // Non-fatal: fork continues even if category/icon copy fails
    console.warn(
      "[ForkChatService] Failed to copy category/icon from source chat:",
      err,
    );
  }

  // Step 6: Re-encrypt all messages with the new chat key in batches.
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

  // Step 7: Save the new chat to IndexedDB.
  // We set the chat key in the db instance cache directly so encryptChatForStorage
  // will find it and skip re-generation.
  chatDB.setChatKey(newChatId, newChatKey);
  // Save the pre-built record (already has encrypted_chat_key set)
  await chatDB.addChat(newChatRecord);

  // Step 8: Save all re-encrypted messages
  await chatDB.batchSaveMessages(reencryptedMessages);

  // Step 9: Sync fork messages + metadata to the server via encrypted_chat_metadata.
  //         This provides permanent encrypted storage in Directus, and also
  //         stores the chat metadata (title, category, icon) server-side so
  //         that other devices can sync the forked chat correctly.
  //
  //         AI context on first follow-up is handled by the request_chat_history
  //         mechanism: the backend detects an empty AI cache for this chat and
  //         asks the client for history. The client responds with all IndexedDB
  //         messages + active_focus_id via handleRequestChatHistoryImpl.
  syncForkEncryptedToStorage(
    newChatId,
    encryptedNewChatKey,
    encryptedTitle,
    encryptedNewCategory,
    encryptedNewIcon,
    reencryptedMessages,
    nowTimestamp,
    messagesToCopy.length,
  );

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
 * Sync the fork's encrypted messages and chat metadata to the server via a
 * single encrypted_chat_metadata event. The server's History Injection Flow
 * (in encrypted_chat_metadata_handler.py) picks up the message_history array
 * and persists each message to Directus via persist_new_chat_message tasks.
 *
 * Also stores the encrypted title, category, and icon so that the chat appears
 * correctly on other devices (and after a full sync cycle).
 *
 * This is fire-and-forget (not awaited) because it happens after the fork is
 * considered complete from the user's perspective.
 */
function syncForkEncryptedToStorage(
  newChatId: string,
  encryptedChatKey: string,
  encryptedTitle: string,
  encryptedCategory: string | undefined,
  encryptedIcon: string | undefined,
  reencryptedMessages: Message[],
  nowTimestamp: number,
  messageCount: number,
): void {
  const isConnected = get(websocketStatus).status === "connected";
  if (!isConnected) {
    console.info(
      "[ForkChatService] WebSocket offline — encrypted storage sync will be reconciled via phased_sync on reconnect",
    );
    return;
  }

  // Build the message_history array for the History Injection Flow.
  // The handler only persists messages that have both message_id AND encrypted_content.
  const messageHistory = reencryptedMessages
    .filter((m) => m.message_id && m.encrypted_content)
    .map((m) => ({
      message_id: m.message_id,
      chat_id: newChatId,
      role: m.role,
      encrypted_content: m.encrypted_content,
      encrypted_sender_name: m.encrypted_sender_name,
      encrypted_category: m.encrypted_category,
      encrypted_model_name: m.encrypted_model_name,
      created_at: m.created_at,
    }));

  const payload: Record<string, unknown> = {
    chat_id: newChatId,
    encrypted_chat_key: encryptedChatKey,
    encrypted_title: encryptedTitle,
    message_history: messageHistory,
    versions: {
      messages_v: messageCount,
      title_v: 1,
      last_edited_overall_timestamp: nowTimestamp,
    },
  };

  // Include category and icon if we successfully copied them from the source chat
  if (encryptedCategory) {
    payload.encrypted_chat_category = encryptedCategory;
  }
  if (encryptedIcon) {
    payload.encrypted_icon = encryptedIcon;
  }

  webSocketService
    .sendMessage("encrypted_chat_metadata", payload)
    .then(() => {
      console.info(
        `[ForkChatService] Encrypted storage sync sent for chat ${newChatId} ` +
          `(${messageHistory.length} messages, category=${!!encryptedCategory}, icon=${!!encryptedIcon})`,
      );
    })
    .catch((err) => {
      console.warn(
        "[ForkChatService] Encrypted storage sync failed (will reconcile via phased_sync):",
        err,
      );
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
