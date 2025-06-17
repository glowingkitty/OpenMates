// frontend/packages/ui/src/services/chatSyncServiceHandlersCoreSync.ts
import type { ChatSynchronizationService } from './chatSyncService';
import { chatDB } from './db';
import { userDB } from './userDB';
import { notificationStore } from '../stores/notificationStore';
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
    MessageStatus // Added MessageStatus for status type
} from '../types/chat';

// Define the structure of messages as they come from the server in the batch
interface ServerMessageFormat {
    id: string;
    chat_id: string;
    role: MessageRole;
    content: TiptapJSON;
    created_at: number;
    category?: string;
    client_message_id?: string;
    user_message_id?: string;
    // Add any other fields that might come from the server message
}

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

        const chatsToUpdate: Chat[] = payload.chats_to_add_or_update.map(serverChat => {
            const chat: Chat = {
                chat_id: serverChat.chat_id,
                title: serverChat.title,
                messages_v: serverChat.versions.messages_v,
                title_v: serverChat.versions.title_v,
                draft_v: serverChat.versions.draft_v,
                draft_json: serverChat.draft_json,
                last_edited_overall_timestamp: serverChat.last_edited_overall_timestamp,
                unread_count: serverChat.unread_count,
                createdAt: new Date(serverChat.last_edited_overall_timestamp * 1000),
                updatedAt: new Date(serverChat.last_edited_overall_timestamp * 1000),
            };
            return chat;
        });

        const messagesToSave: Message[] = payload.chats_to_add_or_update.flatMap(chat => chat.messages || []);

        await chatDB.batchProcessChatData(
            chatsToUpdate,
            messagesToSave,
            payload.chat_ids_to_delete || [],
            [],
            transaction
        );

        // Correctly save the server_timestamp from the payload
        if (payload.server_timestamp) {
            await userDB.updateUserData({ last_sync_timestamp: payload.server_timestamp });
        }

        transaction.oncomplete = () => {
            console.info("[ChatSyncService:CoreSync] Delta sync DB transaction complete.");
            serviceInstance.dispatchEvent(new CustomEvent('syncComplete'));
            (serviceInstance as any).isSyncing = false;
        };
        
    } catch (error) {
        console.error("[ChatSyncService:CoreSync] Error in delta_sync_data processing:", error);
        if (transaction && transaction.abort && !transaction.error && transaction.error !== error) {
            try { transaction.abort(); } catch (abortError) { console.error("Error aborting transaction:", abortError); }
        }
        const errorMessage = error instanceof Error ? error.message : String(error);
        notificationStore.error(`Error processing server sync data: ${errorMessage}`);
    (serviceInstance as any).isSyncing = false;
    }
}

export function handleInitialSyncErrorImpl(
    serviceInstance: ChatSynchronizationService,
    payload: { message: string }
): void {
    console.error("[ChatSyncService:CoreSync] Received initial_sync_error:", payload.message);
    notificationStore.error(`Chat sync failed: ${payload.message}`);
    (serviceInstance as any).isSyncing = false;
    (serviceInstance as any).initialSyncAttempted = false; // Allow retry
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
    let transaction: IDBTransaction | null = null;
    let updatedChatCount = 0;
    
    try {
        transaction = await chatDB.getTransaction(
            [chatDB['CHATS_STORE_NAME'], chatDB['MESSAGES_STORE_NAME']],
            'readwrite'
        );

        transaction.oncomplete = () => {
            if (updatedChatCount > 0) {
                serviceInstance.dispatchEvent(new CustomEvent('chatsUpdatedWithMessages', { detail: { chatIds: chatIdsWithMessages } }));
            }
        };
        // transaction.onerror handled by outer catch

        for (const chatId of chatIdsWithMessages) {
            const messagesFromServer = payload.messages_by_chat_id[chatId] as ServerMessageFormat[]; // Cast to ServerMessageFormat[]
            if (messagesFromServer && messagesFromServer.length > 0) {
                for (const serverMsg of messagesFromServer) {
                    // Map server message structure to local Message type
                    const messageToSave: Message = {
                        message_id: serverMsg.id, // Use serverMsg.id
                        chat_id: serverMsg.chat_id,
                        role: serverMsg.role, // Role should already be of type MessageRole via ServerMessageFormat
                        content: serverMsg.content,
                        timestamp: serverMsg.created_at, // Use serverMsg.created_at
                        status: 'synced' as MessageStatus, // Messages from batch are considered synced
                        category: serverMsg.category,
                        client_message_id: serverMsg.client_message_id, 
                        user_message_id: serverMsg.user_message_id,
                        // Ensure all required fields of Message type are present
                    };
                    await chatDB.saveMessage(messageToSave, transaction);
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
        console.error("[ChatSyncService:CoreSync] Error in handleChatContentBatchResponseImpl:", error);
        if (transaction && transaction.abort && !transaction.error && transaction.error !== error) {
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
            // Notification logic based on payload
            if (payload.errors > 0) notificationStore.error(`Offline sync: ${payload.errors} changes could not be applied.`);
            if (payload.conflicts > 0) notificationStore.warning(`Offline sync: ${payload.conflicts} changes had conflicts.`);
            if (payload.errors === 0 && payload.conflicts === 0 && payload.processed > 0) notificationStore.success(`${payload.processed} offline changes synced.`);
            serviceInstance.dispatchEvent(new CustomEvent('offlineSyncProcessed', { detail: payload }));
        };
        // tx.onerror handled by outer catch
    } catch (error) {
        console.error("[ChatSyncService:CoreSync] Error in handleOfflineSyncCompleteImpl:", error);
        if (tx && tx.abort && !tx.error && tx.error !== error) {
            try { tx.abort(); } catch (abortError) { console.error("Error aborting transaction:", abortError); }
        }
    }
}
