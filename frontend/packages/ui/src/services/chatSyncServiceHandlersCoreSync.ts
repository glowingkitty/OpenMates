// frontend/packages/ui/src/services/chatSyncServiceHandlersCoreSync.ts
import type { ChatSynchronizationService } from './chatSyncService';
import { chatDB } from './db';
import { userDB } from './userDB';
import { notificationStore } from '../stores/notificationStore';
import type {
    InitialSyncResponsePayload,
    Phase1LastChatPayload,
    CachePrimedPayload,
    CacheStatusResponsePayload,
    ChatContentBatchResponsePayload,
    OfflineSyncCompletePayload,
    Chat,
    Message,
    MessageStatus, // Added MessageStatus for status type
    ServerBatchMessageFormat,
    SyncEmbed
} from '../types/chat';
import type { EmbedType } from '../message_parsing/types';

export async function handleInitialSyncResponseImpl(
    serviceInstance: ChatSynchronizationService,
    payload: InitialSyncResponsePayload
): Promise<void> {
    console.info("[ChatSyncService:CoreSync] Received initial_sync_response (delta_sync_data):", payload);
    let transaction: IDBTransaction | null = null;
    
    try {
        // CRITICAL: Do all async processing FIRST, THEN create transaction
        // If transaction is created before async work, it will auto-commit
        
        // Process chats with async decryption
        const chatsToUpdate: Chat[] = await Promise.all(payload.chats_to_add_or_update.map(async (serverChat) => {
            // Decrypt encrypted title from server for in-memory use using chat-specific key
            let cleartextTitle: string | null = null;
            if (serverChat.encrypted_title && serverChat.encrypted_chat_key) {
                console.log(
                    `[CLIENT_DECRYPT] ✅ Chat ${serverChat.chat_id} has encrypted_chat_key: ` +
                    `${serverChat.encrypted_chat_key.substring(0, 20)}... (length: ${serverChat.encrypted_chat_key.length})`
                );
                // First, decrypt the chat key from encrypted_chat_key using master key
                const { decryptChatKeyWithMasterKey } = await import('./cryptoService');
                const chatKey = await decryptChatKeyWithMasterKey(serverChat.encrypted_chat_key);

                if (chatKey) {
                    // Cache the decrypted chat key for future use
                    chatDB.setChatKey(serverChat.chat_id, chatKey);
                    console.log(
                        `[CLIENT_DECRYPT] ✅ Decrypted and cached chat key for ${serverChat.chat_id} ` +
                        `(key length: ${chatKey.length} bytes)`
                    );

                    // Now decrypt the title with the chat key
                    const { decryptWithChatKey } = await import('./cryptoService');
                    cleartextTitle = await decryptWithChatKey(serverChat.encrypted_title, chatKey);
                    if (cleartextTitle) {
                        console.log(
                            `[CLIENT_DECRYPT] ✅ Successfully decrypted title for chat ${serverChat.chat_id}: "${cleartextTitle.substring(0, 50)}..."`
                        );
                    } else {
                        console.warn(`[CLIENT_DECRYPT] ❌ Failed to decrypt title for chat ${serverChat.chat_id}`);
                        cleartextTitle = serverChat.encrypted_title; // Fallback to encrypted content if decryption fails
                    }
                } else {
                    console.error(
                        `[CLIENT_DECRYPT] ❌ CRITICAL: Failed to decrypt chat key for chat ${serverChat.chat_id} - ` +
                        `chat will not be decryptable!`
                    );
                    cleartextTitle = serverChat.encrypted_title; // Fallback to encrypted content if decryption fails
                }
            } else if (serverChat.encrypted_title) {
                console.error(
                    `[CLIENT_DECRYPT] ❌ CRITICAL: Chat ${serverChat.chat_id} missing encrypted_chat_key - ` +
                    `cannot decrypt title or messages!`
                );
                cleartextTitle = serverChat.encrypted_title;
            } else {
                console.warn(
                    `[CLIENT_DECRYPT] ⚠️ Chat ${serverChat.chat_id} has no encrypted_title or encrypted_chat_key`
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
                last_edited_overall_timestamp: serverChat.last_edited_overall_timestamp,
                unread_count: serverChat.unread_count,
                created_at: serverChat.created_at,
                updated_at: serverChat.updated_at,
                // Include sharing fields from server sync for cross-device consistency
                is_shared: serverChat.is_shared !== undefined ? serverChat.is_shared : undefined,
                is_private: serverChat.is_private !== undefined ? serverChat.is_private : undefined,
            };
            return chat;
        }));

        const messagesToSave: Message[] = payload.chats_to_add_or_update.flatMap(chat =>
            (chat.messages || []).map(msg => {
                // Handle missing message_id - check if msg has 'id' property (legacy format)
                const messageId = (msg as Message & { id?: string }).id || msg.message_id;
                return {
                    ...msg,
                    message_id: messageId,
                };
            })
        );

        // NOW create the transaction after all async preparation work
        // CRITICAL: Clean up embeds for chats being deleted BEFORE starting the transaction
        if (payload.chat_ids_to_delete && payload.chat_ids_to_delete.length > 0) {
            try {
                const { embedStore } = await import('./embedStore');
                for (const chatId of payload.chat_ids_to_delete) {
                    await embedStore.deleteEmbedsForChat(chatId);
                }
            } catch (error) {
                console.error("[ChatSyncService:CoreSync] Error cleaning up embeds during sync delete:", error);
            }
        }

        transaction = await chatDB.getTransaction(
            [chatDB['CHATS_STORE_NAME'], chatDB['MESSAGES_STORE_NAME']],
            'readwrite'
        );

        // Set the oncomplete handler IMMEDIATELY after creating transaction
        transaction.oncomplete = () => {
            console.info("[ChatSyncService:CoreSync] Delta sync DB transaction complete.");
            // Use the service's dispatchEvent method correctly
            serviceInstance.dispatchEvent(new CustomEvent('syncComplete', { 
                detail: { serverChatOrder: payload.server_chat_order } 
            }));
            serviceInstance.isSyncing_FOR_HANDLERS_ONLY = false;
        };

        transaction.onerror = (event) => {
            console.error("[ChatSyncService:CoreSync] Error in delta_sync_data transaction:", (event.target as IDBRequest).error);
            const errorMessage = (event.target as IDBRequest).error?.message || "Unknown database transaction error";
            notificationStore.error(`Error processing server sync data: ${errorMessage}`);
            serviceInstance.isSyncing_FOR_HANDLERS_ONLY = false;
        };

        // This function now returns a promise that resolves when all operations are queued.
        // The transaction will auto-commit after this.
        await chatDB.batchProcessChatData(
            chatsToUpdate,
            messagesToSave,
            payload.chat_ids_to_delete || [],
            [],
            transaction
        );

        // Correctly save the server_timestamp from the payload
        if (payload.server_timestamp) {
            // This should ideally be part of the same transaction if possible,
            // but userDB seems to be a separate class. For now, this is acceptable.
            await userDB.updateUserData({ last_sync_timestamp: payload.server_timestamp });
        }
        
    } catch (error) {
        console.error("[ChatSyncService:CoreSync] Error setting up delta_sync_data processing:", error);
        if (transaction && transaction.abort && !transaction.error) {
            try { transaction.abort(); } catch (abortError) { console.error("Error aborting transaction:", abortError); }
        }
        const errorMessage = error instanceof Error ? error.message : String(error);
        notificationStore.error(`Error processing server sync data: ${errorMessage}`);
        serviceInstance.isSyncing_FOR_HANDLERS_ONLY = false;
    }
}

export function handleInitialSyncErrorImpl(
    serviceInstance: ChatSynchronizationService,
    payload: { message: string }
): void {
    console.error("[ChatSyncService:CoreSync] Received initial_sync_error:", payload.message);
    notificationStore.error(`Chat sync failed: ${payload.message}`);
    serviceInstance.isSyncing_FOR_HANDLERS_ONLY = false;
    serviceInstance.initialSyncAttempted_FOR_HANDLERS_ONLY = false; // Allow retry
}

export async function handlePhase1LastChatImpl(
    serviceInstance: ChatSynchronizationService,
    payload: Phase1LastChatPayload
): Promise<void> {
    console.info("[ChatSyncService:CoreSync] Received phase_1_last_chat_ready for:", payload.chat_id);
    console.debug("[ChatSyncService:CoreSync] Phase 1 payload contains:", {
        chat_id: payload.chat_id,
        has_chat_details: !!payload.chat_details,
        messages_count: payload.messages?.length || 0,
        embeds_count: payload.embeds?.length || 0,
        suggestions_count: payload.new_chat_suggestions?.length || 0,
        already_synced: payload.already_synced
    });
    
    // Check if server indicated chat is already synced (version-aware optimization)
    if (payload.already_synced) {
        console.info(`[ChatSyncService:CoreSync] Phase 1: Chat ${payload.chat_id} already up-to-date on client. Skipping data save.`);
        // Still dispatch event so Chats.svelte knows Phase 1 is complete
        serviceInstance.dispatchEvent(new CustomEvent('phase_1_last_chat_ready', { detail: payload }));
        return;
    }
    
    // CRITICAL: According to sync.md, Phase 1 must save data to IndexedDB BEFORE opening chat
    // This ensures chat is available when Chats.svelte tries to load it
    try {
        // Save Phase 1 chat data to IndexedDB using a single transaction for atomicity
        if (payload.chat_details && payload.messages) {
            console.info("[ChatSyncService:CoreSync] Saving Phase 1 chat data to IndexedDB:", payload.chat_id);
            
            // CRITICAL FIX: Ensure chat_details has the chat_id field
            // The backend sends chat_id at payload root, but chat_details needs it too
            // Ensure all required Chat fields are present
            const chatWithId: Chat = {
                chat_id: payload.chat_id,
                encrypted_title: payload.chat_details.encrypted_title ?? null,
                messages_v: payload.chat_details.messages_v ?? 0,
                title_v: payload.chat_details.title_v ?? 0,
                draft_v: payload.chat_details.draft_v ?? 0,
                encrypted_draft_md: payload.chat_details.encrypted_draft_md ?? null,
                encrypted_draft_preview: payload.chat_details.encrypted_draft_preview ?? null,
                last_edited_overall_timestamp: payload.chat_details.last_edited_overall_timestamp ?? payload.chat_details.updated_at ?? Math.floor(Date.now() / 1000),
                unread_count: payload.chat_details.unread_count ?? 0,
                created_at: payload.chat_details.created_at ?? Math.floor(Date.now() / 1000),
                updated_at: payload.chat_details.updated_at ?? Math.floor(Date.now() / 1000),
                // Include optional fields
                encrypted_chat_key: payload.chat_details.encrypted_chat_key ?? null,
                encrypted_icon: payload.chat_details.encrypted_icon ?? null,
                encrypted_category: payload.chat_details.encrypted_category ?? null,
                is_shared: payload.chat_details.is_shared,
                is_private: payload.chat_details.is_private,
                ...payload.chat_details
            };
            
            // Use a single transaction for all Phase 1 writes (chat + messages) for instant availability
            await chatDB.init();
            const transaction = await chatDB.getTransaction(['chats', 'messages'], 'readwrite');
            
            // Store chat metadata in transaction
            await chatDB.addChat(chatWithId, transaction);
            
            // Store messages if provided
            if (payload.messages && payload.messages.length > 0) {
                console.info("[ChatSyncService:CoreSync] Saving", payload.messages.length, "Phase 1 messages");
                for (const messageData of payload.messages) {
                    // Parse JSON string if needed
                    let message = messageData;
                    if (typeof messageData === 'string') {
                        try {
                            message = JSON.parse(messageData);
                        } catch (e) {
                            console.error('[ChatSyncService:CoreSync] Failed to parse Phase 1 message JSON:', e);
                            continue;
                        }
                    }
                    
                    // DEFENSIVE: Validate message has required fields before saving
                    if (!message.message_id) {
                        console.error('[ChatSyncService:CoreSync] Message missing message_id, skipping:', message);
                        continue;
                    }
                    if (!message.chat_id) {
                        // Use chat_id from payload if missing
                        message.chat_id = payload.chat_id;
                    }
                    
                    await chatDB.saveMessage(message, transaction);
                }
            }
            
            // Wait for transaction to complete
            await new Promise<void>((resolve, reject) => {
                transaction.oncomplete = () => resolve();
                transaction.onerror = () => reject(transaction.error);
            });
            
            // CRITICAL FIX: Add delay after transaction to ensure IndexedDB has flushed to disk
            // Without this, getAllChats() called immediately after returns 0 chats!
            // 50ms ensures data is queryable across different transactions
            await new Promise(resolve => setTimeout(resolve, 50));
            
            console.info("[ChatSyncService:CoreSync] ✅ Phase 1 transaction completed - data is now immediately available in IndexedDB for chat:", payload.chat_id);
        }
        
        // CRITICAL: Save new chat suggestions to IndexedDB (Phase 1 ALWAYS includes suggestions)
        if (payload.new_chat_suggestions && payload.new_chat_suggestions.length > 0) {
            console.info("[ChatSyncService:CoreSync] Saving", payload.new_chat_suggestions.length, "new chat suggestions to IndexedDB");
            try {
                // Pass full NewChatSuggestion objects with IDs from server
                // Use 'global' as chatId when no specific chat is associated (e.g., "new" section)
                const chatIdForSuggestions = payload.chat_id || 'global';
                await chatDB.saveEncryptedNewChatSuggestions(payload.new_chat_suggestions, chatIdForSuggestions);
                console.info("[ChatSyncService:CoreSync] ✅ Successfully saved", payload.new_chat_suggestions.length, "suggestions to IndexedDB with IDs");
                
                // Dispatch event so NewChatSuggestions component can update
                serviceInstance.dispatchEvent(new CustomEvent('newChatSuggestionsReady', { 
                    detail: { suggestions: payload.new_chat_suggestions } 
                }));
            } catch (suggestionError) {
                console.error("[ChatSyncService:CoreSync] Error saving suggestions to IndexedDB:", suggestionError);
            }
        } else {
            console.warn("[ChatSyncService:CoreSync] ⚠️ No new chat suggestions received in Phase 1 - this is unexpected!");
        }
        
        // CRITICAL: Save embeds to EmbedStore (Phase 1 may include embeds for the chat)
        // This ensures embeds are available for rendering when messages are displayed
        // Embeds from sync are already client-encrypted, so we store them as-is (no re-encryption)
        console.debug("[ChatSyncService:CoreSync] Phase 1 payload embeds check:", {
            hasEmbeds: !!payload.embeds,
            embedsLength: payload.embeds?.length || 0,
            embedIds: payload.embeds?.map((e: SyncEmbed) => e.embed_id).slice(0, 5) || []
        });
        
        if (payload.embeds && payload.embeds.length > 0) {
            console.info("[ChatSyncService:CoreSync] Saving", payload.embeds.length, "embeds to EmbedStore");
            try {
                const { embedStore } = await import('./embedStore');
                
                for (const embed of payload.embeds) {
                    // Each embed should have: embed_id, encrypted_content, encrypted_type, status, etc.
                    if (!embed.embed_id) {
                        console.warn('[ChatSyncService:CoreSync] Embed missing embed_id, skipping:', embed);
                        continue;
                    }
                    
                    // Create contentRef in the format used by embeds: embed:{embed_id}
                    const contentRef = `embed:${embed.embed_id}`;
                    
                    // Store the embed with its already-encrypted content (no re-encryption)
                    // This matches the pattern used for messages during sync
                    await embedStore.putEncrypted(contentRef, {
                        encrypted_content: embed.encrypted_content, // Already client-encrypted from Directus
                        encrypted_type: embed.encrypted_type, // Already client-encrypted from Directus
                        embed_id: embed.embed_id,
                        status: embed.status || 'finished',
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
                        updatedAt: embed.updatedAt || embed.updated_at
                    }, (embed.encrypted_type ? 'app-skill-use' : embed.embed_type || 'app-skill-use') as EmbedType);
                }
                
                console.info("[ChatSyncService:CoreSync] ✅ Successfully saved", payload.embeds.length, "embeds to EmbedStore (as-is, no re-encryption)");
            } catch (embedError) {
                console.error("[ChatSyncService:CoreSync] Error saving embeds to EmbedStore:", embedError);
            }
        } else {
            console.debug("[ChatSyncService:CoreSync] No embeds in Phase 1 payload (chat may not have any)");
        }
        
        // CRITICAL: Save embed_keys to EmbedStore (needed to decrypt embed content)
        // Without embed_keys, embeds cannot be decrypted and will show errors
        if (payload.embed_keys && payload.embed_keys.length > 0) {
            console.info("[ChatSyncService:CoreSync] Saving", payload.embed_keys.length, "embed_keys to EmbedStore");
            try {
                const { embedStore } = await import('./embedStore');
                
                // Store all embed key entries
                await embedStore.storeEmbedKeys(payload.embed_keys);
                
                console.info("[ChatSyncService:CoreSync] ✅ Successfully saved", payload.embed_keys.length, "embed_keys to EmbedStore");
            } catch (embedKeyError) {
                console.error("[ChatSyncService:CoreSync] Error saving embed_keys to EmbedStore:", embedKeyError);
            }
        } else {
            console.debug("[ChatSyncService:CoreSync] No embed_keys in Phase 1 payload (embeds may not have keys yet)");
        }
        
        // CRITICAL FIX: Add delay to ensure ALL IndexedDB operations are queryable
        // This includes chat suggestions which use their own transaction
        await new Promise(resolve => setTimeout(resolve, 50));
    } catch (error) {
        console.error("[ChatSyncService:CoreSync] Error saving Phase 1 data to IndexedDB:", error);
    }
    
    // Now dispatch event so Chats.svelte can open the chat
    console.info("[ChatSyncService:CoreSync] Dispatching phase_1_last_chat_ready event with payload:", payload);
    serviceInstance.dispatchEvent(new CustomEvent('phase_1_last_chat_ready', { detail: payload }));
}

export function handleCachePrimedImpl(
    serviceInstance: ChatSynchronizationService,
    payload: CachePrimedPayload
): void {
    console.info("[ChatSyncService:CoreSync] Received cache_primed:", payload.status);
    if (payload.status === "full_sync_ready") {
        serviceInstance.cachePrimed_FOR_HANDLERS_ONLY = true;
        serviceInstance.dispatchEvent(new CustomEvent('cachePrimed'));
        if (!serviceInstance.isSyncing_FOR_HANDLERS_ONLY && !serviceInstance.initialSyncAttempted_FOR_HANDLERS_ONLY) {
             serviceInstance.attemptInitialSync_FOR_HANDLERS_ONLY();
        }
    }
}

export function handleCacheStatusResponseImpl(
    serviceInstance: ChatSynchronizationService,
    payload: CacheStatusResponsePayload
): void {
    console.info("[ChatSyncService:CoreSync] Received 'cache_status_response':", payload);
    
    // Validate required fields - no silent failures!
    if (typeof payload.is_primed !== 'boolean') {
        console.error("[ChatSyncService:CoreSync] CRITICAL: Missing or invalid 'is_primed' in cache_status_response:", payload);
        throw new Error("Invalid cache_status_response: missing 'is_primed'");
    }
    
    if (typeof payload.chat_count !== 'number') {
        console.error("[ChatSyncService:CoreSync] CRITICAL: Missing or invalid 'chat_count' in cache_status_response:", payload);
        throw new Error("Invalid cache_status_response: missing 'chat_count'");
    }
    
    if (typeof payload.timestamp !== 'number') {
        console.error("[ChatSyncService:CoreSync] CRITICAL: Missing or invalid 'timestamp' in cache_status_response:", payload);
        throw new Error("Invalid cache_status_response: missing 'timestamp'");
    }
    
    // Dispatch event to Chats component with validated payload
    serviceInstance.dispatchEvent(new CustomEvent('syncStatusResponse', {
        detail: {
            cache_primed: payload.is_primed,
            chat_count: payload.chat_count,
            timestamp: payload.timestamp
        }
    }));
    
    console.log("[ChatSyncService:CoreSync] Cache status check:", {
        is_primed: payload.is_primed,
        chat_count: payload.chat_count,
        cachePrimed_before: serviceInstance.cachePrimed_FOR_HANDLERS_ONLY,
        initialSyncAttempted: serviceInstance.initialSyncAttempted_FOR_HANDLERS_ONLY
    });
    
    if (payload.is_primed && !serviceInstance.cachePrimed_FOR_HANDLERS_ONLY) {
        console.log("[ChatSyncService:CoreSync] ✅ Cache is primed! Setting flag and attempting initial sync...");
        serviceInstance.cachePrimed_FOR_HANDLERS_ONLY = true;
        console.log("[ChatSyncService:CoreSync] Calling attemptInitialSync_FOR_HANDLERS_ONLY()...");
        serviceInstance.attemptInitialSync_FOR_HANDLERS_ONLY();
        console.log("[ChatSyncService:CoreSync] attemptInitialSync_FOR_HANDLERS_ONLY() call completed");
    } else if (payload.is_primed && serviceInstance.cachePrimed_FOR_HANDLERS_ONLY) {
        console.warn("[ChatSyncService:CoreSync] Cache primed but flag already set - sync may have already been attempted");
    } else {
        console.warn("[ChatSyncService:CoreSync] Cache not primed yet, waiting...");
    }
}

export async function handleChatContentBatchResponseImpl(
    serviceInstance: ChatSynchronizationService,
    payload: ChatContentBatchResponsePayload
): Promise<void> {
    console.info("[ChatSyncService:CoreSync] Received 'chat_content_batch_response':", payload);
    if (!payload.messages_by_chat_id || Object.keys(payload.messages_by_chat_id).length === 0) {
        return;
    }

    const chatIdsWithMessages = Object.keys(payload.messages_by_chat_id);
    let transaction: IDBTransaction | null = null;
    let updatedChatCount = 0;
    
    try {
        transaction = await chatDB.getTransaction(
            [chatDB['CHATS_STORE_NAME'], chatDB['MESSAGES_STORE_NAME']],
            'readwrite'
        );

        transaction.oncomplete = () => {
            if (updatedChatCount > 0) {
                // This event is not standard. Consider using 'chatUpdated' for each chat.
                // For now, keeping as is, but this could be improved.
                // serviceInstance.dispatchEvent(new CustomEvent('chatsUpdatedWithMessages', { detail: { chatIds: chatIdsWithMessages } }));
            }
        };
        
        for (const chatId of chatIdsWithMessages) {
            const messagesFromServer = payload.messages_by_chat_id[chatId] as ServerBatchMessageFormat[]; // Cast to ServerBatchMessageFormat[]
            if (messagesFromServer && messagesFromServer.length > 0) {
                for (const serverMsg of messagesFromServer) {
                    const messageToSave: Message = {
                        message_id: serverMsg.message_id,
                        chat_id: serverMsg.chat_id,
                        role: serverMsg.role,
                        created_at: serverMsg.created_at,
                        status: 'synced' as MessageStatus,
                        client_message_id: serverMsg.client_message_id, 
                        user_message_id: serverMsg.user_message_id,
                        // Only encrypted fields from server for device sync (zero-knowledge architecture)
                        encrypted_content: serverMsg.encrypted_content,
                        encrypted_sender_name: serverMsg.encrypted_sender_name,
                        encrypted_category: serverMsg.encrypted_category,
                        encrypted_model_name: serverMsg.encrypted_model_name,
                    };
                    await chatDB.saveMessage(messageToSave, transaction);
                }
                const chat = await chatDB.getChat(chatId, transaction);
                if (chat) {
                    chat.updated_at = Math.floor(Date.now() / 1000);
                    await chatDB.updateChat(chat, transaction);
                    updatedChatCount++;
                    serviceInstance.dispatchEvent(new CustomEvent('chatUpdated', { detail: { chat_id: chatId, messagesUpdated: true } }));
                }
            }
        }
    } catch (error) {
        console.error("[ChatSyncService:CoreSync] Error in handleChatContentBatchResponseImpl:", error);
        if (transaction && transaction.abort && !transaction.error) {
            try { transaction.abort(); } catch (abortError) { console.error("Error aborting transaction:", abortError); }
        }
        notificationStore.error("Error saving batch-fetched messages to local database.");
    }
}

export async function handleOfflineSyncCompleteImpl(
    serviceInstance: ChatSynchronizationService,
    payload: OfflineSyncCompletePayload
): Promise<void> {
    console.info("[ChatSyncService:CoreSync] Received offline_sync_complete:", payload);
    const changes = await chatDB.getOfflineChanges();
    let tx: IDBTransaction | null = null;
    try {
        tx = await chatDB.getTransaction(chatDB['OFFLINE_CHANGES_STORE_NAME'], 'readwrite');
        for (const change of changes) {
            await chatDB.deleteOfflineChange(change.change_id, tx);
        }
        tx.oncomplete = () => {
            if (payload.errors > 0) notificationStore.error(`Offline sync: ${payload.errors} changes could not be applied.`);
            if (payload.conflicts > 0) notificationStore.warning(`Offline sync: ${payload.conflicts} changes had conflicts.`);
            if (payload.errors === 0 && payload.conflicts === 0 && payload.processed > 0) notificationStore.success(`${payload.processed} offline changes synced.`);
            serviceInstance.dispatchEvent(new CustomEvent('offlineSyncProcessed', { detail: payload }));
        };
    } catch (error) {
        console.error("[ChatSyncService:CoreSync] Error in handleOfflineSyncCompleteImpl:", error);
        if (tx && tx.abort && !tx.error) {
            try { tx.abort(); } catch (abortError) { console.error("Error aborting transaction:", abortError); }
        }
    }
}
