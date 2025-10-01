// frontend/packages/ui/src/services/chatSyncServiceHandlersCoreSync.ts
import type { ChatSynchronizationService } from './chatSyncService';
import { chatDB } from './db';
import { userDB } from './userDB';
import { notificationStore } from '../stores/notificationStore';
import { decryptWithMasterKey } from './cryptoService';
import type {
    InitialSyncResponsePayload,
    PriorityChatReadyPayload,
    CachePrimedPayload,
    CacheStatusResponsePayload,
    ChatContentBatchResponsePayload,
    OfflineSyncCompletePayload,
    Chat,
    Message,
    TiptapJSON, // Added TiptapJSON for content type
    MessageRole, // Added MessageRole for role type
    MessageStatus, // Added MessageStatus for status type
    ServerBatchMessageFormat
} from '../types/chat';

export async function handleInitialSyncResponseImpl(
    serviceInstance: ChatSynchronizationService,
    payload: InitialSyncResponsePayload
): Promise<void> {
    console.info("[ChatSyncService:CoreSync] Received initial_sync_response (delta_sync_data):", payload);
    let transaction: IDBTransaction | null = null;
    
    try {
        transaction = await chatDB.getTransaction(
            [chatDB['CHATS_STORE_NAME'], chatDB['MESSAGES_STORE_NAME']],
            'readwrite'
        );

        // Set the oncomplete handler BEFORE queueing operations
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

        // Process chats with async decryption
        const chatsToUpdate: Chat[] = await Promise.all(payload.chats_to_add_or_update.map(async (serverChat) => {
            // Decrypt encrypted title from server for in-memory use using chat-specific key
            let cleartextTitle: string | null = null;
            if (serverChat.encrypted_title) {
                // Get chat key for decryption
                const chatKey = chatDB.getChatKey(serverChat.chat_id);
                if (chatKey) {
                    const { decryptWithChatKey } = await import('./cryptoService');
                    cleartextTitle = decryptWithChatKey(serverChat.encrypted_title, chatKey);
                } else {
                    console.warn(`[ChatSyncService:CoreSync] No chat key found for chat ${serverChat.chat_id}, cannot decrypt title`);
                    cleartextTitle = serverChat.encrypted_title; // Fallback to encrypted content if decryption fails
                }
                if (!cleartextTitle) {
                    console.warn(`[ChatSyncService:CoreSync] Failed to decrypt title for chat ${serverChat.chat_id}`);
                    cleartextTitle = serverChat.encrypted_title; // Fallback to encrypted content if decryption fails
                }
            }
            
            const chat: Chat = {
                chat_id: serverChat.chat_id,
                encrypted_title: serverChat.encrypted_title,
                messages_v: serverChat.versions.messages_v,
                title_v: serverChat.versions.title_v,
                draft_v: serverChat.versions.draft_v,
                encrypted_draft_md: serverChat.encrypted_draft_md,
                encrypted_draft_preview: serverChat.encrypted_draft_preview,
                last_edited_overall_timestamp: serverChat.last_edited_overall_timestamp,
                unread_count: serverChat.unread_count,
                created_at: serverChat.created_at,
                updated_at: serverChat.updated_at,
            };
            return chat;
        }));

        const messagesToSave: Message[] = payload.chats_to_add_or_update.flatMap(chat =>
            (chat.messages || []).map(msg => ({
                ...msg,
                message_id: (msg as any).id || msg.message_id, // Handle missing message_id
            }))
        );

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

export function handlePriorityChatReadyImpl(
    serviceInstance: ChatSynchronizationService,
    payload: PriorityChatReadyPayload
): void {
    console.info("[ChatSyncService:CoreSync] Received priority_chat_ready for:", payload.chat_id);
    serviceInstance.dispatchEvent(new CustomEvent('priorityChatReady', { detail: payload }));
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
    
    // Dispatch event to Chats component with full payload
    serviceInstance.dispatchEvent(new CustomEvent('syncStatusResponse', {
        detail: {
            cache_primed: payload.is_primed,
            chat_count: 0, // We don't have chat count in cache_status_response
            timestamp: Date.now()
        }
    }));
    
    if (payload.is_primed && !serviceInstance.cachePrimed_FOR_HANDLERS_ONLY) {
        serviceInstance.cachePrimed_FOR_HANDLERS_ONLY = true;
        serviceInstance.attemptInitialSync_FOR_HANDLERS_ONLY();
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
