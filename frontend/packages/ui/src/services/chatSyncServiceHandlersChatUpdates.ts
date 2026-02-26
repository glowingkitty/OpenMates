// frontend/packages/ui/src/services/chatSyncServiceHandlersChatUpdates.ts
import type { ChatSynchronizationService } from "./chatSyncService";
import { chatDB } from "./db";
import { chatMetadataCache } from "./chatMetadataCache";
import { chatListCache } from "./chatListCache";
import type {
  ChatTitleUpdatedPayload,
  ChatDraftUpdatedPayload,
  ChatMessageReceivedPayload,
  ChatMessageConfirmedPayload,
  ChatDeletedPayload,
  Message,
  Chat,
  MessageRole,
} from "../types/chat";
// Imported lazily to avoid circular deps — called after each chat-key establishment
// so that system messages queued before the key was available get saved correctly.
import { flushPendingSystemMessagesForChat } from "./chatSyncServiceHandlersAppSettings";

/**
 * Pending message queue for cross-device sync.
 *
 * When a `new_chat_message` broadcast arrives from another device but the chat
 * key is not yet available (e.g. brand-new chat where the server hasn't
 * persisted `encrypted_chat_key` before broadcasting), we cannot safely call
 * `chatDB.saveMessage()` — doing so would trigger `getOrGenerateChatKey()`,
 * which generates a random throwaway key and encrypts the message with it.
 * When the real key later arrives the ciphertext can no longer be decrypted,
 * causing "[Content decryption failed]" on the receiving device.
 *
 * Solution: buffer the plaintext message here and flush it through
 * `chatDB.saveMessage()` only after the correct key has been cached via
 * `chatDB.setChatKey()`.  Call `flushPendingMessagesForChat()` from every
 * code-path that sets the key for a synced chat.
 */
const _pendingMessages: Map<string, Message[]> = new Map();

/**
 * In-memory set tracking chat IDs whose `encrypted_chat_key` has already been
 * persisted to IndexedDB during this session.
 *
 * Problem (iOS performance): The "existing chat" key-persistence block in
 * handleNewChatMessageImpl runs for EVERY `new_chat_message` WS event where
 * `!chatDB.getChatKey(chatId)`. After the first write the key IS in memory so
 * getChatKey() returns truthy and the block is skipped — but on the very first
 * message for each chat a redundant `getChat()` + `updateChat()` IDB round-trip
 * fires. On iOS, when many chats receive their first message in a burst (e.g.
 * opening the sidebar while phased sync is running), this creates a storm of IDB
 * writes + `chatUpdated` events → full `$derived` re-renders that locks up the
 * main thread.
 *
 * Fix: track which chats have had their key written this session. Skip the extra
 * getChat + updateChat entirely on repeat calls.
 */
const _chatKeyPersistedToIDB: Set<string> = new Set();

/**
 * Flush all messages that were held back because the chat key was missing.
 * Safe to call multiple times — a second call is a no-op once the queue is
 * empty.  Must be called AFTER the correct key has been set via
 * `chatDB.setChatKey(chatId, key)`.
 */
export async function flushPendingMessagesForChat(
  chatId: string,
): Promise<void> {
  const pending = _pendingMessages.get(chatId);
  if (!pending || pending.length === 0) return;

  // Remove from map immediately so concurrent flushes can't double-save
  _pendingMessages.delete(chatId);

  console.info(
    `[ChatSyncService:ChatUpdates] Flushing ${pending.length} pending message(s) for chat ${chatId} now that key is available`,
  );
  for (const msg of pending) {
    try {
      await chatDB.saveMessage(msg);
      console.debug(
        `[ChatSyncService:ChatUpdates] Flushed pending message ${msg.message_id} for chat ${chatId}`,
      );
    } catch (err) {
      console.error(
        `[ChatSyncService:ChatUpdates] Error flushing pending message ${msg.message_id} for chat ${chatId}:`,
        err,
      );
    }
  }
}

export async function handleChatTitleUpdatedImpl(
  serviceInstance: ChatSynchronizationService,
  payload: ChatTitleUpdatedPayload,
): Promise<void> {
  console.info(
    "[ChatSyncService:ChatUpdates] Received chat_title_updated:",
    payload,
  );

  // Validate payload has required properties
  if (!payload || !payload.chat_id) {
    console.error(
      "[ChatSyncService:ChatUpdates] Invalid payload in handleChatTitleUpdatedImpl: missing chat_id",
      payload,
    );
    return;
  }

  if (!payload.data || payload.data.encrypted_title === undefined) {
    console.error(
      `[ChatSyncService:ChatUpdates] Invalid payload in handleChatTitleUpdatedImpl: missing data.encrypted_title for chat_id ${payload.chat_id}`,
      payload,
    );
    return;
  }

  if (!payload.versions || payload.versions.title_v === undefined) {
    console.error(
      `[ChatSyncService:ChatUpdates] Invalid payload in handleChatTitleUpdatedImpl: missing versions.title_v for chat_id ${payload.chat_id}`,
      payload,
    );
    return;
  }

  // CRITICAL FIX: Don't reuse a single transaction across multiple async operations
  // The async decryption work in getChat() causes IndexedDB transactions to auto-commit.
  // Instead, use separate transactions for each operation.
  try {
    // First, get the chat without passing a transaction (getChat will create its own)
    const chat = await chatDB.getChat(payload.chat_id);

    if (chat) {
      // Update encrypted title from broadcast
      chat.encrypted_title = payload.data.encrypted_title;
      chat.title_v = payload.versions.title_v;
      chat.updated_at = Math.floor(Date.now() / 1000);

      // Use a separate transaction for updateChat (it will create its own internally)
      await chatDB.updateChat(chat);

      // DB operation completed successfully - dispatch event
      serviceInstance.dispatchEvent(
        new CustomEvent("chatUpdated", {
          detail: { chat_id: payload.chat_id, type: "title_updated", chat },
        }),
      );
    } else {
      console.debug(
        `[ChatSyncService:ChatUpdates] Chat ${payload.chat_id} not found for title update`,
      );
    }
  } catch (error) {
    console.error(
      "[ChatSyncService:ChatUpdates] Error in handleChatTitleUpdated:",
      error,
    );
  }
}

export async function handleChatDraftUpdatedImpl(
  serviceInstance: ChatSynchronizationService,
  payload: ChatDraftUpdatedPayload,
): Promise<void> {
  console.info(
    "[ChatSyncService:ChatUpdates] Received chat_draft_updated:",
    payload,
  );

  // Validate payload has required properties
  if (!payload || !payload.chat_id) {
    console.error(
      "[ChatSyncService:ChatUpdates] Invalid payload in handleChatDraftUpdatedImpl: missing chat_id",
      payload,
    );
    return;
  }

  if (!payload.data || payload.data.encrypted_draft_md === undefined) {
    console.error(
      `[ChatSyncService:ChatUpdates] Invalid payload in handleChatDraftUpdatedImpl: missing data.encrypted_draft_md for chat_id ${payload.chat_id}`,
      payload,
    );
    return;
  }

  if (!payload.versions || payload.versions.draft_v === undefined) {
    console.error(
      `[ChatSyncService:ChatUpdates] Invalid payload in handleChatDraftUpdatedImpl: missing versions.draft_v for chat_id ${payload.chat_id}`,
      payload,
    );
    return;
  }

  // CRITICAL FIX: Don't reuse a single transaction across multiple async operations
  // The async decryption work in getChat() causes IndexedDB transactions to auto-commit,
  // making the transaction invalid by the time updateChat() is called.
  // Instead, use separate transactions for each operation (same fix as handleChatMessageReceivedImpl).
  try {
    // First, get the chat without passing a transaction (getChat will create its own)
    const chat = await chatDB.getChat(payload.chat_id);

    if (chat) {
      console.debug(
        `[ChatSyncService:ChatUpdates] Existing chat ${payload.chat_id} found for draft update. Local draft_v: ${chat.draft_v}, Incoming draft_v: ${payload.versions.draft_v}.`,
      );

      // Check if this is a draft deletion (encrypted_draft_md is null)
      if (payload.data.encrypted_draft_md === null) {
        console.debug(
          `[ChatSyncService:ChatUpdates] Received draft deletion for chat ${payload.chat_id}`,
        );
      }

      chat.encrypted_draft_md = payload.data.encrypted_draft_md;
      chat.encrypted_draft_preview =
        payload.data.encrypted_draft_preview || null;
      chat.draft_v = payload.versions.draft_v;
      // CRITICAL: Don't update last_edited_overall_timestamp from draft updates
      // Only messages should update this timestamp for proper sorting
      // Chats with drafts will appear at the top via sorting logic (hasNonEmptyDraft check),
      // but their position among "recent" chats should be based on last message time, not draft time.
      // This prevents old chats from appearing as recent just because a draft was added/deleted.
      // See chatSortUtils.ts for the sorting contract.
      // chat.last_edited_overall_timestamp = payload.last_edited_overall_timestamp; // REMOVED
      chat.updated_at = Math.floor(Date.now() / 1000);

      // Use a separate transaction for updateChat (it will create its own internally)
      await chatDB.updateChat(chat);
    } else {
      console.warn(
        `[ChatSyncService:ChatUpdates] Chat ${payload.chat_id} not found when handling chat_draft_updated broadcast. Creating new chat entry for draft.`,
      );
      const newChatForDraft: Chat = {
        chat_id: payload.chat_id,
        encrypted_title: null,
        messages_v: 0,
        title_v: 0,
        encrypted_draft_md: payload.data.encrypted_draft_md,
        encrypted_draft_preview: payload.data.encrypted_draft_preview || null,
        draft_v: payload.versions.draft_v,
        last_edited_overall_timestamp: payload.last_edited_overall_timestamp,
        unread_count: 0,
        created_at: payload.last_edited_overall_timestamp,
        updated_at: payload.last_edited_overall_timestamp,
      };
      // Use a separate transaction for addChat (it will create its own internally)
      await chatDB.addChat(newChatForDraft);
    }

    // DB operations completed successfully - now do cache invalidation and event dispatch
    // This happens AFTER the await completes, ensuring the DB was actually updated
    console.info(
      `[ChatSyncService:ChatUpdates] DB update for handleChatDraftUpdated (chat_id: ${payload.chat_id}) completed successfully.`,
    );

    // Invalidate metadata cache since draft content changed
    chatMetadataCache.invalidateChat(payload.chat_id);

    // Dispatch event to notify UI components
    serviceInstance.dispatchEvent(
      new CustomEvent("chatUpdated", {
        detail: { chat_id: payload.chat_id, type: "draft" },
      }),
    );
  } catch (error) {
    console.error(
      `[ChatSyncService:ChatUpdates] Error in handleChatDraftUpdated for chat_id ${payload.chat_id}:`,
      error,
    );
  }
}

/**
 * Handle draft deletion from another device
 * When a draft is deleted on one device, other devices should also clear the draft
 * This prevents the stale draft from appearing on other devices
 */
export async function handleDraftDeletedImpl(
  serviceInstance: ChatSynchronizationService,
  payload: { chat_id: string },
): Promise<void> {
  console.info(
    "[ChatSyncService:ChatUpdates] Received draft_deleted from server for chat:",
    payload.chat_id,
  );

  // Validate payload
  if (!payload || !payload.chat_id) {
    console.error(
      "[ChatSyncService:ChatUpdates] Invalid payload in handleDraftDeletedImpl: missing chat_id",
      payload,
    );
    return;
  }

  // CRITICAL FIX: Don't reuse a single transaction across multiple async operations
  // The async decryption work in getChat() causes IndexedDB transactions to auto-commit.
  // Instead, use separate transactions for each operation.
  try {
    // First, get the chat without passing a transaction (getChat will create its own)
    const chat = await chatDB.getChat(payload.chat_id);

    if (chat) {
      console.debug(
        `[ChatSyncService:ChatUpdates] Clearing draft for chat ${payload.chat_id}`,
      );
      // Clear the draft since it was deleted on another device
      chat.encrypted_draft_md = null;
      chat.encrypted_draft_preview = null;
      chat.draft_v = 0;
      chat.updated_at = Math.floor(Date.now() / 1000);

      // Use a separate transaction for updateChat (it will create its own internally)
      await chatDB.updateChat(chat);

      // DB operation completed successfully - now do cache invalidation and event dispatch
      console.info(
        `[ChatSyncService:ChatUpdates] DB update for handleDraftDeleted (chat_id: ${payload.chat_id}) completed successfully.`,
      );

      // Invalidate metadata cache and dispatch event
      chatMetadataCache.invalidateChat(payload.chat_id);
      serviceInstance.dispatchEvent(
        new CustomEvent("chatUpdated", {
          detail: { chat_id: payload.chat_id, type: "draft_deleted" },
        }),
      );
    } else {
      console.debug(
        `[ChatSyncService:ChatUpdates] Chat ${payload.chat_id} not found, nothing to clear`,
      );
    }
  } catch (error) {
    console.error(
      `[ChatSyncService:ChatUpdates] Error in handleDraftDeleted for chat_id ${payload.chat_id}:`,
      error,
    );
  }
}

/**
 * Handle new_chat_message event from other devices
 * This is sent when a user message is sent from another device
 * It creates a new chat if it doesn't exist locally, or adds the message to an existing chat
 *
 * IMPORTANT: This event contains plaintext content for display purposes.
 * The encrypted chat key will arrive later via:
 * 1. ai_typing_started event (which includes encrypted metadata), OR
 * 2. Initial sync response when the client reconnects
 *
 * We create a shell chat here, but DON'T generate a chat key yet.
 * This prevents key mismatch issues between devices.
 */
export async function handleNewChatMessageImpl(
  serviceInstance: ChatSynchronizationService,
  payload: {
    chat_id: string;
    message_id: string;
    content: string;
    role?: string;
    sender_name?: string;
    created_at?: number;
    messages_v?: number;
    last_edited_overall_timestamp?: number;
    encrypted_chat_key?: string;
    /** Encrypted title — sent by sync_inspiration_chat_handler for cross-device inspiration chats */
    encrypted_title?: string;
    /** Encrypted category — sent by sync_inspiration_chat_handler for cross-device inspiration chats */
    encrypted_category?: string;
  },
): Promise<void> {
  console.info(
    "[ChatSyncService:ChatUpdates] Received new_chat_message (user message from another device):",
    payload,
  );

  // Validate payload has required properties
  if (!payload || !payload.chat_id) {
    console.error(
      "[ChatSyncService:ChatUpdates] Invalid payload in handleNewChatMessageImpl: missing chat_id",
      payload,
    );
    return;
  }

  if (!payload.message_id || !payload.content) {
    console.error(
      `[ChatSyncService:ChatUpdates] Invalid payload in handleNewChatMessageImpl: missing message data for chat_id ${payload.chat_id}`,
      payload,
    );
    return;
  }

  let isNewChat = false;

  try {
    // CRITICAL: Avoid shared transactions here because encryption/decryption is async.
    // A shared transaction can auto-commit before saveMessage/updateChat runs, which
    // prevents UI updates from firing (seen as "missing" messages on other devices).
    let chat = await chatDB.getChat(payload.chat_id);

    if (!chat) {
      // Chat doesn't exist locally - create a new chat shell
      // The encrypted_chat_key should come from the payload for proper device sync
      console.info(
        `[ChatSyncService:ChatUpdates] Creating new chat shell ${payload.chat_id} from new_chat_message event`,
      );
      isNewChat = true;

      const newChat: Chat = {
        chat_id: payload.chat_id,
        encrypted_title: payload.encrypted_title || null, // Set from payload if available (e.g. inspiration chat sync)
        encrypted_category: payload.encrypted_category || undefined, // Set from payload if available (e.g. inspiration chat sync)
        messages_v: payload.messages_v || 1,
        title_v: payload.encrypted_title ? 1 : 0, // If title is provided, mark as populated
        encrypted_draft_md: null,
        encrypted_draft_preview: null,
        draft_v: 0,
        last_edited_overall_timestamp: (() => {
          if (!payload.last_edited_overall_timestamp) {
            console.warn(
              `[ChatSyncService:ChatUpdates] new_chat_message for new chat ${payload.chat_id} missing last_edited_overall_timestamp — falling back to Date.now()`,
            );
          }
          return (
            payload.last_edited_overall_timestamp ||
            Math.floor(Date.now() / 1000)
          );
        })(),
        unread_count: 0,
        created_at: payload.created_at || Math.floor(Date.now() / 1000),
        updated_at: Math.floor(Date.now() / 1000),
        encrypted_chat_key: payload.encrypted_chat_key || undefined, // Critical for device sync
      };

      // If we have the chat key and encrypted title/category, decrypt for immediate local display
      if (
        payload.encrypted_chat_key &&
        (payload.encrypted_title || payload.encrypted_category)
      ) {
        try {
          const { decryptChatKeyWithMasterKey, decryptWithChatKey } =
            await import("./cryptoService");
          const chatKey = await decryptChatKeyWithMasterKey(
            payload.encrypted_chat_key,
          );
          if (chatKey) {
            chatDB.setChatKey(payload.chat_id, chatKey);
            // Flush any regular messages and system messages queued before this key was available
            await flushPendingMessagesForChat(payload.chat_id);
            await flushPendingSystemMessagesForChat(payload.chat_id);
            // Decrypt title for immediate display
            if (payload.encrypted_title) {
              try {
                const title = await decryptWithChatKey(
                  payload.encrypted_title,
                  chatKey,
                );
                if (title) {
                  (newChat as Chat & { title?: string }).title = title;
                }
              } catch {
                console.warn(
                  `[ChatSyncService:ChatUpdates] Failed to decrypt title for new chat ${payload.chat_id}`,
                );
              }
            }
            // Decrypt category for mate profile display
            if (payload.encrypted_category) {
              try {
                const category = await decryptWithChatKey(
                  payload.encrypted_category,
                  chatKey,
                );
                if (category) {
                  (newChat as Chat & { category?: string }).category = category;
                }
              } catch {
                console.warn(
                  `[ChatSyncService:ChatUpdates] Failed to decrypt category for new chat ${payload.chat_id}`,
                );
              }
            }
            console.info(
              `[ChatSyncService:ChatUpdates] Decrypted title/category from payload for new chat ${payload.chat_id}`,
            );
          }
        } catch (error) {
          console.warn(
            `[ChatSyncService:ChatUpdates] Error decrypting title/category for new chat ${payload.chat_id}:`,
            error,
          );
        }
      }

      // If encrypted_chat_key is provided and we haven't already decrypted it above
      // (the title/category block already decrypts + caches the key), decrypt it now.
      if (payload.encrypted_chat_key && !chatDB.getChatKey(payload.chat_id)) {
        try {
          const { decryptChatKeyWithMasterKey } =
            await import("./cryptoService");
          const chatKey = await decryptChatKeyWithMasterKey(
            payload.encrypted_chat_key,
          );
          if (chatKey) {
            chatDB.setChatKey(payload.chat_id, chatKey);
            // Flush any regular messages and system messages queued before this key was set
            await flushPendingMessagesForChat(payload.chat_id);
            await flushPendingSystemMessagesForChat(payload.chat_id);
            console.info(
              `[ChatSyncService:ChatUpdates] Decrypted and cached chat key for new chat ${payload.chat_id}`,
            );
          } else {
            console.error(
              `[ChatSyncService:ChatUpdates] Failed to decrypt chat key for new chat ${payload.chat_id}`,
            );
          }
        } catch (error) {
          console.error(
            `[ChatSyncService:ChatUpdates] Error decrypting chat key for new chat ${payload.chat_id}:`,
            error,
          );
        }
      } else if (!payload.encrypted_chat_key) {
        console.warn(
          `[ChatSyncService:ChatUpdates] No encrypted_chat_key in payload for new chat ${payload.chat_id}. Message will be queued until key arrives via ai_typing_started.`,
        );
      }

      await chatDB.addChat(newChat);
      chat = newChat; // Use the newly created chat for message saving
      console.info(
        `[ChatSyncService:ChatUpdates] Created new chat shell ${payload.chat_id} successfully`,
      );
    } else if (
      payload.encrypted_chat_key &&
      !chatDB.getChatKey(payload.chat_id)
    ) {
      // Existing chat without cached key - try to decrypt and cache for immediate encryption
      try {
        const { decryptChatKeyWithMasterKey } = await import("./cryptoService");
        const chatKey = await decryptChatKeyWithMasterKey(
          payload.encrypted_chat_key,
        );
        if (chatKey) {
          chatDB.setChatKey(payload.chat_id, chatKey);
          console.info(
            `[ChatSyncService:ChatUpdates] Decrypted and cached chat key for existing chat ${payload.chat_id}`,
          );
          // Flush any regular messages and system messages that arrived before the key was available
          await flushPendingMessagesForChat(payload.chat_id);
          await flushPendingSystemMessagesForChat(payload.chat_id);
          // Also persist encrypted_chat_key to the IDB chat record so the key survives page reload.
          // Without this, the key is only in memory — lost on refresh for the "existing chat" path.
          // Guard: only run the getChat + updateChat IDB round-trip once per session per chat.
          // On iOS, many chats receiving their first WS message in a burst creates a storm of IDB
          // writes that locks up the main thread. After the first write the record already has the
          // key, so subsequent calls would be no-ops — skip them entirely.
          if (!_chatKeyPersistedToIDB.has(payload.chat_id)) {
            _chatKeyPersistedToIDB.add(payload.chat_id);
            const existingChatRecord = await chatDB.getChat(payload.chat_id);
            if (
              existingChatRecord &&
              !existingChatRecord.encrypted_chat_key &&
              payload.encrypted_chat_key
            ) {
              await chatDB.updateChat({
                ...existingChatRecord,
                encrypted_chat_key: payload.encrypted_chat_key,
              });
              console.debug(
                `[ChatSyncService:ChatUpdates] Persisted encrypted_chat_key to IDB for existing chat ${payload.chat_id}`,
              );
            }
          }
        }
      } catch (error) {
        console.error(
          `[ChatSyncService:ChatUpdates] Error decrypting chat key for existing chat ${payload.chat_id}:`,
          error,
        );
      }
    }

    // Create the message object from the payload
    // NOTE: This is plaintext content from the broadcast for immediate display
    // The message will be encrypted when saved via chatDB.saveMessage()
    const newMessage: Message = {
      message_id: payload.message_id,
      chat_id: payload.chat_id,
      role: (payload.role || "user") as MessageRole,
      sender_name: payload.sender_name,
      content: payload.content, // This is plaintext from the broadcast
      created_at: payload.created_at || Math.floor(Date.now() / 1000),
      status: "synced", // Message comes from server, so it's already synced
      encrypted_content: "", // Will be populated by chatDB.saveMessage()
    };

    // CRITICAL: Only save via chatDB.saveMessage() if the chat key is already cached.
    // If the key is absent (brand-new chat where the server broadcast fired before the
    // key was persisted), saveMessage() would call getOrGenerateChatKey() which silently
    // generates a random throwaway key — encrypting the message with the wrong key.
    // When the real key later arrives the ciphertext cannot be decrypted, causing
    // "[Content decryption failed]" on this device.
    //
    // Instead, push the message into the pending queue and flush it in
    // flushPendingMessagesForChat() once the correct key is available.
    if (chatDB.getChatKey(payload.chat_id)) {
      await chatDB.saveMessage(newMessage);
      console.debug(
        `[ChatSyncService:ChatUpdates] Saved new message ${payload.message_id} to chat ${payload.chat_id}`,
      );
    } else {
      // Queue the message — will be flushed when key arrives (ai_typing_started or Phase 1)
      const queue = _pendingMessages.get(payload.chat_id) ?? [];
      queue.push(newMessage);
      _pendingMessages.set(payload.chat_id, queue);
      console.warn(
        `[ChatSyncService:ChatUpdates] No chat key for ${payload.chat_id} — queued message ${payload.message_id} (queue length: ${queue.length}). Will save once key arrives.`,
      );
    }

    // Update chat metadata
    chat.messages_v = payload.messages_v || chat.messages_v + 1;
    if (!payload.last_edited_overall_timestamp) {
      console.warn(
        `[ChatSyncService:ChatUpdates] new_chat_message for existing chat ${payload.chat_id} missing last_edited_overall_timestamp — falling back to Date.now()`,
      );
    }
    chat.last_edited_overall_timestamp =
      payload.last_edited_overall_timestamp || Math.floor(Date.now() / 1000);
    chat.updated_at = Math.floor(Date.now() / 1000);

    await chatDB.updateChat(chat);

    // Invalidate metadata cache so chat list reloads updated data
    chatMetadataCache.invalidateChat(payload.chat_id);

    console.info(
      `[ChatSyncService:ChatUpdates] Successfully processed new_chat_message for chat ${payload.chat_id}`,
    );
    // Dispatch event to update UI immediately (no transaction callback needed)
    serviceInstance.dispatchEvent(
      new CustomEvent("chatUpdated", {
        detail: {
          chat_id: payload.chat_id,
          newMessage,
          chat,
          isNewChat, // Indicate if this was a newly created chat
        },
      }),
    );
  } catch (error) {
    console.error(
      "[ChatSyncService:ChatUpdates] Error in handleNewChatMessage:",
      error,
    );
  }
}

export async function handleChatMessageReceivedImpl(
  serviceInstance: ChatSynchronizationService,
  payload: ChatMessageReceivedPayload,
): Promise<void> {
  console.info(
    "[ChatSyncService:ChatUpdates] Received chat_message_added (broadcast from server for other users/AI):",
    payload,
  );

  // Validate payload has required properties
  if (!payload || !payload.chat_id) {
    console.error(
      "[ChatSyncService:ChatUpdates] Invalid payload in handleChatMessageReceivedImpl: missing chat_id",
      payload,
    );
    return;
  }

  if (!payload.message) {
    console.error(
      `[ChatSyncService:ChatUpdates] Invalid payload in handleChatMessageReceivedImpl: missing message for chat_id ${payload.chat_id}`,
      payload,
    );
    return;
  }

  const incomingMessage = payload.message as Message;

  const taskInfo = serviceInstance.activeAITasks.get(payload.chat_id);
  if (
    incomingMessage.role === "assistant" &&
    taskInfo &&
    taskInfo.taskId === incomingMessage.message_id
  ) {
    serviceInstance.activeAITasks.delete(payload.chat_id);
    serviceInstance.dispatchEvent(
      new CustomEvent("aiTaskEnded", {
        detail: {
          chatId: payload.chat_id,
          taskId: taskInfo.taskId,
          status: "completed_message_received",
        },
      }),
    );
    console.info(
      `[ChatSyncService:ChatUpdates] AI Task ${taskInfo.taskId} for chat ${payload.chat_id} considered ended as full AI message was received.`,
    );
  }

  // CRITICAL: For AI messages, send encrypted content back to server for Directus storage
  // This is part of the zero-knowledge architecture where the client encrypts and sends back
  // This handles the case where streaming events weren't processed (e.g., timing issues, component not ready)
  // FIX: Only send if status is NOT 'synced'. If it's already 'synced', the server already has it.
  // This prevents duplicate 'ai_response_storage_confirmed' events and potential double messages.
  if (
    incomingMessage.role === "assistant" &&
    incomingMessage.status !== "synced"
  ) {
    try {
      console.debug(
        "[ChatSyncService:ChatUpdates] Sending AI response to server for Directus storage:",
        {
          messageId: incomingMessage.message_id,
          chatId: incomingMessage.chat_id,
          contentLength: incomingMessage.content?.length || 0,
          status: incomingMessage.status,
        },
      );
      // Use type assertion to access the method
      await serviceInstance.sendCompletedAIResponse(incomingMessage);
    } catch (error) {
      console.error(
        "[ChatSyncService:ChatUpdates] Error sending AI response to server:",
        error,
      );
    }
  } else if (incomingMessage.role === "assistant") {
    console.debug(
      "[ChatSyncService:ChatUpdates] Skipping AI response storage - message already synced:",
      {
        messageId: incomingMessage.message_id,
        chatId: incomingMessage.chat_id,
        status: incomingMessage.status,
      },
    );
  }

  // CRITICAL FIX: Don't reuse a single transaction across multiple async operations
  // Instead, use separate transactions for each operation to avoid InvalidStateError
  try {
    // Ensure incomingMessage has a chat_id. If not, use the payload's chat_id.
    // This is crucial for AI messages that might arrive without chat_id embedded in the message object itself.
    if (!incomingMessage.chat_id && payload.chat_id) {
      console.warn(
        `[ChatSyncService:ChatUpdates] handleChatMessageReceivedImpl: incomingMessage (role: ${incomingMessage.role}, id: ${incomingMessage.message_id}) was missing chat_id. Populating from payload.chat_id: ${payload.chat_id}`,
      );
      incomingMessage.chat_id = payload.chat_id;
    } else if (incomingMessage.chat_id !== payload.chat_id) {
      console.warn(
        `[ChatSyncService:ChatUpdates] handleChatMessageReceivedImpl: incomingMessage.chat_id (${incomingMessage.chat_id}) differs from payload.chat_id (${payload.chat_id}). Using payload.chat_id for consistency with chat context.`,
      );
      incomingMessage.chat_id = payload.chat_id;
    }

    // Check if this is an incognito chat
    const { incognitoChatService } = await import("./incognitoChatService");
    let chat: Chat | null = null;
    let isIncognitoChat = false;

    try {
      chat = await incognitoChatService.getChat(payload.chat_id);
      if (chat) {
        isIncognitoChat = true;
      }
    } catch {
      // Not an incognito chat, continue to check IndexedDB
    }

    if (!chat) {
      chat = await chatDB.getChat(payload.chat_id);
    }

    if (isIncognitoChat && chat) {
      // Save to incognito service (no encryption needed)
      await incognitoChatService.addMessage(payload.chat_id, incomingMessage);
      chat.messages_v = payload.versions.messages_v;
      chat.last_edited_overall_timestamp =
        payload.last_edited_overall_timestamp;
      chat.updated_at = Math.floor(Date.now() / 1000);
      await incognitoChatService.updateChat(payload.chat_id, {
        messages_v: chat.messages_v,
        last_edited_overall_timestamp: chat.last_edited_overall_timestamp,
        updated_at: chat.updated_at,
      });
      console.info(
        `[ChatSyncService:ChatUpdates] Updated incognito chat ${payload.chat_id} with messages_v: ${chat.messages_v}`,
      );
      serviceInstance.dispatchEvent(
        new CustomEvent("chatUpdated", {
          detail: {
            chat_id: payload.chat_id,
            newMessage: incomingMessage,
            chat: chat,
          },
        }),
      );
    } else if (chat) {
      // Use separate transactions for each operation to avoid InvalidStateError
      await chatDB.saveMessage(incomingMessage);

      // CRITICAL: Only update specific fields, preserve all encrypted metadata
      // Create a minimal update object that only touches what we need to change
      const chatUpdate: Chat = {
        ...chat, // Preserve ALL existing fields including encrypted_title, encrypted_icon, encrypted_category
        messages_v: payload.versions.messages_v,
        last_edited_overall_timestamp: payload.last_edited_overall_timestamp,
        updated_at: Math.floor(Date.now() / 1000),
      };

      console.debug(
        `[ChatSyncService:ChatUpdates] Updating chat ${payload.chat_id} with messages_v: ${chatUpdate.messages_v}`,
        {
          preservedEncryptedTitle: !!chatUpdate.encrypted_title,
          preservedEncryptedIcon: !!chatUpdate.encrypted_icon,
          preservedEncryptedCategory: !!chatUpdate.encrypted_category,
        },
      );

      // Use a new transaction for updateChat
      await chatDB.updateChat(chatUpdate);

      // Dispatch with the full chat object from DB to ensure consistency
      const finalChatState = await chatDB.getChat(payload.chat_id);
      console.info(
        `[ChatSyncService:ChatUpdates] Chat ${payload.chat_id} updated with messages_v: ${chatUpdate.messages_v}`,
      );
      serviceInstance.dispatchEvent(
        new CustomEvent("chatUpdated", {
          detail: {
            chat_id: payload.chat_id,
            newMessage: incomingMessage,
            chat: finalChatState || chatUpdate,
          },
        }),
      );
    } else {
      // This case implies a message arrived for a chat not in local DB.
      // This could happen if initial sync was incomplete or chat was deleted locally then message arrived.
      // For now, log a warning. A more robust solution might involve creating a shell chat.
      console.warn(
        `[ChatSyncService:ChatUpdates] Chat ${payload.chat_id} not found when handling 'chat_message_added'. Message ID: ${incomingMessage.message_id}.`,
      );
    }
  } catch (error) {
    console.error(
      "[ChatSyncService:ChatUpdates] Error in handleChatMessageReceived:",
      error,
    );
  }
}

export async function handleChatMessageConfirmedImpl(
  serviceInstance: ChatSynchronizationService,
  payload: ChatMessageConfirmedPayload,
): Promise<void> {
  console.info(
    "[ChatSyncService:ChatUpdates] Received chat_message_confirmed for this client's message:",
    payload,
  );

  // Validate payload has required properties
  if (!payload || !payload.chat_id) {
    console.error(
      "[ChatSyncService:ChatUpdates] Invalid payload in handleChatMessageConfirmedImpl: missing chat_id",
      payload,
    );
    return;
  }

  if (!payload.message_id) {
    console.error(
      `[ChatSyncService:ChatUpdates] Invalid payload in handleChatMessageConfirmedImpl: missing message_id for chat_id ${payload.chat_id}`,
      payload,
    );
    return;
  }

  // CRITICAL FIX: Use updateMessageStatus() instead of getMessage() → mutate → saveMessage().
  //
  // The naive mutate-and-save approach triggers encryptMessageFields() which calls
  // getOrGenerateChatKey(). If the chat key has been evicted from the in-memory cache
  // (a real race condition during the new-chat flow), a NEW random key is generated and
  // the message is silently re-encrypted with it — while encrypted_chat_key on the chat
  // still holds the original key. Subsequent decryption attempts use the original key and
  // fail with "[Content decryption failed]" on the sending device. Other devices, which
  // only ever received the server-persisted copy (encrypted with the correct original key),
  // are unaffected and work fine.
  //
  // updateMessageStatus() reads the raw (still-encrypted) IndexedDB record, patches ONLY
  // the status field, and writes it back — no encryption, no key operations, no risk.
  try {
    await chatDB.updateMessageStatus(payload.message_id, "synced");

    // Verify the message belongs to this chat (log only; updateMessageStatus already
    // succeeded so there is nothing to roll back).
    const confirmedMessage = await chatDB.getMessage(payload.message_id);
    if (!confirmedMessage) {
      console.warn(
        `[ChatSyncService:ChatUpdates] Confirmed message (id: ${payload.message_id}) not found in local DB for chat ${payload.chat_id}.`,
      );
    } else if (confirmedMessage.chat_id !== payload.chat_id) {
      console.warn(
        `[ChatSyncService:ChatUpdates] Confirmed message (id: ${payload.message_id}) belongs to chat ${confirmedMessage.chat_id} instead of expected ${payload.chat_id}.`,
      );
    }

    const chat = await chatDB.getChat(payload.chat_id);
    if (chat) {
      // Only update if the values are defined and valid
      if (
        payload.new_messages_v !== undefined &&
        payload.new_messages_v !== null
      ) {
        chat.messages_v = payload.new_messages_v;
      }
      if (
        payload.new_last_edited_overall_timestamp !== undefined &&
        payload.new_last_edited_overall_timestamp !== null
      ) {
        chat.last_edited_overall_timestamp =
          payload.new_last_edited_overall_timestamp;
      }
      chat.updated_at = Math.floor(Date.now() / 1000);
      // Use a new transaction for updateChat
      await chatDB.updateChat(chat);

      // Dispatch events after successful update
      serviceInstance.dispatchEvent(
        new CustomEvent("messageStatusChanged", {
          detail: {
            chatId: payload.chat_id,
            messageId: payload.message_id,
            status: "synced",
            chat,
          },
        }),
      );
      serviceInstance.dispatchEvent(
        new CustomEvent("chatUpdated", {
          detail: {
            chat_id: payload.chat_id,
            chat,
          },
        }),
      );
    } else {
      console.warn(
        `[ChatSyncService:ChatUpdates] Chat ${payload.chat_id} not found for message confirmation.`,
      );
    }
  } catch (error) {
    console.error(
      "[ChatSyncService:ChatUpdates] Error in handleChatMessageConfirmed:",
      error,
    );
  }
}

export async function handleChatDeletedImpl(
  serviceInstance: ChatSynchronizationService,
  payload: ChatDeletedPayload,
): Promise<void> {
  console.info(
    "[ChatSyncService:ChatUpdates] Received chat_deleted from server:",
    payload,
  );

  // Validate payload has required properties
  if (!payload || !payload.chat_id) {
    console.error(
      "[ChatSyncService:ChatUpdates] Invalid payload in handleChatDeletedImpl: missing chat_id",
      payload,
    );
    return;
  }

  if (payload.tombstone) {
    try {
      // Clean up pending deletion entry if this chat was queued for offline deletion.
      // The server has now confirmed the deletion, so we can remove it from the queue.
      const { removePendingChatDeletion } =
        await import("./pendingChatDeletions");
      removePendingChatDeletion(payload.chat_id);

      // Check if chat still exists before attempting delete
      const chatExists = await chatDB.getChat(payload.chat_id);

      if (chatExists) {
        // Chat exists - this deletion was initiated by another device
        console.debug(
          `[ChatSyncService:ChatUpdates] Chat ${payload.chat_id} exists, deleting from IndexedDB (initiated by another device)`,
        );
        await chatDB.deleteChat(payload.chat_id);
        console.debug(
          `[ChatSyncService:ChatUpdates] Chat ${payload.chat_id} deleted from IndexedDB`,
        );

        // Dispatch event to update UI since this is a deletion from another device
        serviceInstance.dispatchEvent(
          new CustomEvent("chatDeleted", {
            detail: { chat_id: payload.chat_id },
          }),
        );
        console.debug(
          `[ChatSyncService:ChatUpdates] chatDeleted event dispatched for chat ${payload.chat_id}`,
        );
      } else {
        // Chat already deleted - this was an optimistic delete from this device
        console.debug(
          `[ChatSyncService:ChatUpdates] Chat ${payload.chat_id} already deleted (optimistic delete from this device)`,
        );
        // No need to dispatch event - it was already dispatched during optimistic delete
      }
    } catch (error) {
      console.error(
        "[ChatSyncService:ChatUpdates] Error in handleChatDeleted (calling chatDB.deleteChat):",
        error,
      );
    }
  }
}

/**
 * Handle metadata for encryption - Dual-Phase Architecture
 * Server sends plaintext metadata (title, category) for client-side encryption
 */
export async function handleChatMetadataForEncryptionImpl(
  serviceInstance: ChatSynchronizationService,
  payload: {
    chat_id: string;
    plaintext_title?: string;
    plaintext_category?: string;
    plaintext_icon?: string;
    task_id?: string;
  },
): Promise<void> {
  console.info(
    "[ChatSyncService:ChatUpdates] Received chat_metadata_for_encryption:",
    payload,
  );

  // Validate payload
  if (!payload || !payload.chat_id) {
    console.error(
      "[ChatSyncService:ChatUpdates] Invalid payload: missing chat_id",
      payload,
    );
    return;
  }

  try {
    const {
      chat_id,
      plaintext_title,
      plaintext_category,
      plaintext_icon,
      task_id,
    } = payload;

    // Get the current chat to access stored user message for encryption
    const chat = await chatDB.getChat(chat_id);
    if (!chat) {
      console.error(
        `[ChatSyncService:ChatUpdates] Chat ${chat_id} not found for metadata encryption`,
      );
      return;
    }

    // Get the user's pending message (the one being processed)
    // This should be the most recent user message in the chat
    const messages = await chatDB.getMessagesForChat(chat_id);
    const userMessage = messages
      .filter((m) => m.role === "user")
      .sort((a, b) => b.created_at - a.created_at)[0];

    if (!userMessage) {
      console.error(
        `[ChatSyncService:ChatUpdates] No user message found for chat ${chat_id} to encrypt`,
      );
      return;
    }

    console.info(
      `[ChatSyncService:ChatUpdates] Updating local chat with encrypted metadata for chat ${chat_id}:`,
      {
        hasTitle: !!plaintext_title,
        hasCategory: !!plaintext_category,
        hasIcon: !!plaintext_icon,
        hasUserMessage: !!userMessage,
        taskId: task_id,
      },
    );

    // PHASE 2: Update local chat with encrypted metadata
    // Get or generate chat key for encryption
    const chatKey = chatDB.getOrGenerateChatKey(chat_id);

    // Import chat-specific encryption function
    const { encryptWithChatKey } = await import("./cryptoService");

    // Encrypt metadata with chat-specific key for local storage
    let encryptedTitle: string | null = null;
    if (plaintext_title) {
      encryptedTitle = await encryptWithChatKey(plaintext_title, chatKey);
    }

    let encryptedIcon: string | null = null;
    if (plaintext_icon) {
      encryptedIcon = await encryptWithChatKey(plaintext_icon, chatKey);
    }

    let encryptedCategory: string | null = null;
    if (plaintext_category) {
      encryptedCategory = await encryptWithChatKey(plaintext_category, chatKey);
    }

    // Update local chat with encrypted metadata
    // CRITICAL FIX: Don't reuse a single transaction across multiple async operations
    // The async decryption work in getChat() causes IndexedDB transactions to auto-commit.
    // Instead, use separate transactions for each operation.
    try {
      // First, get the chat without passing a transaction (getChat will create its own)
      const chatToUpdate = await chatDB.getChat(chat_id);
      if (chatToUpdate) {
        // Update chat with encrypted metadata
        if (encryptedTitle) {
          chatToUpdate.encrypted_title = encryptedTitle;
          chatToUpdate.title_v = (chatToUpdate.title_v || 0) + 1; // Frontend increments title_v
        }

        if (encryptedIcon) {
          chatToUpdate.encrypted_icon = encryptedIcon;
        }

        if (encryptedCategory) {
          chatToUpdate.encrypted_category = encryptedCategory;
        }

        // Update timestamps
        chatToUpdate.updated_at = Math.floor(Date.now() / 1000);

        // Use a separate transaction for updateChat (it will create its own internally)
        await chatDB.updateChat(chatToUpdate);

        // DB operation completed successfully - dispatch event
        console.info(
          `[ChatSyncService:ChatUpdates] Local chat ${chat_id} updated with encrypted metadata`,
        );
        serviceInstance.dispatchEvent(
          new CustomEvent("chatUpdated", {
            detail: { chat_id, type: "metadata_updated", chat: chatToUpdate },
          }),
        );
      } else {
        console.error(
          `[ChatSyncService:ChatUpdates] Chat ${chat_id} not found for metadata update`,
        );
        return;
      }
    } catch (error) {
      console.error(
        `[ChatSyncService:ChatUpdates] Error updating local chat ${chat_id}:`,
        error,
      );
      return;
    }

    // Import the storage sender
    const { sendEncryptedStoragePackage } =
      await import("./chatSyncServiceSenders");

    // Send encrypted storage package to server for permanent storage
    await sendEncryptedStoragePackage(serviceInstance, {
      chat_id,
      plaintext_title,
      plaintext_category,
      plaintext_icon,
      user_message: userMessage,
      task_id,
    });
  } catch (error) {
    console.error(
      "[ChatSyncService:ChatUpdates] Error handling metadata for encryption:",
      error,
    );
  }
}

/**
 * Handle encrypted_chat_metadata events from server
 * This is broadcast when encrypted_chat_key is updated (e.g., when a chat is hidden/unhidden)
 *
 * @param serviceInstance ChatSynchronizationService instance
 * @param payload Payload containing chat_id and encrypted_chat_key
 */
export async function handleEncryptedChatMetadataImpl(
  serviceInstance: ChatSynchronizationService,
  payload: {
    chat_id: string;
    encrypted_chat_key?: string;
    encrypted_title?: string;
    encrypted_icon?: string;
    encrypted_category?: string;
    versions?: { messages_v?: number; title_v?: number; draft_v?: number };
  },
): Promise<void> {
  console.info(
    "[ChatSyncService:ChatUpdates] Received encrypted_chat_metadata (broadcast from other device):",
    payload,
  );

  if (!payload || !payload.chat_id) {
    console.error(
      "[ChatSyncService:ChatUpdates] Invalid payload in handleEncryptedChatMetadataImpl: missing chat_id",
      payload,
    );
    return;
  }

  // CRITICAL FIX: Don't reuse a single transaction across multiple async operations
  // The async decryption work in getChat() causes IndexedDB transactions to auto-commit.
  // Instead, use separate transactions for each operation.
  try {
    // First, get the chat without passing a transaction (getChat will create its own)
    const chat = await chatDB.getChat(payload.chat_id);

    if (!chat) {
      console.warn(
        `[ChatSyncService:ChatUpdates] Chat ${payload.chat_id} not found for encrypted_chat_metadata update broadcast`,
      );
      return;
    }

    let changed = false;

    // Update encrypted_chat_key if provided
    if (
      payload.encrypted_chat_key !== undefined &&
      payload.encrypted_chat_key !== chat.encrypted_chat_key
    ) {
      console.info(
        `[ChatSyncService:ChatUpdates] Updating encrypted_chat_key for chat ${payload.chat_id} from broadcast`,
      );

      // CRITICAL: Clear the cached chat key since it's now encrypted with a different secret
      chatDB.clearChatKey(payload.chat_id);

      // Update the encrypted_chat_key in the database
      chat.encrypted_chat_key = payload.encrypted_chat_key;
      changed = true;
    }

    // Update other metadata fields from broadcast
    if (
      payload.encrypted_title !== undefined &&
      payload.encrypted_title !== chat.encrypted_title
    ) {
      chat.encrypted_title = payload.encrypted_title;
      changed = true;
    }
    if (
      payload.encrypted_icon !== undefined &&
      payload.encrypted_icon !== chat.encrypted_icon
    ) {
      chat.encrypted_icon = payload.encrypted_icon;
      changed = true;
    }
    if (
      payload.encrypted_category !== undefined &&
      payload.encrypted_category !== chat.encrypted_category
    ) {
      chat.encrypted_category = payload.encrypted_category;
      changed = true;
    }

    // Update version info if provided
    if (payload.versions) {
      if (
        payload.versions.messages_v !== undefined &&
        payload.versions.messages_v > (chat.messages_v || 0)
      ) {
        chat.messages_v = payload.versions.messages_v;
        changed = true;
      }
      if (
        payload.versions.title_v !== undefined &&
        payload.versions.title_v > (chat.title_v || 0)
      ) {
        chat.title_v = payload.versions.title_v;
        changed = true;
      }
      if (
        payload.versions.draft_v !== undefined &&
        payload.versions.draft_v > (chat.draft_v || 0)
      ) {
        chat.draft_v = payload.versions.draft_v;
        changed = true;
      }
    }

    if (changed) {
      chat.updated_at = Math.floor(Date.now() / 1000);
      // Use a separate transaction for updateChat (it will create its own internally)
      await chatDB.updateChat(chat);
      console.info(
        `[ChatSyncService:ChatUpdates] Successfully updated metadata for chat ${payload.chat_id} from broadcast`,
      );

      // DB operation completed successfully - dispatch events
      // Mark chat list cache as dirty to force refresh
      chatListCache.markDirty();

      // Dispatch event to notify UI components (e.g., Chats.svelte) to refresh
      if (typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent("chatHidden", {
            detail: { chat_id: payload.chat_id },
          }),
        );
        window.dispatchEvent(
          new CustomEvent("chatUpdated", {
            detail: { chat_id: payload.chat_id, chat: chat },
          }),
        );
      }

      console.info(
        `[ChatSyncService:ChatUpdates] Chat list cache marked dirty and update events dispatched for ${payload.chat_id}`,
      );
    } else {
      console.debug(
        `[ChatSyncService:ChatUpdates] No changes needed for chat ${payload.chat_id} from broadcast`,
      );
    }
  } catch (error) {
    console.error(
      `[ChatSyncService:ChatUpdates] Error handling encrypted_chat_metadata for chat ${payload.chat_id}:`,
      error,
    );
  }
}
