// frontend/packages/ui/src/services/chatSyncServiceHandlersPhasedSync.ts
// Handles phased sync (Phase 2/3) event handlers and storage operations.
// These handlers process bulk chat data during the 3-phase sync process.

import type { ChatSynchronizationService } from "./chatSyncService";
import type {
  Phase2RecentChatsPayload,
  Phase3FullSyncPayload,
  PhasedSyncCompletePayload,
  SyncStatusResponsePayload,
  SyncEmbed,
  Chat,
  Message,
  MessageStatus,
} from "../types/chat";
import type { EmbedKeyEntry } from "./embedStore";
import type { EmbedType } from "../message_parsing/types";
import { chatDB } from "./db";
import { userDB } from "./userDB";

/**
 * Handle Phase 2 completion (recent chats ready)
 *
 * NOTE: This handler receives TWO different payload formats:
 * 1. Cache warming notification: {chat_count: N} - Just metadata, no actual chat data
 * 2. Direct sync response: {chats: [...], chat_count: N, phase: 'phase2'} - Full chat data
 *
 * We must validate the payload and only process when actual chat data is present.
 */
export async function handlePhase2RecentChatsImpl(
  serviceInstance: ChatSynchronizationService,
  payload: Phase2RecentChatsPayload,
): Promise<void> {
  console.log(
    "[ChatSyncService] Phase 2 complete - recent chats ready:",
    payload,
  );

  try {
    // Phase2RecentChatsPayload may have additional fields (embeds, embed_keys) not in the type definition
    const { chats, chat_count, embeds, embed_keys } =
      payload as Phase2RecentChatsPayload & {
        embeds?: SyncEmbed[];
        embed_keys?: EmbedKeyEntry[];
      };

    // CRITICAL: Validate that chats array exists before processing
    // The cache warming task sends {chat_count: N} without chats array
    // The direct sync handler sends {chats: [...], embeds: [...], embed_keys: [...], chat_count: N, phase: 'phase2'}
    if (!chats || !Array.isArray(chats)) {
      console.debug(
        "[ChatSyncService] Phase 2 notification received (cache warming), waiting for actual chat data...",
      );
      return;
    }

    // Only process when we have actual chat data
    if (chats.length === 0) {
      console.debug(
        "[ChatSyncService] Phase 2 received empty chats array, nothing to store",
      );
      // Still store embeds and embed_keys if any (they can exist without chats being sent)
      // CRITICAL: Store embed_keys FIRST so putEncrypted can decrypt content to extract app_id/skill_id
      if (embed_keys && Array.isArray(embed_keys) && embed_keys.length > 0) {
        await storeEmbedKeysBatch(embed_keys, "Phase 2");
      }
      if (embeds && Array.isArray(embeds) && embeds.length > 0) {
        await storeEmbedsBatch(embeds, "Phase 2");
      }
      return;
    }

    // Store recent chats data
    await storeRecentChats(serviceInstance, chats);

    // CRITICAL: Store embed_keys FIRST (needed to decrypt embed content for app_id/skill_id extraction)
    if (embed_keys && Array.isArray(embed_keys) && embed_keys.length > 0) {
      await storeEmbedKeysBatch(embed_keys, "Phase 2");
    }

    // Store embeds from flat array (new format - deduplicated by backend)
    // Now that keys are stored, putEncrypted can extract app_id/skill_id from decrypted content
    if (embeds && Array.isArray(embeds) && embeds.length > 0) {
      await storeEmbedsBatch(embeds, "Phase 2");
    }

    // Dispatch event for UI components - use the correct event name that Chats.svelte listens for
    serviceInstance.dispatchEvent(
      new CustomEvent("phase_2_last_20_chats_ready", {
        detail: { chat_count },
      }),
    );
  } catch (error) {
    console.error(
      "[ChatSyncService] Error handling Phase 2 completion:",
      error,
    );
  }
}

/**
 * Handle Phase 3 completion (full sync ready)
 *
 * NOTE: This handler receives TWO different payload formats:
 * 1. Cache warming notification: {chat_count: N} - Just metadata, no actual chat data
 * 2. Direct sync response: {chats: [...], chat_count: N, phase: 'phase3'} - Full chat data
 *
 * We must validate the payload and only process when actual chat data is present.
 */
export async function handlePhase3FullSyncImpl(
  serviceInstance: ChatSynchronizationService,
  payload: Phase3FullSyncPayload,
): Promise<void> {
  console.log("[ChatSyncService] Phase 3 complete - full sync ready:", payload);

  try {
    // Phase3FullSyncPayload may have additional fields (embeds, embed_keys) not in the type definition
    const { chats, chat_count, new_chat_suggestions, embeds, embed_keys } =
      payload as Phase3FullSyncPayload & {
        embeds?: SyncEmbed[];
        embed_keys?: EmbedKeyEntry[];
      };

    // CRITICAL: Validate that chats array exists before processing
    // The cache warming task sends {chat_count: N} without chats array
    // The direct sync handler sends {chats: [...], embeds: [...], embed_keys: [...], chat_count: N, phase: 'phase3'}
    if (!chats || !Array.isArray(chats)) {
      console.debug(
        "[ChatSyncService] Phase 3 notification received (cache warming), waiting for actual chat data...",
      );
      return;
    }

    // Only process when we have actual chat data
    if (chats.length === 0) {
      console.debug(
        "[ChatSyncService] Phase 3 received empty chats array, nothing to store",
      );
      // Still store embeds and embed_keys if any (they can exist without chats being sent)
      // CRITICAL: Store embed_keys FIRST so putEncrypted can decrypt content to extract app_id/skill_id
      if (embed_keys && Array.isArray(embed_keys) && embed_keys.length > 0) {
        await storeEmbedKeysBatch(embed_keys, "Phase 3");
      }
      if (embeds && Array.isArray(embeds) && embeds.length > 0) {
        await storeEmbedsBatch(embeds, "Phase 3");
      }
      return;
    }

    // Store all chats data
    await storeAllChats(serviceInstance, chats);

    // CRITICAL: Store embed_keys FIRST (needed to decrypt embed content for app_id/skill_id extraction)
    if (embed_keys && Array.isArray(embed_keys) && embed_keys.length > 0) {
      await storeEmbedKeysBatch(embed_keys, "Phase 3");
    }

    // Store embeds from flat array (new format - deduplicated by backend)
    // Now that keys are stored, putEncrypted can extract app_id/skill_id from decrypted content
    if (embeds && Array.isArray(embeds) && embeds.length > 0) {
      await storeEmbedsBatch(embeds, "Phase 3");
    }

    // Store new chat suggestions if provided
    if (
      new_chat_suggestions &&
      Array.isArray(new_chat_suggestions) &&
      new_chat_suggestions.length > 0
    ) {
      console.log(
        `[ChatSyncService] Storing ${new_chat_suggestions.length} new chat suggestions`,
      );
      // Pass full NewChatSuggestion objects with IDs from server
      // Normalize to NewChatSuggestion format if needed
      const normalizedSuggestions = new_chat_suggestions.map((s) => {
        if (typeof s === "string") {
          // Backward compatibility: if string, create object with generated ID
          return {
            id: globalThis.crypto.randomUUID(),
            encrypted_suggestion: s,
            chat_id: "global",
            created_at: Math.floor(Date.now() / 1000),
          };
        }
        return s;
      });
      await chatDB.saveEncryptedNewChatSuggestions(
        normalizedSuggestions,
        "global",
      );
    } else {
      console.debug("[ChatSyncService] No new chat suggestions to store");
    }

    // Dispatch event for UI components - use event name that Chats.svelte listens for
    serviceInstance.dispatchEvent(
      new CustomEvent("phase_3_last_100_chats_ready", {
        detail: {
          chat_count,
          suggestions_count: new_chat_suggestions?.length || 0,
        },
      }),
    );

    // Also dispatch fullSyncReady for NewChatSuggestions.svelte
    serviceInstance.dispatchEvent(
      new CustomEvent("fullSyncReady", {
        detail: {
          chat_count,
          suggestions_count: new_chat_suggestions?.length || 0,
        },
      }),
    );
  } catch (error) {
    console.error(
      "[ChatSyncService] Error handling Phase 3 completion:",
      error,
    );
  }
}

/**
 * Handle phased sync completion
 *
 * CRITICAL: This is called when the server sends the phased_sync_complete message.
 * We must clear the timeout to prevent the synthetic completion event from firing.
 */
export async function handlePhasedSyncCompleteImpl(
  serviceInstance: ChatSynchronizationService,
  payload: PhasedSyncCompletePayload,
): Promise<void> {
  console.log("[ChatSyncService] Phased sync complete:", payload);

  // CRITICAL: Clear the timeout since sync completed successfully
  // This prevents the synthetic timeout event from firing after real completion
  serviceInstance.clearPhasedSyncTimeout();

  serviceInstance.dispatchEvent(
    new CustomEvent("phasedSyncComplete", {
      detail: payload,
    }),
  );
}

/**
 * Handle sync status response
 */
export async function handleSyncStatusResponseImpl(
  serviceInstance: ChatSynchronizationService,
  payload: SyncStatusResponsePayload,
): Promise<void> {
  console.log("[ChatSyncService] Sync status response:", payload);

  // Backend sends 'is_primed', not 'cache_primed'
  const { is_primed, chat_count, timestamp } = payload;

  console.log("[ChatSyncService] Setting cachePrimed flag:", {
    is_primed,
    chat_count,
    cachePrimed_before: serviceInstance.cachePrimed_FOR_HANDLERS_ONLY,
    initialSyncAttempted:
      serviceInstance.initialSyncAttempted_FOR_HANDLERS_ONLY,
  });

  serviceInstance.cachePrimed_FOR_HANDLERS_ONLY = is_primed;

  // Dispatch event to Chats.svelte (converting is_primed → cache_primed for backward compatibility)
  serviceInstance.dispatchEvent(
    new CustomEvent("syncStatusResponse", {
      detail: {
        cache_primed: is_primed, // Convert for Chats.svelte
        chat_count,
        timestamp,
      },
    }),
  );

  // Trigger sync if cache is primed and we haven't attempted yet
  if (
    is_primed &&
    !serviceInstance.initialSyncAttempted_FOR_HANDLERS_ONLY &&
    serviceInstance.webSocketConnected_FOR_SENDERS_ONLY
  ) {
    console.log(
      "[ChatSyncService] ✅ Cache primed! Attempting initial sync...",
    );
    serviceInstance.attemptInitialSync_FOR_HANDLERS_ONLY();
  } else {
    console.log("[ChatSyncService] Not starting sync:", {
      is_primed,
      initialSyncAttempted:
        serviceInstance.initialSyncAttempted_FOR_HANDLERS_ONLY,
      webSocketConnected: serviceInstance.webSocketConnected_FOR_SENDERS_ONLY,
    });
  }
}

// ============================================================================
// STORAGE HELPERS
// ============================================================================

/**
 * Store recent chats (Phase 2)
 * Merges server data with local data, preserving higher version numbers
 */
async function storeRecentChats(
  serviceInstance: ChatSynchronizationService,
  chats: Array<{
    chat_details: Partial<Chat> & { id: string };
    messages?: Message[];
    server_message_count?: number;
  }>,
): Promise<void> {
  try {
    // Get current user's ID for ownership tracking
    // All synced chats belong to the current user (server filters by hashed_user_id)
    const userProfile = await userDB.getUserProfile();
    const currentUserId = userProfile?.user_id;

    for (const chatItem of chats) {
      const { chat_details, messages, server_message_count } = chatItem;
      const chatId = chat_details.id;

      // Get existing local chat to compare versions
      const existingChat = await chatDB.getChat(chatId);

      // Merge server data with local data, preserving higher versions
      let mergedChat = mergeServerChatWithLocal(
        chat_details,
        existingChat,
        currentUserId,
      );

      // CRITICAL: Check if we should sync messages for Phase 2 chats
      // This prevents data inconsistency where messages_v is set but messages are missing
      const shouldSyncMessages =
        messages && Array.isArray(messages) && messages.length > 0;
      const serverMessagesV = chat_details.messages_v || 0;
      const localMessagesV = existingChat?.messages_v || 0;

      // CRITICAL FIX: Validate message count when server skips sending messages
      // If server sends server_message_count but no messages, validate local data
      // This detects data inconsistency where version matches but messages are missing
      if (
        !shouldSyncMessages &&
        server_message_count !== undefined &&
        server_message_count !== null &&
        server_message_count > 0
      ) {
        const localMessages = await chatDB.getMessagesForChat(chatId);
        const localMessageCount = localMessages?.length || 0;

        console.debug(
          `[ChatSyncService] Phase 2 - Message count validation for chat ${chatId}: ` +
            `server_count=${server_message_count}, local_count=${localMessageCount}`,
        );

        // DATA INCONSISTENCY DETECTED: Local has fewer messages than server
        if (localMessageCount < server_message_count) {
          console.warn(
            `[ChatSyncService] Phase 2 - ⚠️ DATA INCONSISTENCY DETECTED for chat ${chatId}: ` +
              `Local has ${localMessageCount} messages but server has ${server_message_count}. ` +
              `Resetting messages_v to 0 to force re-sync.`,
          );

          // Reset the chat's messages_v to 0 to force a full re-sync
          mergedChat = {
            ...mergedChat,
            messages_v: 0, // Reset to force re-sync on next load
          };
          await chatDB.addChat(mergedChat);

          // Dispatch event to notify about the inconsistency
          serviceInstance.dispatchEvent(
            new CustomEvent("chatDataInconsistency", {
              detail: {
                chatId,
                localCount: localMessageCount,
                serverCount: server_message_count,
                phase: "phase2",
              },
            }),
          );
          continue;
        }
      }

      let shouldSkipMessageSync = false;
      if (
        existingChat &&
        serverMessagesV === localMessagesV &&
        shouldSyncMessages
      ) {
        // Check if we have messages in the database
        const localMessages = await chatDB.getMessagesForChat(chatId);
        const localMessageCount = localMessages?.length || 0;
        const serverMessageCount = messages?.length || 0;

        console.debug(
          `[ChatSyncService] Phase 2 - Chat ${chatId}: serverV=${serverMessagesV}, localV=${localMessagesV}, localCount=${localMessageCount}, serverCount=${serverMessageCount}`,
        );

        // Only skip sync if versions match and message counts match
        if (localMessageCount === serverMessageCount && localMessageCount > 0) {
          shouldSkipMessageSync = true;
          console.info(
            `[ChatSyncService] Phase 2 - Skipping message sync for chat ${chatId} - versions match (v${serverMessagesV}) and message counts match (${localMessageCount})`,
          );
        } else if (localMessageCount === 0 && serverMessageCount === 0) {
          shouldSkipMessageSync = true;
          console.info(
            `[ChatSyncService] Phase 2 - Skipping message sync for chat ${chatId} - no messages on server or client`,
          );
        } else {
          console.debug(
            `[ChatSyncService] Phase 2 - Message count mismatch for chat ${chatId}: local=${localMessageCount}, server=${serverMessageCount}. Syncing to fix...`,
          );
        }
      }

      if (shouldSkipMessageSync) {
        await chatDB.addChat(mergedChat);
        continue;
      }

      // For new chats without messages, save immediately
      if (
        !existingChat &&
        (!shouldSyncMessages || !messages || messages.length === 0)
      ) {
        console.debug(
          `[ChatSyncService] Phase 2 - Saving new chat ${chatId} without messages`,
        );
        await chatDB.addChat(mergedChat);
        continue;
      }

      // Prepare all messages before saving
      const preparedMessages = prepareMessagesForStorage(
        messages,
        chatId,
        "Phase 2",
      );

      // Save chat and messages
      try {
        await chatDB.addChat(mergedChat);
        console.debug(
          `[ChatSyncService] Phase 2 - Saved chat ${chatId} to IndexedDB`,
        );

        if (shouldSyncMessages && preparedMessages.length > 0) {
          console.log(
            `[CLIENT_SYNC] Phase 2 - Syncing ${preparedMessages.length} messages for chat ${chatId} ` +
              `(server v${serverMessagesV}, local v${localMessagesV})`,
          );
          await chatDB.batchSaveMessages(preparedMessages);
          console.log(
            `[CLIENT_SYNC] ✅ Phase 2 - Successfully saved ${preparedMessages.length} messages for chat ${chatId}`,
          );
        }
      } catch (saveError) {
        console.error(
          `[ChatSyncService] Phase 2 - Error saving chat/messages for chat ${chatId}:`,
          saveError,
        );
      }
    }

    console.log(
      `[ChatSyncService] Phase 2 - Stored ${chats.length} recent chats with message sync`,
    );
  } catch (error) {
    console.error(
      "[ChatSyncService] Phase 2 - Error storing recent chats:",
      error,
    );
  }
}

/**
 * Store all chats (Phase 3)
 * Merges server data with local data, preserving higher version numbers
 * Also handles messages if provided in the payload
 *
 * CRITICAL: Uses transactions to prevent duplicate messages during reconnection
 */
async function storeAllChats(
  serviceInstance: ChatSynchronizationService,
  chats: Array<{
    chat_details: Partial<Chat> & { id: string };
    messages?: Message[];
    server_message_count?: number;
  }>,
): Promise<void> {
  try {
    console.debug(
      `[ChatSyncService] storeAllChats: Processing ${chats.length} chats from Phase 3`,
    );

    // Get current user's ID for ownership tracking
    // All synced chats belong to the current user (server filters by hashed_user_id)
    const userProfile = await userDB.getUserProfile();
    const currentUserId = userProfile?.user_id;

    for (const chatItem of chats) {
      const { chat_details, messages, server_message_count } = chatItem;
      const chatId = chat_details.id;

      console.debug(
        `[ChatSyncService] Processing chat ${chatId} with ${messages?.length || 0} messages`,
      );

      // Get existing local chat to compare versions
      const existingChat = await chatDB.getChat(chatId);

      // Merge server data with local data, preserving higher versions
      let mergedChat = mergeServerChatWithLocal(
        chat_details,
        existingChat,
        currentUserId,
      );

      // Check if we should sync messages
      const shouldSyncMessages =
        messages && Array.isArray(messages) && messages.length > 0;
      const serverMessagesV = chat_details.messages_v || 0;
      const localMessagesV = existingChat?.messages_v || 0;

      // CRITICAL FIX: Validate message count when server skips sending messages
      // If server sends server_message_count but no messages, validate local data
      // This detects data inconsistency where version matches but messages are missing
      if (
        !shouldSyncMessages &&
        server_message_count !== undefined &&
        server_message_count !== null &&
        server_message_count > 0
      ) {
        const localMessages = await chatDB.getMessagesForChat(chatId);
        const localMessageCount = localMessages?.length || 0;

        console.debug(
          `[ChatSyncService] Phase 3 - Message count validation for chat ${chatId}: ` +
            `server_count=${server_message_count}, local_count=${localMessageCount}`,
        );

        // DATA INCONSISTENCY DETECTED: Local has fewer messages than server
        if (localMessageCount < server_message_count) {
          console.warn(
            `[ChatSyncService] Phase 3 - ⚠️ DATA INCONSISTENCY DETECTED for chat ${chatId}: ` +
              `Local has ${localMessageCount} messages but server has ${server_message_count}. ` +
              `Resetting messages_v to 0 to force re-sync.`,
          );

          // Reset the chat's messages_v to 0 to force a full re-sync
          mergedChat = {
            ...mergedChat,
            messages_v: 0, // Reset to force re-sync on next load
          };
          await chatDB.addChat(mergedChat);

          // Dispatch event to notify about the inconsistency
          serviceInstance.dispatchEvent(
            new CustomEvent("chatDataInconsistency", {
              detail: {
                chatId,
                localCount: localMessageCount,
                serverCount: server_message_count,
                phase: "phase3",
              },
            }),
          );
          continue;
        }
      }

      let shouldSkipMessageSync = false;
      if (
        existingChat &&
        serverMessagesV === localMessagesV &&
        shouldSyncMessages
      ) {
        const localMessages = await chatDB.getMessagesForChat(chatId);
        const localMessageCount = localMessages?.length || 0;
        const serverMessageCount = messages?.length || 0;

        console.debug(
          `[ChatSyncService] Chat ${chatId}: serverV=${serverMessagesV}, localV=${localMessagesV}, localCount=${localMessageCount}, serverCount=${serverMessageCount}`,
        );

        if (localMessageCount === serverMessageCount && localMessageCount > 0) {
          shouldSkipMessageSync = true;
          console.info(
            `[ChatSyncService] Skipping message sync for chat ${chatId} - versions match (v${serverMessagesV}) and message counts match (${localMessageCount})`,
          );
        } else if (localMessageCount === 0 && serverMessageCount === 0) {
          shouldSkipMessageSync = true;
          console.info(
            `[ChatSyncService] Skipping message sync for chat ${chatId} - no messages on server or client`,
          );
        } else {
          console.debug(
            `[ChatSyncService] Message count mismatch for chat ${chatId}: local=${localMessageCount}, server=${serverMessageCount}. Syncing to fix...`,
          );
          if (existingChat) {
            mergedChat.messages_v = serverMessagesV;
          }
        }
      }

      if (shouldSkipMessageSync) {
        await chatDB.addChat(mergedChat);
        continue;
      }

      // Save chat and messages
      try {
        await chatDB.addChat(mergedChat);
        console.debug(
          `[ChatSyncService] Phase 3 - Saved chat ${chatId} to IndexedDB`,
        );

        if (shouldSyncMessages && messages && messages.length > 0) {
          const preparedMessages = prepareMessagesForStorage(
            messages,
            chatId,
            "Phase 3",
          );

          if (preparedMessages.length > 0) {
            console.log(
              `[CLIENT_SYNC] Phase 3 - Syncing ${preparedMessages.length} messages for chat ${chatId} ` +
                `(server v${serverMessagesV}, local v${localMessagesV})`,
            );
            await chatDB.batchSaveMessages(preparedMessages);
            console.log(
              `[CLIENT_SYNC] ✅ Phase 3 - Successfully saved ${preparedMessages.length} messages for chat ${chatId}`,
            );
          }
        }
      } catch (saveError) {
        console.error(
          `[ChatSyncService] Phase 3 - Error saving chat/messages for chat ${chatId}:`,
          saveError,
        );
      }
    }

    console.log(
      `[ChatSyncService] Stored ${chats.length} all chats (Phase 3) with duplicate prevention`,
    );
  } catch (error) {
    console.error("[ChatSyncService] Error storing all chats:", error);
  }
}

/**
 * Prepare messages for storage - parses JSON strings and validates required fields
 */
function prepareMessagesForStorage(
  messages: Message[],
  chatId: string,
  phaseName: string,
): Message[] {
  const preparedMessages: Message[] = [];

  if (!messages || !Array.isArray(messages)) {
    return preparedMessages;
  }

  for (const messageData of messages) {
    let message = messageData;

    // Parse JSON string if needed
    if (typeof messageData === "string") {
      try {
        message = JSON.parse(messageData);
        const messageId =
          message.message_id || (message as Message & { id?: string }).id;
        console.debug(
          `[ChatSyncService] ${phaseName} - Parsed message JSON string for message: ${messageId}`,
        );
      } catch (e) {
        console.error(
          `[ChatSyncService] ${phaseName} - Failed to parse message JSON for chat ${chatId}:`,
          e,
        );
        continue;
      }
    }

    // Use 'id' field as message_id if message_id is missing
    if (!message.message_id && (message as Message & { id?: string }).id) {
      message.message_id = (message as Message & { id?: string }).id;
    }

    // Skip messages without message_id
    if (!message.message_id) {
      console.error(
        `[ChatSyncService] ${phaseName} - Message missing message_id after parsing, skipping:`,
        message,
      );
      continue;
    }

    // Ensure chat_id is set
    if (!message.chat_id) {
      message.chat_id = chatId;
    }

    // Set default status if missing
    if (!message.status) {
      message.status = "delivered" as MessageStatus;
    }

    preparedMessages.push(message);
  }

  return preparedMessages;
}

/**
 * Store embeds from a flat array (new format from backend with cross-phase deduplication)
 * Backend ensures no duplicates are sent across phases, so we just store all received embeds
 *
 * CRITICAL: Embeds from sync arrive with encrypted_content that is ALREADY client-encrypted
 * (from when the embed was originally stored in Directus). We store them as-is without
 * re-encryption, matching the pattern used for messages. Decryption happens on-demand
 * when embeds are retrieved for rendering.
 *
 * @param embeds - Flat array of embed objects (already deduplicated by backend)
 * @param phaseName - Phase name for logging (e.g., "Phase 1", "Phase 2", "Phase 3")
 */
async function storeEmbedsBatch(
  embeds: SyncEmbed[],
  phaseName: string,
): Promise<void> {
  try {
    const { embedStore } = await import("./embedStore");
    let storedCount = 0;

    for (const embed of embeds) {
      if (!embed.embed_id) {
        console.warn(
          `[ChatSyncService] ${phaseName} - Skipping embed without embed_id`,
        );
        continue;
      }

      try {
        // Create contentRef in the format used by embeds: embed:{embed_id}
        const contentRef = `embed:${embed.embed_id}`;

        // Store the embed with its already-encrypted content (no re-encryption)
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
          (embed.encrypted_type
            ? "app-skill-use"
            : embed.embed_type || "app-skill-use") as EmbedType,
        );

        storedCount++;
      } catch (embedError) {
        console.warn(
          `[ChatSyncService] ${phaseName} - Error storing embed ${embed.embed_id}:`,
          embedError,
        );
      }
    }

    if (storedCount > 0) {
      console.info(
        `[ChatSyncService] ${phaseName} - Stored ${storedCount} embeds (as-is, no re-encryption)`,
      );
    } else {
      console.debug(`[ChatSyncService] ${phaseName} - No embeds stored`);
    }
  } catch (error) {
    console.error(
      `[ChatSyncService] ${phaseName} - Error storing embeds batch:`,
      error,
    );
  }
}

/**
 * Store embed_keys from a flat array (new format from backend with cross-phase deduplication)
 * Backend ensures no duplicates are sent across phases, so we just store all received embed_keys
 *
 * CRITICAL: Embed keys are needed to decrypt embed content. Without embed_keys, embeds cannot
 * be decrypted and will show errors. These keys are wrapped (encrypted) with either the master
 * key or chat key, and are unwrapped on-demand when decrypting embed content.
 *
 * @param embed_keys - Flat array of embed_key objects (already deduplicated by backend)
 * @param phaseName - Phase name for logging (e.g., "Phase 1", "Phase 2", "Phase 3")
 */
async function storeEmbedKeysBatch(
  embed_keys: EmbedKeyEntry[],
  phaseName: string,
): Promise<void> {
  try {
    const { embedStore } = await import("./embedStore");

    // Store all embed key entries
    await embedStore.storeEmbedKeys(embed_keys);

    console.info(
      `[ChatSyncService] ${phaseName} - Stored ${embed_keys.length} embed_keys`,
    );
  } catch (error) {
    console.error(
      `[ChatSyncService] ${phaseName} - Error storing embed_keys batch:`,
      error,
    );
  }
}

/**
 * Merge rejected suggestion hashes from local and server for cross-device sync.
 * Returns a union of both arrays with duplicates removed.
 * This ensures rejected suggestions stay rejected across all devices.
 *
 * @param localHashes - Local rejected suggestion hashes (may be null/undefined)
 * @param serverHashes - Server rejected suggestion hashes (may be null/undefined)
 * @returns Merged array of unique hashes, or null if both inputs are empty/null
 */
function mergeRejectedHashes(
  localHashes: string[] | null | undefined,
  serverHashes: string[] | null | undefined,
): string[] | null {
  const local = localHashes ?? [];
  const server = serverHashes ?? [];

  // If both empty, return null to avoid storing empty arrays
  if (local.length === 0 && server.length === 0) {
    return null;
  }

  // Create union using Set for deduplication
  const mergedSet = new Set([...local, ...server]);
  const merged = Array.from(mergedSet);
  return merged;
}

/**
 * Merge server chat data with local chat data
 * Preserves local data when version numbers are higher or equal
 * This prevents phased sync from overwriting locally updated data that hasn't been synced yet
 *
 * @param serverChat - Server chat data with at least the 'id' field
 * @param localChat - Existing local chat data (or null if not exists locally)
 * @param currentUserId - Current user's ID (all synced chats belong to them - server filters by hashed_user_id)
 * @returns Merged chat data with required fields for Chat type
 */
function mergeServerChatWithLocal(
  serverChat: Partial<Chat> & { id: string },
  localChat: Chat | null,
  currentUserId?: string,
): Chat {
  const nowTimestamp = Math.floor(Date.now() / 1000);

  // If no local chat exists, use server data with defaults
  if (!localChat) {
    console.debug(
      `[ChatSyncService] No local chat found, using server data for chat ${serverChat.id}`,
    );
    return {
      chat_id: serverChat.id,
      encrypted_title: serverChat.encrypted_title ?? null,
      messages_v: serverChat.messages_v ?? 0,
      title_v: serverChat.title_v ?? 0,
      draft_v: serverChat.draft_v ?? 0,
      unread_count: serverChat.unread_count ?? 0,
      created_at: serverChat.created_at ?? nowTimestamp,
      updated_at: serverChat.updated_at ?? nowTimestamp,
      last_edited_overall_timestamp:
        serverChat.last_edited_overall_timestamp ??
        serverChat.updated_at ??
        nowTimestamp,
      encrypted_draft_md: serverChat.encrypted_draft_md,
      encrypted_draft_preview: serverChat.encrypted_draft_preview,
      encrypted_chat_key: serverChat.encrypted_chat_key,
      encrypted_icon: serverChat.encrypted_icon,
      encrypted_category: serverChat.encrypted_category,
      last_visible_message_id: serverChat.last_visible_message_id,
      pinned: serverChat.pinned,
      // CRITICAL: Include post-processing metadata fields
      // These fields are populated after AI post-processing and should be preserved during sync
      encrypted_follow_up_request_suggestions:
        serverChat.encrypted_follow_up_request_suggestions,
      encrypted_chat_summary: serverChat.encrypted_chat_summary,
      encrypted_chat_tags: serverChat.encrypted_chat_tags,
      encrypted_top_recommended_apps_for_chat:
        serverChat.encrypted_top_recommended_apps_for_chat,
      // Settings/memories suggestions from post-processing Phase 2
      encrypted_settings_memories_suggestions:
        serverChat.encrypted_settings_memories_suggestions,
      rejected_suggestion_hashes: serverChat.rejected_suggestion_hashes,
      // Include sharing fields from server sync
      is_shared: serverChat.is_shared,
      is_private: serverChat.is_private,
      // Set user_id from current user (all synced chats belong to them - server filters by hashed_user_id)
      user_id: currentUserId,
    };
  }

  // Start with server data as base, using defaults from local chat where server data is missing
  const merged: Chat = {
    chat_id: serverChat.id,
    // Preserve local user_id (ownership doesn't change)
    user_id: localChat.user_id ?? currentUserId,
    encrypted_title:
      serverChat.encrypted_title ?? localChat.encrypted_title ?? null,
    messages_v: serverChat.messages_v ?? localChat.messages_v ?? 0,
    title_v: serverChat.title_v ?? localChat.title_v ?? 0,
    draft_v: serverChat.draft_v ?? localChat.draft_v ?? 0,
    unread_count: serverChat.unread_count ?? localChat.unread_count ?? 0,
    created_at: serverChat.created_at ?? localChat.created_at ?? nowTimestamp,
    updated_at: serverChat.updated_at ?? localChat.updated_at ?? nowTimestamp,
    last_edited_overall_timestamp:
      serverChat.last_edited_overall_timestamp ??
      localChat.last_edited_overall_timestamp ??
      nowTimestamp,
    encrypted_draft_md:
      serverChat.encrypted_draft_md ?? localChat.encrypted_draft_md,
    encrypted_draft_preview:
      serverChat.encrypted_draft_preview ?? localChat.encrypted_draft_preview,
    encrypted_chat_key:
      serverChat.encrypted_chat_key ?? localChat.encrypted_chat_key,
    encrypted_icon: serverChat.encrypted_icon ?? localChat.encrypted_icon,
    encrypted_category:
      serverChat.encrypted_category ?? localChat.encrypted_category,
    last_visible_message_id:
      serverChat.last_visible_message_id ?? localChat.last_visible_message_id,
    pinned: serverChat.pinned ?? localChat.pinned,
    // CRITICAL: Include post-processing metadata fields
    // Server data takes precedence, but fall back to local if server data is missing
    // This ensures suggestions synced from another device are preserved
    encrypted_follow_up_request_suggestions:
      serverChat.encrypted_follow_up_request_suggestions ??
      localChat.encrypted_follow_up_request_suggestions,
    encrypted_chat_summary:
      serverChat.encrypted_chat_summary ?? localChat.encrypted_chat_summary,
    encrypted_chat_tags:
      serverChat.encrypted_chat_tags ?? localChat.encrypted_chat_tags,
    encrypted_top_recommended_apps_for_chat:
      serverChat.encrypted_top_recommended_apps_for_chat ??
      localChat.encrypted_top_recommended_apps_for_chat,
    // Settings/memories suggestions from post-processing Phase 2
    // Server takes precedence since suggestions are overwritten each response
    encrypted_settings_memories_suggestions:
      serverChat.encrypted_settings_memories_suggestions ??
      localChat.encrypted_settings_memories_suggestions,
    // Merge rejected suggestion hashes - union of local and server for zero-knowledge cross-device sync
    rejected_suggestion_hashes: mergeRejectedHashes(
      localChat.rejected_suggestion_hashes,
      serverChat.rejected_suggestion_hashes,
    ),
    // Include sharing fields from server sync, falling back to local if server data is missing
    is_shared: serverChat.is_shared ?? localChat.is_shared,
    is_private: serverChat.is_private ?? localChat.is_private,
  };

  // Preserve local encrypted_title if local title_v is higher or equal
  const localTitleV = localChat.title_v || 0;
  const serverTitleV = serverChat.title_v || 0;
  if (localTitleV >= serverTitleV && localChat.encrypted_title) {
    merged.encrypted_title = localChat.encrypted_title;
    merged.title_v = localChat.title_v;
    console.debug(
      `[ChatSyncService] Preserving local title for chat ${merged.chat_id} (local v${localTitleV} >= server v${serverTitleV})`,
    );
  }

  // Preserve local draft if local draft_v is higher or equal
  const localDraftV = localChat.draft_v || 0;
  const serverDraftV = serverChat.draft_v || 0;
  if (localDraftV >= serverDraftV) {
    if (localChat.encrypted_draft_md) {
      merged.encrypted_draft_md = localChat.encrypted_draft_md;
    }
    if (localChat.encrypted_draft_preview) {
      merged.encrypted_draft_preview = localChat.encrypted_draft_preview;
    }
    merged.draft_v = localChat.draft_v;
    console.debug(
      `[ChatSyncService] Preserving local draft for chat ${merged.chat_id} (local v${localDraftV} >= server v${serverDraftV})`,
    );
  }

  // Use server's encrypted_chat_key if available, otherwise keep local.
  // This ensures we can decrypt messages synced from the server even if our local key was
  // incorrectly generated (e.g. during a race condition or stale session).
  if (serverChat.encrypted_chat_key) {
    if (
      localChat.encrypted_chat_key &&
      localChat.encrypted_chat_key !== serverChat.encrypted_chat_key
    ) {
      console.warn(
        `[ChatSyncService] ⚠️ Chat key mismatch for chat ${merged.chat_id}! ` +
          `Local key differs from server key. Overwriting local key with server's source of truth.`,
      );
    }
    merged.encrypted_chat_key = serverChat.encrypted_chat_key;
  } else if (localChat.encrypted_chat_key) {
    merged.encrypted_chat_key = localChat.encrypted_chat_key;
    console.debug(
      `[ChatSyncService] Preserving local encrypted_chat_key for chat ${merged.chat_id} (server key missing)`,
    );
  }

  // Preserve local messages_v if higher
  const localMessagesV = localChat.messages_v || 0;
  const serverMessagesV = serverChat.messages_v || 0;
  if (localMessagesV > serverMessagesV) {
    merged.messages_v = localChat.messages_v;
    console.debug(
      `[ChatSyncService] Preserving local messages_v for chat ${merged.chat_id} (local v${localMessagesV} > server v${serverMessagesV})`,
    );
  }

  return merged;
}
