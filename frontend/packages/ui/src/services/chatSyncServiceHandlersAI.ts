// frontend/packages/ui/src/services/chatSyncServiceHandlersAI.ts
import type { ChatSynchronizationService } from './chatSyncService';
import { aiTypingStore } from '../stores/aiTypingStore';
import { chatDB } from './db'; // Import chatDB
import type {
    Chat, // Import Chat type
    AITaskInitiatedPayload,
    AIMessageUpdatePayload,
    AITypingStartedPayload,
    AIMessageReadyPayload,
    AITaskCancelRequestedPayload
} from '../types/chat'; // Assuming these types might be moved or are already in a shared types file

// --- AI Task and Stream Event Handler Implementations ---

export function handleAITaskInitiatedImpl(
    serviceInstance: ChatSynchronizationService,
    payload: AITaskInitiatedPayload
): void {
    console.info("[ChatSyncService:AI] Received 'ai_task_initiated':", payload);
    // Accessing private member, ensure 'this' context is correct or pass necessary state/methods
    (serviceInstance as any).activeAITasks.set(payload.chat_id, { taskId: payload.ai_task_id, userMessageId: payload.user_message_id });
    serviceInstance.dispatchEvent(new CustomEvent('aiTaskInitiated', { detail: payload }));
}

export function handleAIMessageUpdateImpl(
    serviceInstance: ChatSynchronizationService,
    payload: AIMessageUpdatePayload
): void {
    console.debug("[ChatSyncService:AI] Received 'ai_message_update':", payload);
    serviceInstance.dispatchEvent(new CustomEvent('aiMessageChunk', { detail: payload }));
    if (payload.is_final_chunk) {
        const taskInfo = (serviceInstance as any).activeAITasks.get(payload.chat_id);
        if (taskInfo && taskInfo.taskId === payload.task_id) {
            (serviceInstance as any).activeAITasks.delete(payload.chat_id);
            // Clear typing status for this specific AI task
            aiTypingStore.clearTyping(payload.chat_id, payload.task_id); 
            serviceInstance.dispatchEvent(new CustomEvent('aiTaskEnded', { detail: { chatId: payload.chat_id, taskId: payload.task_id, status: payload.interrupted_by_revocation ? 'cancelled' : (payload.interrupted_by_soft_limit ? 'timed_out' : 'completed') } }));
            console.info(`[ChatSyncService:AI] AI Task ${payload.task_id} for chat ${payload.chat_id} considered ended due to final chunk marker. Typing status cleared.`);
        }
    }
}

export async function handleAITypingStartedImpl( // Changed to async
    serviceInstance: ChatSynchronizationService,
    payload: AITypingStartedPayload
): Promise<void> { // Added Promise<void>
    console.debug("[ChatSyncService:AI] Received 'ai_typing_started':", payload);
    
    // Update aiTypingStore first
    aiTypingStore.setTyping(payload.chat_id, payload.user_message_id, payload.message_id, payload.category, payload.model_name);

    // Handle title update if present in payload
    if (payload.title) {
        console.info(`[ChatSyncService:AI] 'ai_typing_started' includes title: '${payload.title}' for chat ${payload.chat_id}. Updating DB.`);
        let tx;
        try {
            tx = await chatDB.getTransaction([chatDB['CHATS_STORE_NAME']], 'readwrite');
            const chat = await chatDB.getChat(payload.chat_id, tx);
            let chatToUpdate = await chatDB.getChat(payload.chat_id, tx);
            let chatWasModified = false;

            if (!chatToUpdate) {
                console.warn(`[ChatSyncService:AI] Chat ${payload.chat_id} not found in DB. Creating new chat from 'ai_typing_started' payload.`);
                
                chatToUpdate = {
                    chat_id: payload.chat_id,
                    title: payload.title || null, // Store cleartext in memory
                    encrypted_title: null, // Will be set when saving to IndexedDB
                    title_v: payload.title ? 1 : 0,
                    messages_v: 0,
                    draft_v: 0,
                    encrypted_draft_md: null,
                    last_edited_overall_timestamp: Math.floor(Date.now() / 1000),
                    unread_count: 0,
                    mates: payload.category ? [payload.category] : [],
                    created_at: Math.floor(Date.now() / 1000),
                    updated_at: Math.floor(Date.now() / 1000),
                };
                chatWasModified = true; // New chat is a modification
            } else {
                // Update title if it's different (store cleartext in memory)
                if (payload.title && chatToUpdate.title !== payload.title) {
                    chatToUpdate.title = payload.title; // Store cleartext in memory
                    chatToUpdate.title_v = (chatToUpdate.title_v || 0) + 1;
                    chatWasModified = true;
                    console.debug(`[ChatSyncService:AI] Chat ${payload.chat_id} title updated to '${payload.title}', version ${chatToUpdate.title_v}.`);
                } else if (payload.title) {
                    console.debug(`[ChatSyncService:AI] Chat ${payload.chat_id} title is already '${payload.title}'. No DB update needed for title field.`);
                }

                // Update mates if category is present and different from last mate
                if (payload.category) {
                    const currentMates = chatToUpdate.mates || [];
                    if (currentMates.length === 0 || currentMates[currentMates.length - 1] !== payload.category) {
                        // Add or replace the last mate with the new category.
                        // For simplicity, let's assume we just set/replace the mates array if a new category comes.
                        // A more sophisticated approach might involve appending or managing multiple mates.
                        // Based on current Chat.svelte logic (displayMate = chat.mates[chat.mates.length - 1]),
                        // just ensuring the latest category is present (perhaps as the only one) is fine.
                        chatToUpdate.mates = [payload.category];
                        chatWasModified = true;
                        console.debug(`[ChatSyncService:AI] Chat ${payload.chat_id} mates updated with category '${payload.category}'.`);
                    }
                }
            }

            if (chatWasModified) {
                chatToUpdate.updated_at = Math.floor(Date.now() / 1000);
                await chatDB.addChat(chatToUpdate, tx); // addChat handles create or update
                console.info(`[ChatSyncService:AI] Chat ${payload.chat_id} saved to DB with updates from 'ai_typing_started'.`);
            }
            
            tx.oncomplete = () => {
                console.debug(`[ChatSyncService:AI] Transaction for 'ai_typing_started' (chat ${payload.chat_id}) completed.`);
                serviceInstance.dispatchEvent(new CustomEvent('chatUpdated', { detail: { chat_id: payload.chat_id, type: 'title_from_ai_typing' } }));
                serviceInstance.dispatchEvent(new CustomEvent('aiTypingStarted', { detail: payload }));
            };
            tx.onerror = (err) => {
                console.error(`[ChatSyncService:AI] Transaction error updating title for chat ${payload.chat_id} from 'ai_typing_started':`, tx.error, err);
                serviceInstance.dispatchEvent(new CustomEvent('aiTypingStarted', { detail: payload }));
            };

        } catch (error) {
            console.error(`[ChatSyncService:AI] Error updating chat title for ${payload.chat_id} from 'ai_typing_started':`, error);
            if (tx && (tx as any).abort && !(tx as any).error) { 
                try { (tx as any).abort(); } catch (abortError) { console.error("Error aborting transaction:", abortError); }
            }
            serviceInstance.dispatchEvent(new CustomEvent('aiTypingStarted', { detail: payload }));
        }
    } else {
        serviceInstance.dispatchEvent(new CustomEvent('aiTypingStarted', { detail: payload }));
    }
}

export function handleAITypingEndedImpl(
    serviceInstance: ChatSynchronizationService,
    payload: { chat_id: string, message_id: string }
): void {
    console.debug("[ChatSyncService:AI] Received 'ai_typing_ended':", payload);
    aiTypingStore.clearTyping(payload.chat_id, payload.message_id);
    serviceInstance.dispatchEvent(new CustomEvent('aiTypingEnded', { detail: payload }));
}

export function handleAIMessageReadyImpl(
    serviceInstance: ChatSynchronizationService,
    payload: AIMessageReadyPayload
): void {
    console.debug("[ChatSyncService:AI] Received 'ai_message_ready':", payload);
    serviceInstance.dispatchEvent(new CustomEvent('aiMessageCompletedOnServer', { detail: payload }));
    const taskInfo = (serviceInstance as any).activeAITasks.get(payload.chat_id);
    if (taskInfo && taskInfo.taskId === payload.message_id) {
        (serviceInstance as any).activeAITasks.delete(payload.chat_id);
        serviceInstance.dispatchEvent(new CustomEvent('aiTaskEnded', { detail: { chatId: payload.chat_id, taskId: payload.message_id, status: 'completed' } }));
        console.info(`[ChatSyncService:AI] AI Task ${payload.message_id} for chat ${payload.chat_id} considered ended due to 'ai_message_ready'.`);
    }
}

export function handleAITaskCancelRequestedImpl(
    serviceInstance: ChatSynchronizationService,
    payload: AITaskCancelRequestedPayload
): void {
    console.info("[ChatSyncService:AI] Received 'ai_task_cancel_requested' acknowledgement:", payload);
    serviceInstance.dispatchEvent(new CustomEvent('aiTaskCancellationAcknowledged', { detail: payload }));
    
    if (payload.status === 'already_completed' || payload.status === 'not_found') {
        const chatIdsToClear: string[] = [];
        (serviceInstance as any).activeAITasks.forEach((value: { taskId: string; }, key: string) => {
            if (value.taskId === payload.task_id) {
                chatIdsToClear.push(key);
            }
        });
        chatIdsToClear.forEach(chatId => {
            (serviceInstance as any).activeAITasks.delete(chatId);
            serviceInstance.dispatchEvent(new CustomEvent('aiTaskEnded', { detail: { chatId: chatId, taskId: payload.task_id, status: payload.status } }));
            console.info(`[ChatSyncService:AI] AI Task ${payload.task_id} for chat ${chatId} cleared due to cancel ack status: ${payload.status}.`);
        });
    }
}
