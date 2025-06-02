// frontend/packages/ui/src/services/chatSyncServiceHandlersChatUpdates.ts
import type { ChatSynchronizationService } from './chatSyncService';
import { chatDB } from './db';
import type {
    ChatTitleUpdatedPayload,
    ChatDraftUpdatedPayload,
    ChatMessageReceivedPayload,
    ChatMessageConfirmedPayload,
    ChatDeletedPayload,
    Message,
    Chat,
    TiptapJSON
} from '../types/chat';

export async function handleChatTitleUpdatedImpl(
    serviceInstance: ChatSynchronizationService,
    payload: ChatTitleUpdatedPayload
): Promise<void> {
    console.info("[ChatSyncService:ChatUpdates] Received chat_title_updated:", payload);
    let tx: IDBTransaction | null = null;
    try {
        tx = await chatDB.getTransaction(chatDB['CHATS_STORE_NAME'], 'readwrite');
        const chat = await chatDB.getChat(payload.chat_id, tx);
        if (chat) {
            chat.title = payload.data.title;
            chat.title_v = payload.versions.title_v;
            chat.updatedAt = new Date();
            await chatDB.updateChat(chat, tx);
            
            tx.oncomplete = () => {
                serviceInstance.dispatchEvent(new CustomEvent('chatUpdated', { detail: { chat_id: payload.chat_id } }));
            };
            // tx.onerror is handled by the catch block for the transaction promise or by the outer catch
        } else {
            // If chat not found, the transaction might not need to proceed or could be aborted.
            // Depending on desired logic, tx.abort() could be called here.
            // For now, let it complete or rely on outer catch.
        }
    } catch (error) {
        console.error("[ChatSyncService:ChatUpdates] Error in handleChatTitleUpdated:", error);
        if (tx && tx.abort && !tx.error && tx.error !== error) { // Check if tx exists and error is not already from tx
            try { tx.abort(); } catch (abortError) { console.error("Error aborting transaction:", abortError); }
        }
    }
}

export async function handleChatDraftUpdatedImpl(
    serviceInstance: ChatSynchronizationService,
    payload: ChatDraftUpdatedPayload
): Promise<void> {
    console.info("[ChatSyncService:ChatUpdates] Received chat_draft_updated:", payload);
    let tx: IDBTransaction | null = null;
    try {
        tx = await chatDB.getTransaction(chatDB['CHATS_STORE_NAME'], 'readwrite');
        const chat = await chatDB.getChat(payload.chat_id, tx);
        if (chat) {
            console.debug(`[ChatSyncService:ChatUpdates] Existing chat ${payload.chat_id} found for draft update. Local draft_v: ${chat.draft_v}, Incoming draft_v: ${payload.versions.draft_v}.`);
            chat.draft_json = payload.data.draft_json;
            chat.draft_v = payload.versions.draft_v;
            chat.last_edited_overall_timestamp = payload.last_edited_overall_timestamp;
            chat.updatedAt = new Date();
            await chatDB.updateChat(chat, tx);
        } else {
            console.warn(`[ChatSyncService:ChatUpdates] Chat ${payload.chat_id} not found when handling chat_draft_updated broadcast. Creating new chat entry for draft.`);
            const newChatForDraft: Chat = {
                chat_id: payload.chat_id,
                title: '', 
                messages_v: 0,
                title_v: 0,
                draft_json: payload.data.draft_json,
                draft_v: payload.versions.draft_v,
                last_edited_overall_timestamp: payload.last_edited_overall_timestamp,
                unread_count: 0,
                createdAt: new Date(payload.last_edited_overall_timestamp * 1000),
                updatedAt: new Date(payload.last_edited_overall_timestamp * 1000),
            };
            await chatDB.addChat(newChatForDraft, tx);
        }

        tx.oncomplete = () => {
            console.info(`[ChatSyncService:ChatUpdates] Transaction for handleChatDraftUpdated (chat_id: ${payload.chat_id}) completed successfully.`);
            serviceInstance.dispatchEvent(new CustomEvent('chatUpdated', { detail: { chat_id: payload.chat_id, type: 'draft' } }));
        };
        // tx.onerror handled by outer catch or transaction promise rejection

    } catch (error) {
        console.error(`[ChatSyncService:ChatUpdates] Error in handleChatDraftUpdated (outer catch) for chat_id ${payload.chat_id}:`, error);
        if (tx && tx.abort && !tx.error && tx.error !== error) {
             try { tx.abort(); } catch (abortError) { console.error("Error aborting transaction:", abortError); }
        }
    }
}

export async function handleChatMessageReceivedImpl(
    serviceInstance: ChatSynchronizationService,
    payload: ChatMessageReceivedPayload
): Promise<void> {
    console.info("[ChatSyncService:ChatUpdates] Received chat_message_added (broadcast from server for other users/AI):", payload);
    const incomingMessage = payload.message as Message;
    let tx: IDBTransaction | null = null;

    const taskInfo = serviceInstance.activeAITasks.get(payload.chat_id);
    if (incomingMessage.role === 'assistant' && taskInfo && taskInfo.taskId === incomingMessage.message_id) {
        serviceInstance.activeAITasks.delete(payload.chat_id);
        serviceInstance.dispatchEvent(new CustomEvent('aiTaskEnded', { detail: { chatId: payload.chat_id, taskId: taskInfo.taskId, status: 'completed_message_received' } }));
        console.info(`[ChatSyncService:ChatUpdates] AI Task ${taskInfo.taskId} for chat ${payload.chat_id} considered ended as full AI message was received.`);
    }

    try {
        tx = await chatDB.getTransaction([chatDB['CHATS_STORE_NAME'], chatDB['MESSAGES_STORE_NAME']], 'readwrite');
        // Ensure incomingMessage has a chat_id. If not, use the payload's chat_id.
        // This is crucial for AI messages that might arrive without chat_id embedded in the message object itself.
        if (!incomingMessage.chat_id && payload.chat_id) {
            console.warn(`[ChatSyncService:ChatUpdates] handleChatMessageReceivedImpl: incomingMessage (role: ${incomingMessage.role}, id: ${incomingMessage.message_id}) was missing chat_id. Populating from payload.chat_id: ${payload.chat_id}`);
            incomingMessage.chat_id = payload.chat_id;
        } else if (incomingMessage.chat_id !== payload.chat_id) {
            console.warn(`[ChatSyncService:ChatUpdates] handleChatMessageReceivedImpl: incomingMessage.chat_id (${incomingMessage.chat_id}) differs from payload.chat_id (${payload.chat_id}). Using payload.chat_id for consistency with chat context.`);
            incomingMessage.chat_id = payload.chat_id;
        }
        
        await chatDB.saveMessage(incomingMessage, tx);
        const chat = await chatDB.getChat(payload.chat_id, tx);
        if (chat) {
            chat.messages_v = payload.versions.messages_v;
            chat.last_edited_overall_timestamp = payload.last_edited_overall_timestamp;
            chat.updatedAt = new Date();
            await chatDB.updateChat(chat, tx);

            tx.oncomplete = () => {
                serviceInstance.dispatchEvent(new CustomEvent('chatUpdated', { detail: { chat_id: payload.chat_id, newMessage: incomingMessage, chat } }));
            };
            // tx.onerror handled by outer catch
        } else {
            console.warn(`[ChatSyncService:ChatUpdates] Chat ${payload.chat_id} not found for incoming message.`);
            // if (tx.abort) tx.abort(); // tx might be null if getTransaction failed
        }
    } catch (error) {
        console.error("[ChatSyncService:ChatUpdates] Error in handleChatMessageReceived:", error);
        if (tx && tx.abort && !tx.error && tx.error !== error) {
            try { tx.abort(); } catch (abortError) { console.error("Error aborting transaction:", abortError); }
        }
    }
}

export async function handleChatMessageConfirmedImpl(
    serviceInstance: ChatSynchronizationService,
    payload: ChatMessageConfirmedPayload
): Promise<void> {
    console.info("[ChatSyncService:ChatUpdates] Received chat_message_confirmed for this client's message:", payload);
    let tx: IDBTransaction | null = null;
    try {
        tx = await chatDB.getTransaction([chatDB['CHATS_STORE_NAME'], chatDB['MESSAGES_STORE_NAME']], 'readwrite');
        const messageToUpdate = await chatDB.getMessage(payload.message_id, tx);

        if (messageToUpdate) {
            // Ensure the message belongs to the correct chat, though this should be guaranteed by message_id uniqueness
            if (messageToUpdate.chat_id === payload.chat_id) {
                messageToUpdate.status = 'synced';
                await chatDB.saveMessage(messageToUpdate, tx);
            } else {
                console.warn(`[ChatSyncService:ChatUpdates] Confirmed message (id: ${payload.message_id}) found, but belongs to chat ${messageToUpdate.chat_id} instead of expected ${payload.chat_id}.`);
            }
        } else {
            console.warn(`[ChatSyncService:ChatUpdates] Confirmed message (id: ${payload.message_id}) not found in local DB for chat ${payload.chat_id}.`);
        }

        const chat = await chatDB.getChat(payload.chat_id, tx);
        if (chat) {
            chat.messages_v = payload.new_messages_v;
            chat.last_edited_overall_timestamp = payload.new_last_edited_overall_timestamp;
            chat.updatedAt = new Date();
            await chatDB.updateChat(chat, tx);

            tx.oncomplete = () => {
                serviceInstance.dispatchEvent(new CustomEvent('messageStatusChanged', {
                    detail: {
                        chatId: payload.chat_id,
                        messageId: payload.message_id,
                        status: 'synced',
                        chat
                    }
                }));
                serviceInstance.dispatchEvent(new CustomEvent('chatUpdated', {
                    detail: {
                        chat_id: payload.chat_id,
                        chat
                    }
                }));
            };
            // tx.onerror handled by outer catch
        } else {
            console.warn(`[ChatSyncService:ChatUpdates] Chat ${payload.chat_id} not found for message confirmation.`);
            // if (tx.abort && !tx.error) tx.abort(); // tx might be null
        }
    } catch (error) {
        console.error("[ChatSyncService:ChatUpdates] Error in handleChatMessageConfirmed:", error);
        if (tx && tx.abort && !tx.error && tx.error !== error) {
            try { tx.abort(); } catch (abortError) { console.error("Error aborting transaction:", abortError); }
        }
    }
}

export async function handleChatDeletedImpl(
    serviceInstance: ChatSynchronizationService,
    payload: ChatDeletedPayload
): Promise<void> {
    console.info("[ChatSyncService:ChatUpdates] Received chat_deleted:", payload);
    if (payload.tombstone) {
        try {
            await chatDB.deleteChat(payload.chat_id);
            serviceInstance.dispatchEvent(new CustomEvent('chatDeleted', { detail: { chat_id: payload.chat_id } }));
        } catch (error) {
            console.error("[ChatSyncService:ChatUpdates] Error in handleChatDeleted (calling chatDB.deleteChat):", error);
        }
    }
}
