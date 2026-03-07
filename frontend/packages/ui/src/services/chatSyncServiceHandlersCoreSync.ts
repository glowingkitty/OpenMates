// frontend/packages/ui/src/services/chatSyncServiceHandlersCoreSync.ts
import type { ChatSynchronizationService } from "./chatSyncService";
import { chatDB } from "./db";
import { userDB } from "./userDB";
import { notificationStore } from "../stores/notificationStore";
import { activeChatStore } from "../stores/activeChatStore";
import type {
  InitialSyncResponsePayload,
  Phase1LastChatPayload,
  CachePrimedPayload,
  CacheStatusResponsePayload,
  ChatContentBatchResponsePayload,
  OfflineSyncCompletePayload,
  Chat,
  Message,
  MessageStatus,
  SyncEmbed,
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

/**
 * Decrypt chat title/category/icon and populate phasedSyncState.resumeChatData
 * so the resume card on the welcome screen is available immediately after Phase 1
 * completes — regardless of whether Chats.svelte (sidebar) is mounted.
 *
 * This is the critical fix for "resume card not showing after login":
 * Previously, only Chats.svelte's event listener called setResumeChatData(),
 * but on mobile or when the sidebar isn't open, that listener isn't active.
 *
 * @param chat - The Chat object (from IndexedDB or freshly constructed from payload)
 * @param chatId - The chat ID string
 */
async function populateResumeChatDataFromPhase1(
  chat: Chat,
  chatId: string,
): Promise<void> {
  try {
    const { phasedSyncState } = await import("../stores/phasedSyncStateStore");

    // Decrypt title, category, icon for the resume card display
    let displayTitle = "Untitled Chat";
    let displayCategory: string | null = null;
    let displayIcon: string | null = null;

    try {
      const { decryptWithChatKey, decryptChatKeyWithMasterKey } =
        await import("./cryptoService");
      let chatKey = chatDB.getChatKey(chatId);
      if (!chatKey && chat.encrypted_chat_key) {
        chatKey = await decryptChatKeyWithMasterKey(chat.encrypted_chat_key);
        if (chatKey) chatDB.setChatKey(chatId, chatKey);
      }
      if (chatKey) {
        if (chat.encrypted_title) {
          try {
            displayTitle =
              (await decryptWithChatKey(chat.encrypted_title, chatKey)) ||
              displayTitle;
          } catch {
            /* fall through to default */
          }
        }
        if (chat.encrypted_category) {
          try {
            displayCategory = await decryptWithChatKey(
              chat.encrypted_category,
              chatKey,
            );
          } catch {
            /* fall through */
          }
        }
        if (chat.encrypted_icon) {
          try {
            displayIcon = await decryptWithChatKey(
              chat.encrypted_icon,
              chatKey,
            );
          } catch {
            /* fall through */
          }
        }
      }
    } catch (decryptErr) {
      console.warn(
        "[ChatSyncService:CoreSync] Failed to decrypt fields for Phase 1 resume card:",
        decryptErr,
      );
    }

    // Use force=true because during login the currentActiveChatId might still
    // hold a stale value from the previous session. The user is on the welcome
    // screen at this point — Phase 1 runs before any chat is opened.
    phasedSyncState.setResumeChatData(
      chat,
      displayTitle,
      displayCategory,
      displayIcon,
      true, // force — bypass currentActiveChatId guard
    );

    console.info(
      `[ChatSyncService:CoreSync] ✅ Populated resume card from Phase 1 for chat "${chatId}": title="${displayTitle}"`,
    );
  } catch (err) {
    console.error(
      "[ChatSyncService:CoreSync] Failed to populate resume card from Phase 1:",
      err,
    );
  }
}

export async function handleInitialSyncResponseImpl(
  serviceInstance: ChatSynchronizationService,
  payload: InitialSyncResponsePayload,
): Promise<void> {
  console.info(
    "[ChatSyncService:CoreSync] Received initial_sync_response (delta_sync_data):",
    payload,
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

    // Process chats with async decryption
    const chatsToUpdate: Chat[] = await Promise.all(
      chatsToProcess.map(async (serverChat) => {
        // Decrypt encrypted title from server for in-memory use using chat-specific key
        let cleartextTitle: string | null = null;
        if (serverChat.encrypted_title && serverChat.encrypted_chat_key) {
          console.log(
            `[CLIENT_DECRYPT] ✅ Chat ${serverChat.chat_id} has encrypted_chat_key: ` +
              `${serverChat.encrypted_chat_key.substring(0, 20)}... (length: ${serverChat.encrypted_chat_key.length})`,
          );
          // First, decrypt the chat key from encrypted_chat_key using master key
          const { decryptChatKeyWithMasterKey } =
            await import("./cryptoService");
          const chatKey = await decryptChatKeyWithMasterKey(
            serverChat.encrypted_chat_key,
          );

          if (chatKey) {
            // Cache the decrypted chat key for future use
            chatDB.setChatKey(serverChat.chat_id, chatKey);
            console.log(
              `[CLIENT_DECRYPT] ✅ Decrypted and cached chat key for ${serverChat.chat_id} ` +
                `(key length: ${chatKey.length} bytes)`,
            );

            // Now decrypt the title with the chat key
            const { decryptWithChatKey } = await import("./cryptoService");
            cleartextTitle = await decryptWithChatKey(
              serverChat.encrypted_title,
              chatKey,
            );
            if (cleartextTitle) {
              console.log(
                `[CLIENT_DECRYPT] ✅ Successfully decrypted title for chat ${serverChat.chat_id}: "${cleartextTitle.substring(0, 50)}..."`,
              );
            } else {
              console.warn(
                `[CLIENT_DECRYPT] ❌ Failed to decrypt title for chat ${serverChat.chat_id}`,
              );
              cleartextTitle = serverChat.encrypted_title; // Fallback to encrypted content if decryption fails
            }
          } else {
            console.error(
              `[CLIENT_DECRYPT] ❌ CRITICAL: Failed to decrypt chat key for chat ${serverChat.chat_id} - ` +
                `chat will not be decryptable!`,
            );
            cleartextTitle = serverChat.encrypted_title; // Fallback to encrypted content if decryption fails
          }
        } else if (serverChat.encrypted_title) {
          console.error(
            `[CLIENT_DECRYPT] ❌ CRITICAL: Chat ${serverChat.chat_id} missing encrypted_chat_key - ` +
              `cannot decrypt title or messages!`,
          );
          cleartextTitle = serverChat.encrypted_title;
        } else {
          console.warn(
            `[CLIENT_DECRYPT] ⚠️ Chat ${serverChat.chat_id} has no encrypted_title or encrypted_chat_key`,
          );
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
    "[ChatSyncService:CoreSync] Received phase_1_last_chat_ready for:",
    payload.chat_id,
  );
  console.debug("[ChatSyncService:CoreSync] Phase 1 payload contains:", {
    chat_id: payload.chat_id,
    has_chat_details: !!payload.chat_details,
    messages_count: payload.messages?.length || 0,
    server_message_count: payload.server_message_count,
    embeds_count: payload.embeds?.length || 0,
    suggestions_count: payload.new_chat_suggestions?.length || 0,
    already_synced: payload.already_synced,
  });

  // Check if server indicated chat is already synced (version-aware optimization)
  if (payload.already_synced) {
    console.info(
      `[ChatSyncService:CoreSync] Phase 1: Chat ${payload.chat_id} already up-to-date on client. Skipping data save.`,
    );

    // CRITICAL FIX: Even when already synced, populate resume card data directly.
    // The chat is already in IndexedDB — load it and decrypt for the resume card.
    // Without this, the resume card only appears if Chats.svelte is mounted.
    if (payload.chat_id) {
      try {
        const existingChat = await chatDB.getChat(payload.chat_id);
        if (existingChat) {
          await populateResumeChatDataFromPhase1(existingChat, payload.chat_id);
        }
      } catch (resumeErr) {
        console.warn(
          "[ChatSyncService:CoreSync] Failed to populate resume card for already-synced chat:",
          resumeErr,
        );
      }
    }

    // Still dispatch event so Chats.svelte knows Phase 1 is complete
    serviceInstance.dispatchEvent(
      new CustomEvent("phase_1_last_chat_ready", { detail: payload }),
    );
    return;
  }

  // CRITICAL: According to sync.md, Phase 1 must save data to IndexedDB BEFORE opening chat
  // This ensures chat is available when Chats.svelte tries to load it
  try {
    // CRITICAL FIX: Validate message count when server skips sending messages
    // If server sends server_message_count but no messages (empty array), validate local data
    // This detects data inconsistency where version matches but messages are missing
    if (
      payload.chat_id &&
      payload.server_message_count !== undefined &&
      payload.server_message_count !== null
    ) {
      const messagesFromServer = payload.messages?.length || 0;

      // Server skipped sending messages (empty array) - validate local message count
      if (messagesFromServer === 0 && payload.server_message_count > 0) {
        const localMessages = await chatDB.getMessagesForChat(payload.chat_id);
        const localMessageCount = localMessages?.length || 0;

        console.info(
          `[ChatSyncService:CoreSync] Phase 1 - Message count validation for chat ${payload.chat_id}: ` +
            `server_count=${payload.server_message_count}, local_count=${localMessageCount}`,
        );

        // DATA INCONSISTENCY DETECTED: Local has fewer messages than server
        // This happens when messages_v matches but IndexedDB messages were lost/corrupted
        if (localMessageCount < payload.server_message_count) {
          console.warn(
            `[ChatSyncService:CoreSync] ⚠️ DATA INCONSISTENCY DETECTED for chat ${payload.chat_id}: ` +
              `Local has ${localMessageCount} messages but server has ${payload.server_message_count}. ` +
              `Resetting local messages_v to 0 to force re-sync on next load.`,
          );

          // Reset the local chat's messages_v to 0 to force a full re-sync
          // This will cause the next sync to fetch all messages from the server
          const existingChat = await chatDB.getChat(payload.chat_id);
          if (existingChat) {
            const resetChat = {
              ...existingChat,
              messages_v: 0, // Reset to force re-sync
            };
            await chatDB.addChat(resetChat);
            console.info(
              `[ChatSyncService:CoreSync] Reset messages_v to 0 for chat ${payload.chat_id}. ` +
                `Refresh the page to trigger a full message re-sync.`,
            );
          }

          // Dispatch event with a flag indicating re-sync is needed
          serviceInstance.dispatchEvent(
            new CustomEvent("phase_1_last_chat_ready", {
              detail: { ...payload, needsResync: true },
            }),
          );
          return;
        }
      }
    }

    // Save Phase 1 chat data to IndexedDB using a single transaction for atomicity
    if (payload.chat_details && payload.messages) {
      console.info(
        "[ChatSyncService:CoreSync] Saving Phase 1 chat data to IndexedDB:",
        payload.chat_id,
      );

      // Get current user's ID for ownership tracking
      // All synced chats belong to the current user (server filters by hashed_user_id)
      const userProfile = await userDB.getUserProfile();
      const currentUserId = userProfile?.user_id;

      // Build the Chat object from payload.
      // CRITICAL: Spread chat_details FIRST so explicit field assignments below win.
      // Previously the spread was last, which could overwrite explicit null-coalescing
      // defaults (e.g. messages_v ?? 0) with raw undefined values from chat_details,
      // and override user_id with whatever was (or wasn't) in the server payload.
      const chatWithId: Chat = {
        ...payload.chat_details,
        // Explicit fields below override the spread
        chat_id: payload.chat_id,
        encrypted_title: payload.chat_details.encrypted_title ?? null,
        messages_v: payload.chat_details.messages_v ?? 0,
        title_v: payload.chat_details.title_v ?? 0,
        draft_v: payload.chat_details.draft_v ?? 0,
        encrypted_draft_md: payload.chat_details.encrypted_draft_md ?? null,
        encrypted_draft_preview:
          payload.chat_details.encrypted_draft_preview ?? null,
        last_edited_overall_timestamp:
          payload.chat_details.last_edited_overall_timestamp ??
          payload.chat_details.updated_at ??
          Math.floor(Date.now() / 1000),
        unread_count: payload.chat_details.unread_count ?? 0,
        created_at:
          payload.chat_details.created_at ?? Math.floor(Date.now() / 1000),
        updated_at:
          payload.chat_details.updated_at ?? Math.floor(Date.now() / 1000),
        // Set user_id from current user (all synced chats belong to them - server filters by hashed_user_id)
        user_id: currentUserId,
        encrypted_chat_key: payload.chat_details.encrypted_chat_key ?? null,
        encrypted_icon: payload.chat_details.encrypted_icon ?? null,
        encrypted_category: payload.chat_details.encrypted_category ?? null,
        encrypted_active_focus_id:
          payload.chat_details.encrypted_active_focus_id ?? null,
        is_shared: payload.chat_details.is_shared,
        is_private: payload.chat_details.is_private,
      };

      // NOTE: We intentionally do NOT use a shared multi-store transaction here.
      // IDB transactions auto-commit when there are no pending requests AND the JS
      // event loop returns. addChat() and saveMessage() both do async crypto (key
      // derivation) BEFORE queuing their IDB writes, which causes the shared
      // transaction to auto-commit in the async gap — resulting in
      // InvalidStateError warnings on every login.
      // Each function already manages its own reliable internal transaction, so
      // calling them without a shared transaction is the correct pattern here.
      await chatDB.init();

      // Store chat metadata (uses its own internal transaction)
      await chatDB.addChat(chatWithId);

      // Store messages if provided (each uses its own internal transaction)
      if (payload.messages && payload.messages.length > 0) {
        console.info(
          "[ChatSyncService:CoreSync] Saving",
          payload.messages.length,
          "Phase 1 messages",
        );
        for (const messageData of payload.messages) {
          // Parse JSON string if needed
          let message = messageData;
          if (typeof messageData === "string") {
            try {
              message = JSON.parse(messageData);
            } catch (e) {
              console.error(
                "[ChatSyncService:CoreSync] Failed to parse Phase 1 message JSON:",
                e,
              );
              continue;
            }
          }

          // DEFENSIVE: Validate message has required fields before saving
          if (!message.message_id) {
            console.error(
              "[ChatSyncService:CoreSync] Message missing message_id, skipping:",
              message,
            );
            continue;
          }
          if (!message.chat_id) {
            // Use chat_id from payload if missing
            message.chat_id = payload.chat_id;
          }

          await chatDB.saveMessage(message);
        }
      }

      console.info(
        "[ChatSyncService:CoreSync] ✅ Phase 1 writes complete for chat:",
        payload.chat_id,
      );
    }

    // CRITICAL: Save new chat suggestions to IndexedDB (Phase 1 ALWAYS includes suggestions)
    if (
      payload.new_chat_suggestions &&
      payload.new_chat_suggestions.length > 0
    ) {
      console.info(
        "[ChatSyncService:CoreSync] Saving",
        payload.new_chat_suggestions.length,
        "new chat suggestions to IndexedDB",
      );
      try {
        // Pass full NewChatSuggestion objects with IDs from server
        // Use 'global' as chatId when no specific chat is associated (e.g., "new" section)
        const chatIdForSuggestions = payload.chat_id || "global";
        await chatDB.saveEncryptedNewChatSuggestions(
          payload.new_chat_suggestions,
          chatIdForSuggestions,
        );
        console.info(
          "[ChatSyncService:CoreSync] ✅ Successfully saved",
          payload.new_chat_suggestions.length,
          "suggestions to IndexedDB with IDs",
        );

        // Dispatch event so NewChatSuggestions component can update
        serviceInstance.dispatchEvent(
          new CustomEvent("newChatSuggestionsReady", {
            detail: { suggestions: payload.new_chat_suggestions },
          }),
        );
      } catch (suggestionError) {
        console.error(
          "[ChatSyncService:CoreSync] Error saving suggestions to IndexedDB:",
          suggestionError,
        );
      }
    } else {
      console.warn(
        "[ChatSyncService:CoreSync] ⚠️ No new chat suggestions received in Phase 1 - this is unexpected!",
      );
    }

    // Handle daily inspirations synced in Phase 1 (mirrors new_chat_suggestions pattern).
    // Raw encrypted Directus records are decrypted and saved to IndexedDB here so inspirations
    // are available immediately after login without waiting for the fallback fetch.
    // Import the store once upfront so both the success and empty branches can use it without
    // an extra async microtask gap before calling setInspirations / markPhase1Empty.
    try {
      const { dailyInspirationStore } =
        await import("../stores/dailyInspirationStore");

      if (payload.daily_inspirations && payload.daily_inspirations.length > 0) {
        console.info(
          "[ChatSyncService:CoreSync] Processing",
          payload.daily_inspirations.length,
          "daily inspirations from Phase 1 sync",
        );
        try {
          const { processInspirationRecordsFromSync } =
            await import("./dailyInspirationDB");
          const savedInspirations = await processInspirationRecordsFromSync(
            payload.daily_inspirations,
          );

          // Populate the store so UI updates immediately.
          // Always write personalized data from Phase 1 — it must override any
          // public defaults that loadDefaultInspirations() may have already loaded
          // (defaults load fast via unauthenticated REST; Phase 1 is slower because
          // it requires the WS auth handshake). The store's setInspirations guard
          // prevents defaults from overwriting personalized data, but the reverse
          // must never apply: personalized data (with is_opened / opened_chat_id)
          // must always win.
          if (savedInspirations && savedInspirations.length > 0) {
            dailyInspirationStore.setInspirations(savedInspirations, {
              personalized: true,
            });
            console.info(
              "[ChatSyncService:CoreSync] ✅ Daily inspiration store populated with",
              savedInspirations.length,
              "personalized inspiration(s) from Phase 1 sync",
            );
          } else {
            // Server sent N inspirations but decryption returned 0 — most likely the
            // master key was not yet available (first login race condition). Log this
            // clearly so it shows up in debug sessions. Also call markPhase1Empty()
            // so the fallback in Chats.svelte uses the shorter 1 s wait rather than
            // 3.5 s (the payload was non-empty so the normal empty branch below is
            // never reached, leaving the fallback on the slower path without this fix).
            console.warn(
              "[ChatSyncService:CoreSync] ⚠️ processInspirationRecordsFromSync returned 0 despite",
              payload.daily_inspirations.length,
              "records from server — master key likely absent on first login. Triggering short fallback.",
            );
            dailyInspirationStore.markPhase1Empty();
          }
        } catch (inspirationError) {
          console.error(
            "[ChatSyncService:CoreSync] Error processing daily inspirations from Phase 1 sync:",
            inspirationError,
          );
        }
      } else {
        // Phase 1 delivered zero inspirations — the server has none stored for this user.
        // Signal the fallback in Chats.svelte to use a shorter wait (1 s instead of 3.5 s).
        console.warn(
          "[ChatSyncService:CoreSync] ⚠️ No daily inspirations received in Phase 1 — marking phase1Empty so fallback uses 1 s wait instead of 3.5 s",
        );
        dailyInspirationStore.markPhase1Empty();
      }
    } catch (storeImportErr) {
      console.error(
        "[ChatSyncService:CoreSync] Failed to import dailyInspirationStore in Phase 1:",
        storeImportErr,
      );
    }

    // CRITICAL: Save embed_keys FIRST (needed to decrypt embed content for app_id/skill_id extraction)
    // Without embed_keys, embeds cannot be decrypted and putEncrypted can't extract metadata
    if (payload.embed_keys && payload.embed_keys.length > 0) {
      console.info(
        "[ChatSyncService:CoreSync] Saving",
        payload.embed_keys.length,
        "embed_keys to EmbedStore (FIRST, before embeds)",
      );
      try {
        const { embedStore } = await import("./embedStore");

        // Store all embed key entries
        await embedStore.storeEmbedKeys(payload.embed_keys);

        console.info(
          "[ChatSyncService:CoreSync] ✅ Successfully saved",
          payload.embed_keys.length,
          "embed_keys to EmbedStore",
        );
      } catch (embedKeyError) {
        console.error(
          "[ChatSyncService:CoreSync] Error saving embed_keys to EmbedStore:",
          embedKeyError,
        );
      }
    } else {
      console.debug(
        "[ChatSyncService:CoreSync] No embed_keys in Phase 1 payload (embeds may not have keys yet)",
      );
    }

    // Now save embeds - keys are available so putEncrypted can extract app_id/skill_id metadata
    console.debug("[ChatSyncService:CoreSync] Phase 1 payload embeds check:", {
      hasEmbeds: !!payload.embeds,
      embedsLength: payload.embeds?.length || 0,
      embedIds:
        payload.embeds?.map((e: SyncEmbed) => e.embed_id).slice(0, 5) || [],
    });

    if (payload.embeds && payload.embeds.length > 0) {
      console.info(
        "[ChatSyncService:CoreSync] Saving",
        payload.embeds.length,
        "embeds to EmbedStore",
      );
      try {
        const { embedStore } = await import("./embedStore");

        for (const embed of payload.embeds) {
          // Each embed should have: embed_id, encrypted_content, encrypted_type, status, etc.
          if (!embed.embed_id) {
            console.warn(
              "[ChatSyncService:CoreSync] Embed missing embed_id, skipping:",
              embed,
            );
            continue;
          }

          // Skip error/cancelled embeds — not displayed, not worth storing locally
          if (embed.status === "error" || embed.status === "cancelled") {
            console.debug(
              `[ChatSyncService:CoreSync] Skipping ${embed.status} embed ${embed.embed_id}`,
            );
            continue;
          }

          // Create contentRef in the format used by embeds: embed:{embed_id}
          const contentRef = `embed:${embed.embed_id}`;

          // Store the embed with its already-encrypted content (no re-encryption)
          // Skip metadata extraction during bulk sync - embed keys may not be
          // available yet, and attempting decryption per embed is expensive.
          // Metadata will be extracted later when embeds are accessed.
          await embedStore.putEncrypted(
            contentRef,
            {
              encrypted_content: embed.encrypted_content, // Already client-encrypted from Directus
              encrypted_type: embed.encrypted_type, // Already client-encrypted from Directus
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
            (embed.encrypted_type
              ? "app-skill-use"
              : embed.embed_type || "app-skill-use") as EmbedType,
            undefined, // plaintextContent
            undefined, // preExtractedMetadata
            { skipMetadataExtraction: true },
          );
        }

        console.info(
          "[ChatSyncService:CoreSync] ✅ Successfully saved",
          payload.embeds.length,
          "embeds to EmbedStore (as-is, no re-encryption)",
        );
      } catch (embedError) {
        console.error(
          "[ChatSyncService:CoreSync] Error saving embeds to EmbedStore:",
          embedError,
        );
      }
    } else {
      console.debug(
        "[ChatSyncService:CoreSync] No embeds in Phase 1 payload (chat may not have any)",
      );
    }

    // CRITICAL FIX: Add delay to ensure ALL IndexedDB operations are queryable
    // This includes chat suggestions which use their own transaction
    await new Promise((resolve) => setTimeout(resolve, 50));
  } catch (error) {
    console.error(
      "[ChatSyncService:CoreSync] Error saving Phase 1 data to IndexedDB:",
      error,
    );
  }

  // CRITICAL FIX: Populate resume card data directly from Phase 1 data.
  // This ensures the resume card appears on the welcome screen regardless of
  // whether Chats.svelte (sidebar) is mounted. Previously, only the sidebar's
  // event listener called setResumeChatData(), so on mobile or when sidebar was
  // closed, the resume card never appeared after login.
  if (payload.chat_id && payload.chat_details) {
    try {
      // Reconstruct the Chat object from payload (same as chatWithId built above).
      // chat_details is Partial<Chat> from the server — cast to Chat since we only
      // need encrypted_title/category/icon/chat_key fields for the resume card.
      const chatForResume = {
        ...payload.chat_details,
        chat_id: payload.chat_id,
      } as Chat;
      await populateResumeChatDataFromPhase1(chatForResume, payload.chat_id);
    } catch (resumeErr) {
      console.warn(
        "[ChatSyncService:CoreSync] Failed to populate resume card from Phase 1 data:",
        resumeErr,
      );
    }
  }

  // Now dispatch event so Chats.svelte can open the chat
  console.info(
    "[ChatSyncService:CoreSync] Dispatching phase_1_last_chat_ready event with payload:",
    payload,
  );
  serviceInstance.dispatchEvent(
    new CustomEvent("phase_1_last_chat_ready", { detail: payload }),
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
    "[ChatSyncService:CoreSync] Received 'cache_status_response':",
    payload,
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
