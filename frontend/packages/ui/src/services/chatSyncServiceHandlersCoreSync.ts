// frontend/packages/ui/src/services/chatSyncServiceHandlersCoreSync.ts
import type { ChatSynchronizationService } from "./chatSyncService";
import { chatDB } from "./db";
import { chatKeyManager } from "./encryption/ChatKeyManager";
import { decryptWithChatKey } from "./encryption/MessageEncryptor";

import { userDB } from "./userDB";
import { chatListCache } from "./chatListCache";
import { notificationStore } from "../stores/notificationStore";
import { activeChatStore } from "../stores/activeChatStore";
import { phasedSyncState } from "../stores/phasedSyncStateStore";
import type {
  InitialSyncResponsePayload,
  Phase1LastChatPayload,
  Phase1bChatContentPayload,
  CachePrimedPayload,
  CacheStatusResponsePayload,
  ChatContentBatchResponsePayload,
  OfflineSyncCompletePayload,
  Chat,
  Message,
  MessageStatus,
} from "../types/chat";
import type { EmbedType } from "../message_parsing/types";

/**
 * Yield control back to the browser's main thread.
 * This prevents long-running sync operations from blocking UI rendering,
 * which is especially important on mobile devices with limited resources.
 */
function yieldToMainThread(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

export async function handleInitialSyncResponseImpl(
  serviceInstance: ChatSynchronizationService,
  payload: InitialSyncResponsePayload,
): Promise<void> {
  console.info(
    `[ChatSyncService:CoreSync] Received initial_sync_response: ${payload.chats_to_add_or_update?.length || 0} chats to update, ${payload.chat_ids_to_delete?.length || 0} to delete`,
  );
  let transaction: IDBTransaction | null = null;

  try {
    // CRITICAL: Do all async processing FIRST, THEN create transaction
    // If transaction is created before async work, it will auto-commit

    // Get current user's ID for ownership tracking
    // All synced chats belong to the current user (server filters by hashed_user_id)
    const userProfile = await userDB.getUserProfile();
    const currentUserId = userProfile?.user_id;

    // CRITICAL: Filter out chats that are pending server deletion.
    // These were deleted locally while offline and should not be re-added.
    const { getPendingChatDeletionsSet } =
      await import("./pendingChatDeletions");
    const pendingDeletions = getPendingChatDeletionsSet();
    const chatsToProcess =
      pendingDeletions.size > 0
        ? payload.chats_to_add_or_update.filter(
            (c) => !pendingDeletions.has(c.chat_id),
          )
        : payload.chats_to_add_or_update;

    // Process chats with async decryption — aggregate errors instead of per-chat logging
    let keyDecryptOk = 0;
    let keyDecryptFail = 0;
    let titleDecryptFail = 0;
    let missingKey = 0;

    const chatsToUpdate: Chat[] = await Promise.all(
      chatsToProcess.map(async (serverChat) => {
        // Decrypt encrypted title from server for in-memory use using chat-specific key
        let cleartextTitle: string | null = null;
        if (serverChat.encrypted_title && serverChat.encrypted_chat_key) {
          // Decrypt the chat key from server — receiveKeyFromServer() bypasses
          // the immutability guard so the server key always wins over stale
          // bulk_init keys (fixes iPad Safari IDB-deletion-blocked scenario).
          const chatKey = await chatKeyManager.receiveKeyFromServer(
            serverChat.chat_id,
            serverChat.encrypted_chat_key,
          );

          if (chatKey) {
            keyDecryptOk++;
            cleartextTitle = await decryptWithChatKey(
              serverChat.encrypted_title,
              chatKey,
            );
            if (!cleartextTitle) {
              titleDecryptFail++;
              cleartextTitle = serverChat.encrypted_title;
            }
          } else {
            keyDecryptFail++;
            cleartextTitle = serverChat.encrypted_title;
          }
        } else if (serverChat.encrypted_title) {
          missingKey++;
          cleartextTitle = serverChat.encrypted_title;
        }

        const chat: Chat = {
          chat_id: serverChat.chat_id,
          encrypted_title: serverChat.encrypted_title,
          messages_v: serverChat.versions.messages_v,
          title_v: serverChat.versions.title_v,
          draft_v: serverChat.versions.draft_v,
          encrypted_draft_md: serverChat.encrypted_draft_md,
          encrypted_draft_preview: serverChat.encrypted_draft_preview,
          encrypted_chat_key: serverChat.encrypted_chat_key, // Add encrypted chat key for decryption
          encrypted_icon: serverChat.encrypted_icon, // Add encrypted icon for decryption
          encrypted_category: serverChat.encrypted_category, // Add encrypted category for decryption
          last_edited_overall_timestamp:
            serverChat.last_edited_overall_timestamp,
          unread_count: serverChat.unread_count,
          created_at: serverChat.created_at,
          updated_at: serverChat.updated_at,
          // Set user_id from current user (all synced chats belong to them - server filters by hashed_user_id)
          user_id: currentUserId,
          // Include sharing fields from server sync for cross-device consistency
          is_shared:
            serverChat.is_shared !== undefined
              ? serverChat.is_shared
              : undefined,
          is_private:
            serverChat.is_private !== undefined
              ? serverChat.is_private
              : undefined,
        };
        return chat;
      }),
    );

    // Aggregate summary instead of per-chat logging (50 chats = 5 lines → 1 line)
    if (keyDecryptFail > 0 || missingKey > 0) {
      console.warn(
        `[ChatSyncService:CoreSync] Chat key decrypt: ${keyDecryptOk} ok, ${keyDecryptFail} key-failed, ${titleDecryptFail} title-failed, ${missingKey} missing-key`,
      );
    } else {
      console.info(
        `[ChatSyncService:CoreSync] Decrypted ${keyDecryptOk} chat keys successfully`,
      );
    }

    const messagesToSave: Message[] = payload.chats_to_add_or_update.flatMap(
      (chat) =>
        (chat.messages || []).map((msg) => {
          // Handle missing message_id - check if msg has 'id' property (legacy format)
          const messageId =
            (msg as Message & { id?: string }).id || msg.message_id;
          return {
            ...msg,
            message_id: messageId,
          };
        }),
    );

    // NOW create the transaction after all async preparation work
    // CRITICAL: Clean up embeds for chats being deleted BEFORE starting the transaction
    if (payload.chat_ids_to_delete && payload.chat_ids_to_delete.length > 0) {
      try {
        const { embedStore } = await import("./embedStore");
        for (const chatId of payload.chat_ids_to_delete) {
          await embedStore.deleteEmbedsForChat(chatId);
        }
      } catch (error) {
        console.error(
          "[ChatSyncService:CoreSync] Error cleaning up embeds during sync delete:",
          error,
        );
      }
    }

    transaction = await chatDB.getTransaction(
      [chatDB["CHATS_STORE_NAME"], chatDB["MESSAGES_STORE_NAME"]],
      "readwrite",
    );

    // Set the oncomplete handler IMMEDIATELY after creating transaction
    transaction.oncomplete = () => {
      console.info(
        "[ChatSyncService:CoreSync] Delta sync DB transaction complete.",
      );
      // Use the service's dispatchEvent method correctly
      serviceInstance.dispatchEvent(
        new CustomEvent("syncComplete", {
          detail: { serverChatOrder: payload.server_chat_order },
        }),
      );
      serviceInstance.isSyncing_FOR_HANDLERS_ONLY = false;
    };

    transaction.onerror = (event) => {
      console.error(
        "[ChatSyncService:CoreSync] Error in delta_sync_data transaction:",
        (event.target as IDBRequest).error,
      );
      const errorMessage =
        (event.target as IDBRequest).error?.message ||
        "Unknown database transaction error";
      notificationStore.error(
        `Error processing server sync data: ${errorMessage}`,
      );
      serviceInstance.isSyncing_FOR_HANDLERS_ONLY = false;
    };

    // This function now returns a promise that resolves when all operations are queued.
    // The transaction will auto-commit after this.
    await chatDB.batchProcessChatData(
      chatsToUpdate,
      messagesToSave,
      payload.chat_ids_to_delete || [],
      [],
      transaction,
    );

    // Correctly save the server_timestamp from the payload
    if (payload.server_timestamp) {
      // This should ideally be part of the same transaction if possible,
      // but userDB seems to be a separate class. For now, this is acceptable.
      await userDB.updateUserData({
        last_sync_timestamp: payload.server_timestamp,
      });
    }
  } catch (error) {
    console.error(
      "[ChatSyncService:CoreSync] Error setting up delta_sync_data processing:",
      error,
    );
    if (transaction && transaction.abort && !transaction.error) {
      try {
        transaction.abort();
      } catch (abortError) {
        console.error("Error aborting transaction:", abortError);
      }
    }
    const errorMessage = error instanceof Error ? error.message : String(error);
    notificationStore.error(
      `Error processing server sync data: ${errorMessage}`,
    );
    serviceInstance.isSyncing_FOR_HANDLERS_ONLY = false;
  }
}

export function handleInitialSyncErrorImpl(
  serviceInstance: ChatSynchronizationService,
  payload: { message: string },
): void {
  console.error(
    "[ChatSyncService:CoreSync] Received initial_sync_error:",
    payload.message,
  );
  notificationStore.error(`Chat sync failed: ${payload.message}`);
  serviceInstance.isSyncing_FOR_HANDLERS_ONLY = false;
  serviceInstance.initialSyncAttempted_FOR_HANDLERS_ONLY = false; // Allow retry
}

export async function handlePhase1LastChatImpl(
  serviceInstance: ChatSynchronizationService,
  payload: Phase1LastChatPayload,
): Promise<void> {
  console.info(
    "[ChatSyncService:CoreSync] Phase 1a received for:",
    payload.chat_id,
    "recent_metadata:",
    payload.recent_chat_metadata?.length || 0,
  );

  try {
    const { phasedSyncState } = await import("../stores/phasedSyncStateStore");

    // --- Build Chat objects for all Phase 1a chats and save metadata to IDB ---
    const userProfile = await userDB.getUserProfile();
    const currentUserId = userProfile?.user_id;
    await chatDB.init();

    // Helper to build Chat from server metadata
    const buildChat = (
      details: Partial<Chat> & { id: string },
    ): Chat => ({
      ...details,
      chat_id: details.id,
      encrypted_title: details.encrypted_title ?? null,
      messages_v: details.messages_v ?? 0,
      title_v: details.title_v ?? 0,
      draft_v: details.draft_v ?? 0,
      encrypted_draft_md: details.encrypted_draft_md ?? null,
      encrypted_draft_preview: details.encrypted_draft_preview ?? null,
      last_edited_overall_timestamp:
        details.last_edited_overall_timestamp ??
        details.updated_at ??
        Math.floor(Date.now() / 1000),
      unread_count: details.unread_count ?? 0,
      created_at: details.created_at ?? Math.floor(Date.now() / 1000),
      updated_at: details.updated_at ?? Math.floor(Date.now() / 1000),
      user_id: currentUserId,
      encrypted_chat_key: details.encrypted_chat_key ?? null,
      encrypted_icon: details.encrypted_icon ?? null,
      encrypted_category: details.encrypted_category ?? null,
      encrypted_active_focus_id: details.encrypted_active_focus_id ?? null,
      is_shared: details.is_shared,
      is_private: details.is_private,
    }) as Chat;

    // Collect all chats to decrypt: last-opened + recent metadata
    const allPhase1Chats: Chat[] = [];

    if (payload.chat_details && payload.chat_id) {
      const lastChat = buildChat({
        ...payload.chat_details,
        id: payload.chat_id,
      } as Partial<Chat> & { id: string });
      allPhase1Chats.push(lastChat);
      await chatDB.addChat(lastChat);
      chatListCache.upsertChat(lastChat);
    }

    if (payload.recent_chat_metadata) {
      for (const meta of payload.recent_chat_metadata) {
        const chat = buildChat(meta);
        allPhase1Chats.push(chat);
        await chatDB.addChat(chat);
        chatListCache.upsertChat(chat);
      }
    }

    // --- Decrypt title/icon/category for all 11 chats (44 decrypts max) ---
    const recentChatsDecrypted: Array<{
      chat: Chat;
      title: string;
      category: string | null;
      icon: string | null;
    }> = [];

    for (const chat of allPhase1Chats) {
      let title = "Untitled Chat";
      let category: string | null = null;
      let icon: string | null = null;

      try {
        let chatKey = await chatKeyManager.getKey(chat.chat_id);
        if (!chatKey && chat.encrypted_chat_key) {
          chatKey = await chatKeyManager.receiveKeyFromServer(
            chat.chat_id,
            chat.encrypted_chat_key,
          );
        }
        if (chatKey) {
          if (chat.encrypted_title) {
            try {
              title =
                (await decryptWithChatKey(chat.encrypted_title, chatKey)) ||
                title;
            } catch {
              /* fallback to default */
            }
          }
          if (chat.encrypted_category) {
            try {
              category = await decryptWithChatKey(
                chat.encrypted_category,
                chatKey,
              );
            } catch {
              /* fallback */
            }
          }
          if (chat.encrypted_icon) {
            try {
              icon = await decryptWithChatKey(chat.encrypted_icon, chatKey);
            } catch {
              /* fallback */
            }
          }
        }
      } catch {
        /* continue with defaults */
      }

      recentChatsDecrypted.push({ chat, title, category, icon });
    }

    // Store in phasedSyncStateStore for immediate rendering
    phasedSyncState.setRecentChats(recentChatsDecrypted);

    // Populate resume card for the last-opened chat (first in the list)
    if (recentChatsDecrypted.length > 0 && payload.chat_id && payload.chat_details) {
      const lastChat = recentChatsDecrypted[0];
      phasedSyncState.setResumeChatData(
        lastChat.chat,
        lastChat.title,
        lastChat.category,
        lastChat.icon,
        true, // force — bypass currentActiveChatId guard
      );
    }

    console.info(
      `[ChatSyncService:CoreSync] ✅ Phase 1a: decrypted ${recentChatsDecrypted.length} chats`,
    );

    // --- Save suggestions to IDB (unchanged from before) ---
    if (
      payload.new_chat_suggestions &&
      payload.new_chat_suggestions.length > 0
    ) {
      try {
        const chatIdForSuggestions = payload.chat_id || "global";
        await chatDB.saveEncryptedNewChatSuggestions(
          payload.new_chat_suggestions,
          chatIdForSuggestions,
        );
        serviceInstance.dispatchEvent(
          new CustomEvent("newChatSuggestionsReady", {
            detail: { suggestions: payload.new_chat_suggestions },
          }),
        );
      } catch (suggestionError) {
        console.error(
          "[ChatSyncService:CoreSync] Error saving suggestions:",
          suggestionError,
        );
      }
    }

    // --- Handle daily inspirations (unchanged from before) ---
    try {
      const { dailyInspirationStore } =
        await import("../stores/dailyInspirationStore");

      if (payload.daily_inspirations && payload.daily_inspirations.length > 0) {
        try {
          const { processInspirationRecordsFromSync } =
            await import("./dailyInspirationDB");
          const savedInspirations = await processInspirationRecordsFromSync(
            payload.daily_inspirations,
          );
          if (savedInspirations && savedInspirations.length > 0) {
            dailyInspirationStore.setInspirations(savedInspirations, {
              personalized: true,
            });
          } else {
            dailyInspirationStore.markPhase1Empty();
          }
        } catch (inspirationError) {
          console.error(
            "[ChatSyncService:CoreSync] Error processing inspirations:",
            inspirationError,
          );
        }
      } else {
        dailyInspirationStore.markPhase1Empty();
      }
    } catch (storeImportErr) {
      console.error(
        "[ChatSyncService:CoreSync] Failed to import dailyInspirationStore:",
        storeImportErr,
      );
    }

    // Brief delay to ensure IDB transactions are committed
    await new Promise((resolve) => setTimeout(resolve, 100));
  } catch (error) {
    console.error(
      "[ChatSyncService:CoreSync] Error in Phase 1a handler:",
      error,
    );
  }

  // Dispatch event so Chats.svelte can update
  serviceInstance.dispatchEvent(
    new CustomEvent("phase_1_last_chat_ready", { detail: payload }),
  );
}

/**
 * Phase 1b: Store messages + embeds for the 11 Phase 1a chats.
 * Messages are stored encrypted in IDB — NO decryption during sync.
 * This is a separate WS message so Phase 1a can render immediately.
 */
export async function handlePhase1bChatContentImpl(
  serviceInstance: ChatSynchronizationService,
  payload: Phase1bChatContentPayload,
): Promise<void> {
  console.info(
    `[ChatSyncService:CoreSync] Phase 1b received: ${payload.chats?.length || 0} chats, ` +
      `${payload.embeds?.length || 0} embeds, ${payload.embed_keys?.length || 0} embed_keys`,
  );

  try {
    // Store messages for each chat (encrypted, no decryption)
    for (const chatData of payload.chats || []) {
      if (!chatData.messages || chatData.messages.length === 0) continue;

      const preparedMessages: Message[] = [];
      for (const msgData of chatData.messages) {
        let msg = msgData;
        if (typeof msgData === "string") {
          try {
            msg = JSON.parse(msgData);
          } catch {
            continue;
          }
        }
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const msgObj = msg as any;
        if (!msgObj.message_id && msgObj.id) {
          msgObj.message_id = msgObj.id;
        }
        if (!msgObj.message_id) continue;
        if (!msgObj.chat_id) msgObj.chat_id = chatData.chat_id;
        if (!msgObj.status) msgObj.status = "delivered";
        preparedMessages.push(msgObj as Message);
      }

      if (preparedMessages.length > 0) {
        await chatDB.batchSaveMessages(preparedMessages);
      }

      // Update messages_v on the chat object
      if (chatData.server_message_count > 0) {
        const existingChat = await chatDB.getChat(chatData.chat_id);
        if (existingChat) {
          const updatedV = Math.max(
            existingChat.messages_v || 0,
            chatData.server_message_count,
          );
          if (updatedV > (existingChat.messages_v || 0)) {
            await chatDB.addChat({ ...existingChat, messages_v: updatedV });
          }
        }
      }
    }

    // Store embed_keys FIRST (needed for embed decryption)
    if (payload.embed_keys && payload.embed_keys.length > 0) {
      try {
        const { embedStore } = await import("./embedStore");
        await embedStore.storeEmbedKeys(payload.embed_keys);
      } catch (e) {
        console.error("[ChatSyncService:CoreSync] Phase 1b embed_keys error:", e);
      }
    }

    // Store embeds — use batch write (single IDB transaction) instead of
    // individual putEncrypted() calls. Matches the Phase 3 optimisation that
    // reduced 1300-embed sync on iPhone Safari from ~15s to ~1s.
    if (payload.embeds && payload.embeds.length > 0) {
      try {
        const { embedStore } = await import("./embedStore");
        const validEmbeds = payload.embeds.filter(
          (embed) =>
            embed.embed_id &&
            embed.status !== "error" &&
            embed.status !== "cancelled",
        );

        if (validEmbeds.length > 0) {
          await embedStore.putEncryptedBatch(
            validEmbeds.map((embed) => ({
              contentRef: `embed:${embed.embed_id}`,
              data: {
                encrypted_content: embed.encrypted_content,
                encrypted_type: embed.encrypted_type,
                embed_id: embed.embed_id,
                status: embed.status || "finished",
                hashed_chat_id: embed.hashed_chat_id,
                hashed_user_id: embed.hashed_user_id,
                embed_ids: embed.embed_ids,
                parent_embed_id: embed.parent_embed_id,
                version_number: embed.version_number,
                encrypted_diff: embed.encrypted_diff,
                file_path: embed.file_path,
                content_hash: embed.content_hash,
                text_length_chars: embed.text_length_chars,
                is_private: embed.is_private ?? false,
                is_shared: embed.is_shared ?? false,
                createdAt: embed.createdAt || embed.created_at,
                updatedAt: embed.updatedAt || embed.updated_at,
              },
              type: (embed.encrypted_type
                ? "app-skill-use"
                : embed.embed_type || "app-skill-use") as EmbedType,
            })),
          );
        }
      } catch (e) {
        console.error("[ChatSyncService:CoreSync] Phase 1b embeds error:", e);
      }
    }

    console.info("[ChatSyncService:CoreSync] ✅ Phase 1b complete");
  } catch (error) {
    console.error("[ChatSyncService:CoreSync] Phase 1b error:", error);
  }

  serviceInstance.dispatchEvent(
    new CustomEvent("phase_1b_chat_content_ready", { detail: payload }),
  );
}

export function handleCachePrimedImpl(
  serviceInstance: ChatSynchronizationService,
  payload: CachePrimedPayload,
): void {
  console.info(
    "[ChatSyncService:CoreSync] Received cache_primed:",
    payload.status,
  );
  if (payload.status === "full_sync_ready") {
    serviceInstance.cachePrimed_FOR_HANDLERS_ONLY = true;

    // Mark sync completed in the service layer when cache is primed and sync
    // was already attempted — this means the server considers data ready.
    // This guarantees the "Syncing..." indicator clears even if Chats.svelte
    // is unmounted. The markSyncCompleted call is idempotent.
    if (serviceInstance.initialSyncAttempted_FOR_HANDLERS_ONLY) {
      phasedSyncState.markSyncCompleted();
    }

    serviceInstance.dispatchEvent(new CustomEvent("cachePrimed"));
    if (
      !serviceInstance.isSyncing_FOR_HANDLERS_ONLY &&
      !serviceInstance.initialSyncAttempted_FOR_HANDLERS_ONLY
    ) {
      serviceInstance.attemptInitialSync_FOR_HANDLERS_ONLY();
    }
  }
}

export function handleCacheStatusResponseImpl(
  serviceInstance: ChatSynchronizationService,
  payload: CacheStatusResponsePayload,
): void {
  console.info(
    `[ChatSyncService:CoreSync] Received cache_status_response: primed=${payload.is_primed}, chats=${payload.chat_count}`,
  );

  // Validate required fields - no silent failures!
  if (typeof payload.is_primed !== "boolean") {
    console.error(
      "[ChatSyncService:CoreSync] CRITICAL: Missing or invalid 'is_primed' in cache_status_response:",
      payload,
    );
    throw new Error("Invalid cache_status_response: missing 'is_primed'");
  }

  if (typeof payload.chat_count !== "number") {
    console.error(
      "[ChatSyncService:CoreSync] CRITICAL: Missing or invalid 'chat_count' in cache_status_response:",
      payload,
    );
    throw new Error("Invalid cache_status_response: missing 'chat_count'");
  }

  if (typeof payload.timestamp !== "number") {
    console.error(
      "[ChatSyncService:CoreSync] CRITICAL: Missing or invalid 'timestamp' in cache_status_response:",
      payload,
    );
    throw new Error("Invalid cache_status_response: missing 'timestamp'");
  }

  // Dispatch event to Chats component with validated payload
  serviceInstance.dispatchEvent(
    new CustomEvent("syncStatusResponse", {
      detail: {
        cache_primed: payload.is_primed,
        chat_count: payload.chat_count,
        timestamp: payload.timestamp,
      },
    }),
  );

  console.log("[ChatSyncService:CoreSync] Cache status check:", {
    is_primed: payload.is_primed,
    chat_count: payload.chat_count,
    cachePrimed_before: serviceInstance.cachePrimed_FOR_HANDLERS_ONLY,
    initialSyncAttempted:
      serviceInstance.initialSyncAttempted_FOR_HANDLERS_ONLY,
  });

  if (payload.is_primed && !serviceInstance.cachePrimed_FOR_HANDLERS_ONLY) {
    console.log(
      "[ChatSyncService:CoreSync] ✅ Cache is primed! Setting flag and attempting initial sync...",
    );
    serviceInstance.cachePrimed_FOR_HANDLERS_ONLY = true;
    console.log(
      "[ChatSyncService:CoreSync] Calling attemptInitialSync_FOR_HANDLERS_ONLY()...",
    );
    serviceInstance.attemptInitialSync_FOR_HANDLERS_ONLY();
    console.log(
      "[ChatSyncService:CoreSync] attemptInitialSync_FOR_HANDLERS_ONLY() call completed",
    );
  } else if (
    payload.is_primed &&
    serviceInstance.cachePrimed_FOR_HANDLERS_ONLY
  ) {
    console.warn(
      "[ChatSyncService:CoreSync] Cache primed but flag already set - sync may have already been attempted",
    );
  } else {
    // Cache is not primed — the backend has auto-dispatched a cache warming task.
    // Schedule a retry to poll for completion. The cache_primed push event should also
    // arrive when warming completes, but polling provides a reliable fallback in case
    // the push event is missed (e.g., brief WebSocket reconnection window).
    console.warn(
      "[ChatSyncService:CoreSync] Cache not primed yet. Backend is re-warming. Scheduling status retry...",
    );
    serviceInstance.scheduleCacheStatusRetry_FOR_HANDLERS_ONLY();
  }
}

export async function handleChatContentBatchResponseImpl(
  serviceInstance: ChatSynchronizationService,
  payload: ChatContentBatchResponsePayload,
): Promise<void> {
  console.info(
    "[ChatSyncService:CoreSync] Received 'chat_content_batch_response':",
    payload,
  );
  if (
    !payload.messages_by_chat_id ||
    Object.keys(payload.messages_by_chat_id).length === 0
  ) {
    console.info(
      "[ChatSyncService:CoreSync] No messages in batch response, skipping.",
    );
    return;
  }

  const chatIdsWithMessages = Object.keys(payload.messages_by_chat_id);
  let updatedChatCount = 0;

  // PERFORMANCE FIX: Prioritize the active chat so its messages render first,
  // then process remaining chats with yields to the UI thread between each.
  // This prevents the "glitching" effect on mobile devices where processing
  // many chats' IndexedDB writes simultaneously blocks the main thread.
  const currentActiveChatId = activeChatStore.get();
  const sortedChatIds = [...chatIdsWithMessages].sort((a, b) => {
    if (a === currentActiveChatId) return -1;
    if (b === currentActiveChatId) return 1;
    return 0;
  });

  for (let i = 0; i < sortedChatIds.length; i++) {
    const chatId = sortedChatIds[i];

    // Yield to the main thread between non-active chat saves to prevent UI jank.
    // Skip yielding for the first chat (active chat) to render it ASAP.
    if (i > 0) {
      await yieldToMainThread();
    }
    const rawMessages = payload.messages_by_chat_id[chatId];
    if (!rawMessages || rawMessages.length === 0) {
      console.debug(
        `[ChatSyncService:CoreSync] Batch response: No messages for chat ${chatId}`,
      );
      continue;
    }

    try {
      // Parse messages — server sends JSON-serialized strings from sync cache/Directus
      // Same pattern as prepareMessagesForStorage in phased sync
      const preparedMessages: Message[] = [];
      for (const messageData of rawMessages) {
        let message: Record<string, unknown>;

        // Parse JSON string if needed (server sends JSON strings from sync cache)
        if (typeof messageData === "string") {
          try {
            message = JSON.parse(messageData);
          } catch (e) {
            console.error(
              `[ChatSyncService:CoreSync] Failed to parse message JSON for chat ${chatId}:`,
              e,
            );
            continue;
          }
        } else {
          message = messageData as unknown as Record<string, unknown>;
        }

        // Normalize message_id: use 'id' field as fallback (Directus UUID)
        const messageId = (message.message_id ||
          message.client_message_id ||
          message.id) as string | undefined;
        if (!messageId) {
          console.error(
            `[ChatSyncService:CoreSync] Message missing message_id after parsing, skipping:`,
            message,
          );
          continue;
        }

        const messageToSave: Message = {
          message_id: messageId,
          chat_id: (message.chat_id as string) || chatId,
          role: (message.role as Message["role"]) || "user",
          created_at: message.created_at as number,
          status:
            (message.status as MessageStatus) || ("delivered" as MessageStatus),
          client_message_id: message.client_message_id as string | undefined,
          user_message_id: message.user_message_id as string | undefined,
          // Encrypted fields (zero-knowledge architecture)
          encrypted_content: message.encrypted_content as string,
          encrypted_sender_name: message.encrypted_sender_name as
            | string
            | undefined,
          encrypted_category: message.encrypted_category as string | undefined,
          encrypted_model_name: message.encrypted_model_name as
            | string
            | undefined,
          encrypted_thinking_content: message.encrypted_thinking_content as
            | string
            | undefined,
          encrypted_thinking_signature: message.encrypted_thinking_signature as
            | string
            | undefined,
          has_thinking: message.has_thinking as boolean | undefined,
          thinking_token_count: message.thinking_token_count as
            | number
            | undefined,
          // PII mappings for client-side restoration of anonymized data
          encrypted_pii_mappings: message.encrypted_pii_mappings as
            | string
            | undefined,
        };
        preparedMessages.push(messageToSave);
      }

      if (preparedMessages.length === 0) {
        console.debug(
          `[ChatSyncService:CoreSync] Batch response: No valid messages after parsing for chat ${chatId}`,
        );
        continue;
      }

      // Save messages to IndexedDB
      await chatDB.batchSaveMessages(preparedMessages);

      // Update chat record: set messages_v from server response and update timestamp
      const chat = await chatDB.getChat(chatId);
      if (chat) {
        chat.updated_at = Math.floor(Date.now() / 1000);

        // CRITICAL: Update messages_v from the server's version info so the client
        // doesn't keep re-requesting messages on the next sync cycle.
        // Without this, messages_v would stay at 0 (from the inconsistency reset)
        // and trigger another full re-sync.
        const versionInfo = payload.versions_by_chat_id?.[chatId];
        if (versionInfo && versionInfo.messages_v !== undefined) {
          console.info(
            `[ChatSyncService:CoreSync] Batch response: Updating messages_v for chat ${chatId}: ` +
              `${chat.messages_v} → ${versionInfo.messages_v} (server_message_count: ${versionInfo.server_message_count})`,
          );
          chat.messages_v = versionInfo.messages_v;
        }

        await chatDB.updateChat(chat);
        updatedChatCount++;
        serviceInstance.dispatchEvent(
          new CustomEvent("chatUpdated", {
            detail: { chat_id: chatId, messagesUpdated: true },
          }),
        );
      }

      console.info(
        `[ChatSyncService:CoreSync] Batch response: Saved ${preparedMessages.length} messages for chat ${chatId}`,
      );
    } catch (error) {
      console.error(
        `[ChatSyncService:CoreSync] Error processing batch messages for chat ${chatId}:`,
        error,
      );
    }
  }

  if (updatedChatCount > 0) {
    console.info(
      `[ChatSyncService:CoreSync] Batch response: Updated ${updatedChatCount} chats with re-synced messages`,
    );
  }

  // Store embeds + embed_keys from on-demand batch response (new: added for chats 101-1000)
  if (payload.embed_keys && payload.embed_keys.length > 0) {
    try {
      const { embedStore } = await import("./embedStore");
      await embedStore.storeEmbedKeys(payload.embed_keys);
    } catch (e) {
      console.error("[ChatSyncService:CoreSync] Batch embed_keys error:", e);
    }
  }
  if (payload.embeds && payload.embeds.length > 0) {
    try {
      const { embedStore } = await import("./embedStore");
      for (const embed of payload.embeds) {
        if (!embed.embed_id || embed.status === "error" || embed.status === "cancelled") continue;
        const contentRef = `embed:${embed.embed_id}`;
        await embedStore.putEncrypted(
          contentRef,
          {
            encrypted_content: embed.encrypted_content,
            encrypted_type: embed.encrypted_type,
            embed_id: embed.embed_id,
            status: embed.status || "finished",
            hashed_chat_id: embed.hashed_chat_id,
            hashed_user_id: embed.hashed_user_id,
            embed_ids: embed.embed_ids,
            parent_embed_id: embed.parent_embed_id,
            version_number: embed.version_number,
            encrypted_diff: embed.encrypted_diff,
            file_path: embed.file_path,
            content_hash: embed.content_hash,
            text_length_chars: embed.text_length_chars,
            is_private: embed.is_private ?? false,
            is_shared: embed.is_shared ?? false,
            createdAt: embed.createdAt || embed.created_at,
            updatedAt: embed.updatedAt || embed.updated_at,
          },
          (embed.encrypted_type ? "app-skill-use" : embed.embed_type || "app-skill-use") as EmbedType,
          undefined,
          undefined,
          { skipMetadataExtraction: true },
        );
      }
    } catch (e) {
      console.error("[ChatSyncService:CoreSync] Batch embeds error:", e);
    }
  }
}

export async function handleOfflineSyncCompleteImpl(
  serviceInstance: ChatSynchronizationService,
  payload: OfflineSyncCompletePayload,
): Promise<void> {
  console.info(
    "[ChatSyncService:CoreSync] Received offline_sync_complete:",
    payload,
  );
  const changes = await chatDB.getOfflineChanges();
  let tx: IDBTransaction | null = null;
  try {
    tx = await chatDB.getTransaction(
      chatDB["OFFLINE_CHANGES_STORE_NAME"],
      "readwrite",
    );
    for (const change of changes) {
      await chatDB.deleteOfflineChange(change.change_id, tx);
    }
    tx.oncomplete = () => {
      if (payload.errors > 0)
        notificationStore.error(
          `Offline sync: ${payload.errors} changes could not be applied.`,
        );
      if (payload.conflicts > 0)
        notificationStore.warning(
          `Offline sync: ${payload.conflicts} changes had conflicts.`,
        );
      if (
        payload.errors === 0 &&
        payload.conflicts === 0 &&
        payload.processed > 0
      )
        notificationStore.success(
          `${payload.processed} offline changes synced.`,
        );
      serviceInstance.dispatchEvent(
        new CustomEvent("offlineSyncProcessed", { detail: payload }),
      );
    };
  } catch (error) {
    console.error(
      "[ChatSyncService:CoreSync] Error in handleOfflineSyncCompleteImpl:",
      error,
    );
    if (tx && tx.abort && !tx.error) {
      try {
        tx.abort();
      } catch (abortError) {
        console.error("Error aborting transaction:", abortError);
      }
    }
  }
}
