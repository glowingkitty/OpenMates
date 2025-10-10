// frontend/packages/ui/src/services/chatSyncServiceHandlersAI.ts
import type { ChatSynchronizationService } from './chatSyncService';
import { aiTypingStore } from '../stores/aiTypingStore';
import { chatDB } from './db'; // Import chatDB
import type {
    Chat, // Import Chat type
    Message,
    AITaskInitiatedPayload,
    AIMessageUpdatePayload,
    AIBackgroundResponseCompletedPayload,
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

/**
 * Handles background AI response completion for inactive chats.
 * This allows AI processing to continue when user switches chats,
 * storing the completed response in IndexedDB for later retrieval.
 */
export async function handleAIBackgroundResponseCompletedImpl(
    serviceInstance: ChatSynchronizationService,
    payload: AIBackgroundResponseCompletedPayload
): Promise<void> {
    console.info("[ChatSyncService:AI] Received 'ai_background_response_completed' for inactive chat:", payload);
    
    try {
        // Get chat from DB to update messages_v
        const chat = await chatDB.getChat(payload.chat_id);
        if (!chat) {
            console.error(`[ChatSyncService:AI] Chat ${payload.chat_id} not found in DB for background response`);
            return;
        }
        
        // Get the category from typing store if available
        const typingStatus = aiTypingStore.get();
        const category = (typingStatus?.chatId === payload.chat_id) ? typingStatus.category : undefined;
        
        // Create the completed AI message
        // CRITICAL: Store AI response as markdown string, not Tiptap JSON
        // Tiptap JSON is only for UI rendering, never stored in database
        const aiMessage: Message = {
            message_id: payload.message_id,
            chat_id: payload.chat_id,
            user_message_id: payload.user_message_id,
            role: 'assistant',
            category: category || undefined,
            content: payload.full_content, // Store as markdown string, not Tiptap JSON
            status: 'synced',
            created_at: Math.floor(Date.now() / 1000),
            // Required encrypted fields (will be populated by encryptMessageFields)
            encrypted_content: '', // Will be set by encryption
            encrypted_category: undefined
        };
        
        // Save message to IndexedDB (encryption handled by chatDB)
        await chatDB.saveMessage(aiMessage);
        console.info(`[ChatSyncService:AI] Saved background AI response to DB for chat ${payload.chat_id}`);
        
        // Update chat metadata with new messages_v
        const newMessagesV = (chat.messages_v || 0) + 1;
        const newLastEdited = Math.floor(Date.now() / 1000);
        const updatedChat: Chat = {
            ...chat,
            messages_v: newMessagesV,
            last_edited_overall_timestamp: newLastEdited
        };
        await chatDB.updateChat(updatedChat);
        console.info(`[ChatSyncService:AI] Updated chat ${payload.chat_id} metadata: messages_v=${newMessagesV}`);
        
        // Clear AI task tracking
        const taskInfo = (serviceInstance as any).activeAITasks.get(payload.chat_id);
        if (taskInfo && taskInfo.taskId === payload.task_id) {
            (serviceInstance as any).activeAITasks.delete(payload.chat_id);
            console.info(`[ChatSyncService:AI] Cleared active AI task for chat ${payload.chat_id}`);
        }
        
        // Clear typing status for this specific AI task
        aiTypingStore.clearTyping(payload.chat_id, payload.task_id);
        
        // Dispatch chatUpdated event to notify UI (e.g., update chat list)
        // This will NOT update ActiveChat if the chat is not currently open
        serviceInstance.dispatchEvent(new CustomEvent('chatUpdated', {
            detail: {
                chat_id: payload.chat_id,
                chat: updatedChat,
                newMessage: aiMessage,
                type: 'background_ai_completion'
            }
        }));
        
        // Dispatch aiTaskEnded event for cleanup
        serviceInstance.dispatchEvent(new CustomEvent('aiTaskEnded', {
            detail: {
                chatId: payload.chat_id,
                taskId: payload.task_id,
                status: payload.interrupted_by_revocation ? 'cancelled' : (payload.interrupted_by_soft_limit ? 'timed_out' : 'completed')
            }
        }));
        
        console.info(`[ChatSyncService:AI] Background AI response processing completed for chat ${payload.chat_id}`);
        
        // CRITICAL: Send encrypted AI response back to server for Directus storage (zero-knowledge architecture)
        // This uses the existing sendCompletedAIResponse method
        try {
            console.debug('[ChatSyncService:AI] Sending completed background AI response to server for encrypted Directus storage:', {
                messageId: aiMessage.message_id,
                chatId: aiMessage.chat_id,
                contentLength: aiMessage.content?.length || 0
            });
            await (serviceInstance as any).sendCompletedAIResponse(aiMessage);
        } catch (error) {
            console.error('[ChatSyncService:AI] Error sending completed background AI response to server:', error);
        }
        
    } catch (error) {
        console.error(`[ChatSyncService:AI] Error handling background AI response for chat ${payload.chat_id}:`, error);
    }
}

export async function handleAITypingStartedImpl( // Changed to async
    serviceInstance: ChatSynchronizationService,
    payload: AITypingStartedPayload
): Promise<void> { // Added Promise<void>
    console.debug("[ChatSyncService:AI] Received 'ai_typing_started':", payload);
    
    // Update aiTypingStore first
    aiTypingStore.setTyping(payload.chat_id, payload.user_message_id, payload.message_id, payload.category, payload.model_name);

    // DUAL-PHASE ARCHITECTURE: Handle metadata encryption if provided
    if (payload.title || payload.category) {
        console.info(`[ChatSyncService:AI] DUAL-PHASE: Processing metadata encryption for chat ${payload.chat_id}:`, {
            hasTitle: !!payload.title,
            category: payload.category
        });
        
        try {
            // FIRST: Update local chat with encrypted title immediately
            // Get the current chat
            const chat = await chatDB.getChat(payload.chat_id);
            if (!chat) {
                console.error(`[ChatSyncService:AI] Chat ${payload.chat_id} not found for metadata encryption`);
                return;
            }
            
            // Encrypt title with chat-specific key for local storage
            let encryptedTitle: string | null = null;
            if (payload.title) {
                // Get or generate chat key for encryption
                const chatKey = chatDB.getOrGenerateChatKey(payload.chat_id);
                
                // Import chat-specific encryption function
                const { encryptWithChatKey } = await import('./cryptoService');
                encryptedTitle = encryptWithChatKey(payload.title, chatKey);
                if (!encryptedTitle) {
                    console.error(`[ChatSyncService:AI] Failed to encrypt title for chat ${payload.chat_id}`);
                    return;
                }
            }
            
            // Update local chat with encrypted metadata
            try {
                const chatToUpdate = await chatDB.getChat(payload.chat_id);
                if (chatToUpdate) {
                    // Update chat with encrypted title
                    if (encryptedTitle) {
                        chatToUpdate.encrypted_title = encryptedTitle;
                        chatToUpdate.title_v = (chatToUpdate.title_v || 0) + 1; // Frontend increments title_v
                        console.info(`[ChatSyncService:AI] Updating chat ${payload.chat_id} with encrypted title, version: ${chatToUpdate.title_v}`);
                    }
                    
                    // Ensure chat key is stored for decryption
                    const chatKey = chatDB.getOrGenerateChatKey(payload.chat_id);
                    const encryptedChatKey = await import('./cryptoService').then(m => m.encryptChatKeyWithMasterKey(chatKey));
                    if (encryptedChatKey) {
                        chatToUpdate.encrypted_chat_key = encryptedChatKey;
                        console.info(`[ChatSyncService:AI] Stored encrypted chat key for chat ${payload.chat_id}`);
                    }
                    
                    // Update timestamps
                    chatToUpdate.updated_at = Math.floor(Date.now() / 1000);
                    
                    await chatDB.updateChat(chatToUpdate);
                    
                    console.info(`[ChatSyncService:AI] Local chat ${payload.chat_id} updated with encrypted title and chat key`);
                    serviceInstance.dispatchEvent(new CustomEvent('chatUpdated', { 
                        detail: { chat_id: payload.chat_id, type: 'title_updated', chat: chatToUpdate } 
                    }));
                } else {
                    console.error(`[ChatSyncService:AI] Chat ${payload.chat_id} not found for title update`);
                    return;
                }
            } catch (error) {
                console.error(`[ChatSyncService:AI] Error updating local chat ${payload.chat_id}:`, error);
                return;
            }
            
            // SECOND: Send encrypted storage package to server
            const { sendEncryptedStoragePackage } = await import('./chatSyncServiceSenders');
            
            // Get the user's pending message (the one being processed)
            const messages = await chatDB.getMessagesForChat(payload.chat_id);
            const userMessage = messages
                .filter(m => m.role === 'user')
                .sort((a, b) => b.created_at - a.created_at)[0];
                
            if (!userMessage) {
                console.error(`[ChatSyncService:AI] No user message found for chat ${payload.chat_id} to encrypt`);
                return;
            }
            
            // Get the updated chat object (chatToUpdate has the incremented title_v)
            const updatedChat = await chatDB.getChat(payload.chat_id);
            if (!updatedChat) {
                console.error(`[ChatSyncService:AI] Updated chat ${payload.chat_id} not found for sending to server`);
                return;
            }
            
            // Send encrypted storage package with metadata
            await sendEncryptedStoragePackage(serviceInstance, {
                chat_id: payload.chat_id,
                plaintext_title: payload.title, // Use title directly
                plaintext_category: payload.category, // Use category directly
                user_message: userMessage,
                task_id: payload.task_id,
                updated_chat: updatedChat  // Pass the updated chat object with incremented title_v
            });
            
            console.info(`[ChatSyncService:AI] DUAL-PHASE: Sent encrypted storage package for chat ${payload.chat_id}`);
            
        } catch (error) {
            console.error(`[ChatSyncService:AI] DUAL-PHASE: Error processing metadata encryption for chat ${payload.chat_id}:`, error);
        }
    } else {
        console.info(`[ChatSyncService:AI] 'ai_typing_started' for chat ${payload.chat_id}. No metadata to encrypt.`);
    }
    
    serviceInstance.dispatchEvent(new CustomEvent('aiTypingStarted', { detail: payload }));
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

/**
 * Handle AI response storage confirmation from server
 * This confirms that the encrypted AI response has been stored in Directus
 */
export function handleAIResponseStorageConfirmedImpl(
    serviceInstance: ChatSynchronizationService,
    payload: { chat_id: string; message_id: string; task_id?: string }
): void {
    console.info("[ChatSyncService:AI] Received 'ai_response_storage_confirmed':", payload);
    
    // Dispatch event to notify components that AI response storage is confirmed
    serviceInstance.dispatchEvent(new CustomEvent('aiResponseStorageConfirmed', { 
        detail: { 
            chatId: payload.chat_id, 
            messageId: payload.message_id,
            taskId: payload.task_id 
        } 
    }));
    
    console.debug(`[ChatSyncService:AI] AI response storage confirmed for message ${payload.message_id} in chat ${payload.chat_id}`);
}

/**
 * Handles the 'encrypted_metadata_stored' event from the server.
 * This confirms that encrypted chat metadata has been successfully stored on the server.
 */
export function handleEncryptedMetadataStoredImpl(
    serviceInstance: ChatSynchronizationService,
    payload: { chat_id: string; message_id: string; task_id?: string }
): void {
    console.debug(`[ChatSyncService:AI] Received 'encrypted_metadata_stored':`, payload);
    console.debug(`[ChatSyncService:AI] Encrypted metadata storage confirmed for chat ${payload.chat_id}`);
}
