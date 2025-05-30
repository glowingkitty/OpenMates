// frontend/packages/ui/src/services/chatSyncServiceHandlersCoreSync.ts
import type { ChatSynchronizationService } from './chatSyncService';
import { chatDB } from './db';
import { notificationStore } from '../stores/notificationStore';
import type {
    InitialSyncResponsePayload,
    PriorityChatReadyPayload,
    CachePrimedPayload,
    CacheStatusResponsePayload,
    ChatContentBatchResponsePayload,
    OfflineSyncCompletePayload,
    Chat,
    Message
} from '../types/chat';

export async function handleInitialSyncResponseImpl(
    serviceInstance: ChatSynchronizationService,
    payload: InitialSyncResponsePayload
): Promise<void> {
    console.info("[ChatSyncService:CoreSync] Received initial_sync_response:", payload);
    
    const transaction = chatDB.getTransaction(
        [chatDB['CHATS_STORE_NAME'], chatDB['MESSAGES_STORE_NAME']],
        'readwrite'
    );
    
    const chatsMetadataToUpdateInDB: Chat[] = [];
    const messagesToSaveInDB: Message[] = [];
    const chatIdsToFetchMessagesFor: string[] = [];

    transaction.oncomplete = () => {
        console.info("[ChatSyncService:CoreSync] Initial sync DB transaction complete.");
        (serviceInstance as any).serverChatOrder = payload.server_chat_order || [];
        serviceInstance.dispatchEvent(new CustomEvent('syncComplete', { detail: { serverChatOrder: (serviceInstance as any).serverChatOrder } }));
        (serviceInstance as any).isSyncing = false;

        if (chatIdsToFetchMessagesFor.length > 0) {
            console.info(`[ChatSyncService:CoreSync] Requesting messages for ${chatIdsToFetchMessagesFor.length} chats post initial sync.`);
            // Assuming requestChatContentBatch is a method on serviceInstance
            (serviceInstance as any).requestChatContentBatch(chatIdsToFetchMessagesFor);
        }
    };

    transaction.onerror = (event) => {
        console.error("[ChatSyncService:CoreSync] Error processing initial_sync_response transaction:", transaction.error, event);
        const errorMessage = transaction.error ? transaction.error.message : "Unknown DB transaction error";
        notificationStore.error(`Error processing server sync data: ${errorMessage}`);
        (serviceInstance as any).isSyncing = false;
    };

    try {
        if (payload.chats_to_add_or_update && payload.chats_to_add_or_update.length > 0) {
            for (const serverChatData of payload.chats_to_add_or_update) {
                const localChatMetadata = await chatDB.getChat(serverChatData.chat_id, transaction);
                
                const chatMetadataToSave: Chat = {
                    chat_id: serverChatData.chat_id,
                    title: serverChatData.title ?? localChatMetadata?.title ?? 'New Chat',
                    messages_v: serverChatData.versions.messages_v,
                    title_v: serverChatData.versions.title_v,
                    draft_v: serverChatData.versions.draft_v ?? localChatMetadata?.draft_v ?? 0,
                    draft_json: serverChatData.draft_json !== undefined ? serverChatData.draft_json : localChatMetadata?.draft_json,
                    last_edited_overall_timestamp: serverChatData.last_edited_overall_timestamp,
                    unread_count: serverChatData.unread_count ?? localChatMetadata?.unread_count ?? 0,
                    createdAt: localChatMetadata?.createdAt || new Date(serverChatData.last_edited_overall_timestamp * 1000),
                    updatedAt: new Date(serverChatData.last_edited_overall_timestamp * 1000),
                };
                chatsMetadataToUpdateInDB.push(chatMetadataToSave);

                if (serverChatData.messages && serverChatData.messages.length > 0) {
                    messagesToSaveInDB.push(...serverChatData.messages);
                } else if (!serverChatData.messages && localChatMetadata && serverChatData.versions.messages_v === localChatMetadata.messages_v) {
                    const localMessages = await chatDB.getMessagesForChat(localChatMetadata.chat_id, transaction);
                    localMessages.forEach(msg => {
                        if (msg.status === 'sending') {
                            messagesToSaveInDB.push({ ...msg, status: 'synced' as const });
                        }
                    });
                }

                if (serverChatData.versions.messages_v > 0 && (!serverChatData.messages || serverChatData.messages.length === 0)) {
                    const alreadyCorrected = messagesToSaveInDB.some(m => m.chat_id === serverChatData.chat_id && m.status === 'synced');
                    if (!alreadyCorrected) {
                       chatIdsToFetchMessagesFor.push(serverChatData.chat_id);
                    }
                }
            }
        }
        
        await chatDB.batchProcessChatData(
            chatsMetadataToUpdateInDB,
            messagesToSaveInDB,
            payload.chat_ids_to_delete || [],
            [], 
            transaction
        );
        
    } catch (error) {
        console.error("[ChatSyncService:CoreSync] Error preparing data for initial_sync_response transaction:", error);
        if (transaction && transaction.abort && !transaction.error) { 
            transaction.abort();
        }
        const errorMessage = error instanceof Error ? error.message : String(error);
        notificationStore.error(`Error processing server sync data: ${errorMessage}`);
        (serviceInstance as any).isSyncing = false; 
    }
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
        (serviceInstance as any).cachePrimed = true;
        serviceInstance.dispatchEvent(new CustomEvent('cachePrimed', { detail: payload }));
        if (!(serviceInstance as any).initialSyncAttempted || !(serviceInstance as any).isSyncing) {
             (serviceInstance as any).attemptInitialSync();
        }
    }
}

export function handleCacheStatusResponseImpl(
    serviceInstance: ChatSynchronizationService,
    payload: CacheStatusResponsePayload
): void {
    console.info("[ChatSyncService:CoreSync] Received 'cache_status_response':", payload);
    if (payload.is_primed && !(serviceInstance as any).cachePrimed) {
        (serviceInstance as any).cachePrimed = true;
        (serviceInstance as any).attemptInitialSync();
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
    const transaction = chatDB.getTransaction(
        [chatDB['CHATS_STORE_NAME'], chatDB['MESSAGES_STORE_NAME']],
        'readwrite'
    );
    let updatedChatCount = 0;

    transaction.oncomplete = () => {
        if (updatedChatCount > 0) {
            serviceInstance.dispatchEvent(new CustomEvent('chatsUpdatedWithMessages', { detail: { chatIds: chatIdsWithMessages } }));
        }
    };
    transaction.onerror = (event) => {
        notificationStore.error("Error saving batch-fetched messages to local database.");
    };
    
    try {
        for (const chatId of chatIdsWithMessages) {
            const messages = payload.messages_by_chat_id[chatId];
            if (messages && messages.length > 0) {
                for (const message of messages) {
                    await chatDB.saveMessage(message, transaction);
                }
                const chat = await chatDB.getChat(chatId, transaction);
                if (chat) {
                    chat.updatedAt = new Date();
                    // Optionally update chat.messages_v if server sends it in this payload
                    await chatDB.updateChat(chat, transaction);
                    updatedChatCount++;
                    serviceInstance.dispatchEvent(new CustomEvent('chatUpdated', { detail: { chat_id: chatId, messagesUpdated: true, chat } }));
                }
            }
        }
    } catch (error) {
        if (transaction && transaction.abort && !transaction.error) {
            transaction.abort();
        }
    }
}

export async function handleOfflineSyncCompleteImpl(
    serviceInstance: ChatSynchronizationService,
    payload: OfflineSyncCompletePayload
): Promise<void> {
    console.info("[ChatSyncService:CoreSync] Received offline_sync_complete:", payload);
    const changes = await chatDB.getOfflineChanges(); 
    const tx = chatDB.getTransaction(chatDB['OFFLINE_CHANGES_STORE_NAME'], 'readwrite');
    try {
        for (const change of changes) {
            await chatDB.deleteOfflineChange(change.change_id, tx);
        }
        tx.oncomplete = () => {
            // Notification logic based on payload
            if (payload.errors > 0) notificationStore.error(`Offline sync: ${payload.errors} changes could not be applied.`);
            if (payload.conflicts > 0) notificationStore.warning(`Offline sync: ${payload.conflicts} changes had conflicts.`);
            if (payload.errors === 0 && payload.conflicts === 0 && payload.processed > 0) notificationStore.success(`${payload.processed} offline changes synced.`);
            serviceInstance.dispatchEvent(new CustomEvent('offlineSyncProcessed', { detail: payload }));
        };
        tx.onerror = () => console.error("[ChatSyncService:CoreSync] Error clearing offline changes post-sync:", tx.error);
    } catch (error) {
        if (tx.abort && !tx.error) tx.abort();
    }
}
