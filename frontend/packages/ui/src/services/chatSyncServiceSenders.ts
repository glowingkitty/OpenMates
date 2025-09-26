// frontend/packages/ui/src/services/chatSyncServiceSenders.ts
import type { ChatSynchronizationService } from './chatSyncService';
import { chatDB } from './db';
import { webSocketService } from './websocketService';
import { notificationStore } from '../stores/notificationStore';
import { get } from 'svelte/store';
import { websocketStatus } from '../stores/websocketStatusStore';
import { encryptWithMasterKey } from './cryptoService';
import type {
    TiptapJSON,
    Message,
    OfflineChange,
    // Payloads for sending messages
    UpdateTitlePayload,
    UpdateDraftPayload,
    DeleteDraftPayload,
    DeleteChatPayload,
    SendChatMessagePayload,
    SetActiveChatPayload,
    CancelAITaskPayload,
    SyncOfflineChangesPayload // Assuming this is used by a sender method if sendOfflineChanges is moved
} from '../types/chat'; // Adjust path as necessary

// Note: The actual payload interface definitions for client-to-server messages
// (like UpdateTitlePayload, etc.) are currently still in chatSyncService.ts.
// They might be moved to types/chat.ts for better organization if desired.

export async function sendUpdateTitleImpl(
    serviceInstance: ChatSynchronizationService,
    chat_id: string,
    new_title: string
): Promise<void> {
    // Encrypt title for server storage/syncing
    const encryptedTitle = encryptWithMasterKey(new_title);
    if (!encryptedTitle) {
        notificationStore.error('Failed to encrypt title - master key not available');
        return;
    }
    
    const payload: UpdateTitlePayload = { chat_id, encrypted_title: encryptedTitle };
    const tx = await chatDB.getTransaction(chatDB['CHATS_STORE_NAME'], 'readwrite');
    try {
        const chat = await chatDB.getChat(chat_id, tx);
        if (chat) {
            // Update encrypted title and version
            chat.encrypted_title = encryptedTitle;
            chat.title_v = (chat.title_v || 0) + 1;
            chat.updated_at = Math.floor(Date.now() / 1000);
            await chatDB.updateChat(chat, tx); // This will encrypt for IndexedDB storage
            tx.oncomplete = () => {
                serviceInstance.dispatchEvent(new CustomEvent('chatUpdated', { detail: { chat_id } }));
            };
            tx.onerror = () => console.error("[ChatSyncService:Senders] Error in sendUpdateTitle optimistic transaction:", tx.error);
        } else {
            if(tx.abort) tx.abort();
        }
    } catch (error) {
        console.error("[ChatSyncService:Senders] Error in sendUpdateTitle optimistic update:", error);
        if (tx.abort && !tx.error) tx.abort();
    }
    await webSocketService.sendMessage('update_title', payload);
}

export async function sendUpdateDraftImpl(
    serviceInstance: ChatSynchronizationService,
    chat_id: string,
    draft_content: string | null,
    draft_preview?: string | null
): Promise<void> {
    // NOTE: draft_content and draft_preview here are ENCRYPTED for secure server transmission
    // Local database saving with encrypted content should have already occurred in draftSave.ts
    const payload: UpdateDraftPayload = { 
        chat_id, 
        encrypted_draft_md: draft_content,
        encrypted_draft_preview: draft_preview
    };
    
    // Send encrypted draft to server for synchronization
    await webSocketService.sendMessage('update_draft', payload);
    
    console.debug(`[ChatSyncService:Senders] Sent encrypted draft update to server for chat ${chat_id}`, {
        hasDraftContent: !!draft_content,
        hasPreview: !!draft_preview
    });
}

export async function sendDeleteDraftImpl(
    serviceInstance: ChatSynchronizationService,
    chat_id: string
): Promise<void> {
    const payload: DeleteDraftPayload = { chatId: chat_id };
    try {
        const chatBeforeClear = await chatDB.getChat(chat_id);
        const versionBeforeEdit = chatBeforeClear?.draft_v || 0;
        const clearedDraftChat = await chatDB.clearCurrentUserChatDraft(chat_id);
        if (clearedDraftChat) {
            serviceInstance.dispatchEvent(new CustomEvent('chatUpdated', { detail: { chat_id, type: 'draft_deleted', chat: clearedDraftChat } }));
        }
        if (get(websocketStatus).status === 'connected') {
            await webSocketService.sendMessage('delete_draft', payload);
        } else {
            const offlineChange: Omit<OfflineChange, 'change_id'> = {
                chat_id: chat_id,
                type: 'delete_draft',
                value: null,
                version_before_edit: versionBeforeEdit,
            };
            await (serviceInstance as any).queueOfflineChange(offlineChange); // queueOfflineChange might need to be public or passed
        }
    } catch (error) {
        const errorMessage = error instanceof Error ? error.message : String(error);
        notificationStore.error(`Failed to delete draft: ${errorMessage}`);
    }
}

export async function sendDeleteChatImpl(
    serviceInstance: ChatSynchronizationService,
    chat_id: string
): Promise<void> {
    const payload: DeleteChatPayload = { chatId: chat_id };
    // Create transaction with both CHATS_STORE_NAME and MESSAGES_STORE_NAME since deleteChat needs both
    const tx = await chatDB.getTransaction([chatDB['CHATS_STORE_NAME'], chatDB['MESSAGES_STORE_NAME']], 'readwrite');
    try {
        await chatDB.deleteChat(chat_id, tx);
        tx.oncomplete = () => {
            serviceInstance.dispatchEvent(new CustomEvent('chatDeleted', { detail: { chat_id } }));
        };
        tx.onerror = () => console.error("[ChatSyncService:Senders] Error in sendDeleteChat optimistic transaction:", tx.error);
    } catch (error) {
        console.error("[ChatSyncService:Senders] Error in sendDeleteChat optimistic update:", error);
        if (tx.abort && !tx.error) tx.abort();
    }
    await webSocketService.sendMessage('delete_chat', payload);
}

export async function sendNewMessageImpl(
    serviceInstance: ChatSynchronizationService,
    message: Message
): Promise<void> {
    if (!(serviceInstance as any).webSocketConnected) { // Accessing private member
        console.warn("[ChatSyncService:Senders] WebSocket not connected. Message saved locally.");
        return;
    }
    
    // DUAL-PHASE ARCHITECTURE - Phase 1: Send ONLY plaintext for AI processing
    // Encrypted data will be sent separately after preprocessing completes via chat_metadata_for_encryption event
    
    // Phase 1 payload: ONLY fields needed for AI processing
    const payload = { 
        chat_id: message.chat_id, 
        message: {
            message_id: message.message_id,
            role: message.role,
            content: message.content, // ONLY plaintext for AI processing
            created_at: message.created_at,
            sender_name: message.sender_name // Include for cache but not critical for AI
            // NO category or encrypted fields - those go to Phase 2
        }
    };
    
    console.debug('[ChatSyncService:Senders] Phase 1: Sending plaintext-only message for AI processing:', {
        messageId: message.message_id,
        chatId: message.chat_id,
        hasPlaintextContent: !!message.content
    });
    
    try {
        await webSocketService.sendMessage('chat_message_added', payload);
    } catch (error) {
        console.error(`[ChatSyncService:Senders] Error sending 'chat_message_added' for message_id: ${message.message_id}:`, error);
        try {
            const existingMessage = await chatDB.getMessage(message.message_id);
            let messageToSave: Message;

            if (existingMessage) {
                // Ensure we are updating the correct message if found
                if (existingMessage.chat_id !== message.chat_id) {
                     console.warn(`[ChatSyncService:Senders] Message ${message.message_id} found in DB but with different chat_id (${existingMessage.chat_id}) than expected (${message.chat_id}). Using original message data.`);
                     messageToSave = { ...message, status: 'failed' as const };
                } else {
                    messageToSave = { ...existingMessage, status: 'failed' as const };
                }
            } else {
                // If not found in DB (e.g., was never saved or deleted), use the original message object
                console.warn(`[ChatSyncService:Senders] Message ${message.message_id} not found in DB during error handling. Saving original with 'failed' status.`);
                messageToSave = { ...message, status: 'failed' as const };
            }
            
            await chatDB.saveMessage(messageToSave);
            serviceInstance.dispatchEvent(new CustomEvent('messageStatusChanged', {
                detail: { chatId: messageToSave.chat_id, messageId: messageToSave.message_id, status: 'failed' }
            }));
        } catch (dbError) {
            console.error(`[ChatSyncService:Senders] Error updating message status to 'failed' in DB for ${message.message_id}:`, dbError);
        }
    }
}

export async function sendCompletedAIResponseImpl(
    serviceInstance: ChatSynchronizationService,
    aiMessage: Message
): Promise<void> {
    if (!(serviceInstance as any).webSocketConnected) { // Accessing private member
        console.warn("[ChatSyncService:Senders] WebSocket not connected. AI response not sent to server.");
        return;
    }
    
    // For completed AI responses, we only send encrypted content for Directus storage
    // The server should NOT process this as a new message or trigger AI processing
    
    // Get the chat to access the chat key for encryption
    const chat = await chatDB.getChat(aiMessage.chat_id);
    if (!chat) {
        console.error(`[ChatSyncService:Senders] Chat ${aiMessage.chat_id} not found for AI response encryption`);
        return;
    }
    
    // Encrypt the completed AI response for storage
    const encryptedFields = chatDB.getEncryptedFields(aiMessage, aiMessage.chat_id);
    
    // Create payload with ONLY encrypted content (no plaintext to avoid triggering AI processing)
    const payload = { 
        chat_id: aiMessage.chat_id, 
        message: {
            message_id: aiMessage.message_id,
            chat_id: aiMessage.chat_id,
            role: aiMessage.role, // 'assistant'
            created_at: aiMessage.created_at,
            status: aiMessage.status,
            user_message_id: aiMessage.user_message_id,
            // ONLY encrypted fields - no plaintext content
            encrypted_content: encryptedFields.encrypted_content,
            encrypted_category: encryptedFields.encrypted_category
        }
    };
    
    console.debug('[ChatSyncService:Senders] Sending completed AI response for Directus storage:', {
        messageId: aiMessage.message_id,
        chatId: aiMessage.chat_id,
        hasEncryptedContent: !!encryptedFields.encrypted_content,
        role: aiMessage.role
    });
    
    try {
        // Use a different event type to avoid triggering AI processing
        await webSocketService.sendMessage('ai_response_completed', payload);
    } catch (error) {
        console.error(`[ChatSyncService:Senders] Error sending completed AI response for message_id: ${aiMessage.message_id}:`, error);
    }
}

export async function sendSetActiveChatImpl(
    serviceInstance: ChatSynchronizationService,
    chatId: string | null
): Promise<void> {
    if (!(serviceInstance as any).webSocketConnected) {
        console.warn("[ChatSyncService:Senders] WebSocket not connected. Cannot send 'set_active_chat'.");
        return;
    }
    const payload: SetActiveChatPayload = { chat_id: chatId };
    try {
        await webSocketService.sendMessage('set_active_chat', payload);
    } catch (error) {
        console.error(`[ChatSyncService:Senders] Error sending 'set_active_chat' for chat_id: ${chatId}:`, error);
    }
}

export async function sendCancelAiTaskImpl(
    serviceInstance: ChatSynchronizationService,
    taskId: string
): Promise<void> {
    if (!(serviceInstance as any).webSocketConnected) {
        notificationStore.error("Cannot cancel AI task: Not connected to server.");
        return;
    }
    if (!taskId) return;
    const payload: CancelAITaskPayload = { task_id: taskId };
    try {
        await webSocketService.sendMessage('cancel_ai_task', payload);
    } catch (error) {
        notificationStore.error("Failed to send AI task cancellation request.");
    }
}

export async function queueOfflineChangeImpl(
    serviceInstance: ChatSynchronizationService,
    change: Omit<OfflineChange, 'change_id'>
): Promise<void> {
    const fullChange: OfflineChange = { ...change, change_id: crypto.randomUUID() };
    await chatDB.addOfflineChange(fullChange);
    notificationStore.info(`Change saved offline. Will sync when reconnected.`, 3000);
}

export async function sendOfflineChangesImpl(
    serviceInstance: ChatSynchronizationService
): Promise<void> {
    if (get(websocketStatus).status !== 'connected') {
        console.warn("[ChatSyncService:Senders] Cannot send offline changes, WebSocket not connected.");
        return;
    }
    const changes = await chatDB.getOfflineChanges();
    if (changes.length === 0) return;
    notificationStore.info(`Attempting to sync ${changes.length} offline change(s)...`);
    const payload: SyncOfflineChangesPayload = { changes };
    await webSocketService.sendMessage('sync_offline_changes', payload);
}

/**
 * Send encrypted storage package - Dual-Phase Architecture Phase 2
 * Encrypts user data (user message, title, category) and sends to server for storage
 * AI responses are handled separately via ai_response_completed event
 */
export async function sendEncryptedStoragePackage(
    serviceInstance: ChatSynchronizationService,
    data: {
        chat_id: string;
        plaintext_title?: string;
        plaintext_category?: string;
        user_message: Message;
        task_id?: string;
    }
): Promise<void> {
    if (!(serviceInstance as any).webSocketConnected) {
        console.warn("[ChatSyncService:Senders] Cannot send encrypted storage package, WebSocket not connected.");
        return;
    }

    try {
        const { chat_id, plaintext_title, plaintext_category, user_message, task_id } = data;
        
        // Get chat object for version info
        const chat = await chatDB.getChat(chat_id);
        if (!chat) {
            console.error(`[ChatSyncService:Senders] Chat ${chat_id} not found for encrypted storage`);
            return;
        }
        
        // Get or generate chat key for encryption
        const chatKey = chatDB.getOrGenerateChatKey(chat_id);
        
        // Get encrypted chat key for server storage
        const encryptedChatKey = await chatDB.getEncryptedChatKey(chat_id);
        
        // Import encryption functions
        const { encryptWithChatKey, encryptWithMasterKey } = await import('./cryptoService');
        
        // Encrypt user message content
        const encryptedUserContent = user_message.content 
            ? (typeof user_message.content === 'string' 
                ? encryptWithChatKey(user_message.content, chatKey)
                : encryptWithChatKey(JSON.stringify(user_message.content), chatKey))
            : null;
        
        // Encrypt user message metadata
        const encryptedUserSenderName = user_message.sender_name 
            ? encryptWithChatKey(user_message.sender_name, chatKey) 
            : null;
        const encryptedUserCategory = plaintext_category 
            ? encryptWithChatKey(plaintext_category, chatKey) 
            : null;
        
        // AI response is handled separately - not part of immediate storage
        
        // Encrypt title with master key (for chat-level metadata)
        const encryptedTitle = plaintext_title 
            ? encryptWithMasterKey(plaintext_title)
            : null;
        
        // Create encrypted metadata payload for new handler
        const metadataPayload = {
            chat_id,
            // User message fields
            message_id: user_message.message_id,
            encrypted_content: encryptedUserContent,
            encrypted_sender_name: encryptedUserSenderName,
            encrypted_category: encryptedUserCategory,
            created_at: user_message.created_at,
            // Chat metadata fields from preprocessing
            encrypted_title: encryptedTitle,
            encrypted_chat_key: encryptedChatKey,
            // Version info - get actual values or fail
            versions: {
                messages_v: chat.messages_v || 0,
                last_edited_overall_timestamp: user_message.created_at
            },
            task_id
        };
        
        console.info('[ChatSyncService:Senders] Sending encrypted chat metadata:', {
            chatId: chat_id,
            hasEncryptedTitle: !!encryptedTitle,
            hasEncryptedUserMessage: !!encryptedUserContent,
            taskId: task_id
        });
        
        // Send to server via new encrypted_chat_metadata handler
        await webSocketService.sendMessage('encrypted_chat_metadata', metadataPayload);
        
    } catch (error) {
        console.error('[ChatSyncService:Senders] Error sending encrypted storage package:', error);
    }
}
