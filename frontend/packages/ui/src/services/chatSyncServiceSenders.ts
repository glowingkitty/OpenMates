// frontend/packages/ui/src/services/chatSyncServiceSenders.ts
import type { ChatSynchronizationService } from './chatSyncService';
import { chatDB } from './db';
import { webSocketService } from './websocketService';
import { notificationStore } from '../stores/notificationStore';
import { get } from 'svelte/store';
import { websocketStatus } from '../stores/websocketStatusStore';
import { encryptWithMasterKey } from './cryptoService';
import type {
    Chat,
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
    // Get or generate chat key for encryption
    const chatKey = chatDB.getOrGenerateChatKey(chat_id);
    
    // Import chat-specific encryption function
    const { encryptWithChatKey } = await import('./cryptoService');
    
    // Encrypt title with chat-specific key for server storage/syncing
    const encryptedTitle = encryptWithChatKey(new_title, chatKey);
    if (!encryptedTitle) {
        notificationStore.error('Failed to encrypt title - chat key not available');
        return;
    }
    
    const payload: UpdateTitlePayload = { chat_id, encrypted_title: encryptedTitle };
    const tx = await chatDB.getTransaction(chatDB['CHATS_STORE_NAME'], 'readwrite');
    try {
        const chat = await chatDB.getChat(chat_id, tx);
        if (chat) {
            // Update encrypted title and version
            chat.encrypted_title = encryptedTitle;
            chat.title_v = (chat.title_v || 0) + 1; // Frontend increments title_v
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

/**
 * Send delete chat request to server
 * NOTE: The actual deletion from IndexedDB should be done by the caller (e.g., Chat.svelte)
 * before calling this function. This function only handles server communication.
 * NOTE: The chatDeleted event is now dispatched by the caller (Chat.svelte) after IndexedDB deletion
 * to ensure proper UI update timing.
 */
export async function sendDeleteChatImpl(
    serviceInstance: ChatSynchronizationService,
    chat_id: string
): Promise<void> {
    const payload: DeleteChatPayload = { chatId: chat_id };
    
    try {
        // Send delete request to server
        console.debug(`[ChatSyncService:Senders] Sending delete_chat request to server for chat ${chat_id}`);
        await webSocketService.sendMessage('delete_chat', payload);
        console.debug(`[ChatSyncService:Senders] Delete request sent successfully for chat ${chat_id}`);
        
        // NOTE: chatDeleted event is now dispatched by Chat.svelte after IndexedDB deletion
        // to ensure proper UI update timing. No need to dispatch it here.
    } catch (error) {
        console.error(`[ChatSyncService:Senders] Error sending delete_chat request for chat ${chat_id}:`, error);
        throw error; // Re-throw so caller can handle the error
    }
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
    
    // CRITICAL: Determine if this is a NEW chat or FOLLOW-UP message
    // Check if chat has existing messages (messages_v > 1, since current message is #1 for new chats)
    // NOT just encrypted_title, because title generation might have been skipped/failed
    const chat = await chatDB.getChat(message.chat_id);
    const chatHasMessages = (chat?.messages_v ?? 0) > 1; // > 1 because current message will be message #1
    
    console.debug(`[ChatSyncService:Senders] Chat has existing messages: ${chatHasMessages} (messages_v: ${chat?.messages_v}) - ${chatHasMessages ? 'FOLLOW-UP' : 'NEW CHAT'}`);
    
    // Phase 1 payload: ONLY fields needed for AI processing
    const payload = {
        chat_id: message.chat_id,
        message: {
            message_id: message.message_id,
            role: message.role,
            content: message.content, // ONLY plaintext for AI processing
            created_at: message.created_at,
            sender_name: message.sender_name, // Include for cache but not critical for AI
            chat_has_title: chatHasMessages // ZERO-KNOWLEDGE: Send true if chat has messages (follow-up), false if new
            // NO category or encrypted fields - those go to Phase 2
            // NO message_history - server will request if cache is stale
        }
    };
    
    console.debug('[ChatSyncService:Senders] Phase 1: Sending plaintext-only message for AI processing:', {
        messageId: message.message_id,
        chatId: message.chat_id,
        hasPlaintextContent: !!message.content,
        chatHasMessages: chatHasMessages,
        messagesV: chat?.messages_v
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
    
    // For completed AI responses, we send encrypted content + updated messages_v for Directus storage
    // The server should NOT process this as a new message or trigger AI processing
    
    // Get the chat to access the chat key for encryption and to increment messages_v
    const chat = await chatDB.getChat(aiMessage.chat_id);
    if (!chat) {
        console.error(`[ChatSyncService:Senders] Chat ${aiMessage.chat_id} not found for AI response encryption`);
        return;
    }
    
    // Increment messages_v for the AI response (client-side versioning, same as user messages)
    const newMessagesV = (chat.messages_v || 1) + 1;
    const newLastEdited = aiMessage.created_at;
    
    // Update chat in IndexedDB with new version
    const updatedChat = {
        ...chat,
        messages_v: newMessagesV,
        last_edited_overall_timestamp: newLastEdited,
        updated_at: Math.floor(Date.now() / 1000)
    };
    
    try {
        await chatDB.addChat(updatedChat);
        console.debug(`[ChatSyncService:Senders] Incremented messages_v for chat ${chat.chat_id}: ${chat.messages_v} → ${newMessagesV}`);
    } catch (error) {
        console.error(`[ChatSyncService:Senders] Failed to update chat messages_v:`, error);
        return;
    }
    
    // Encrypt the completed AI response for storage
    const encryptedFields = chatDB.getEncryptedFields(aiMessage, aiMessage.chat_id);
    
    // Create payload with encrypted content AND version info (like user messages)
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
        },
        // Version info for chat update (matches user message pattern)
        versions: {
            messages_v: newMessagesV,
            last_edited_overall_timestamp: newLastEdited
        }
    };
    
    console.debug('[ChatSyncService:Senders] Sending completed AI response for Directus storage:', {
        messageId: aiMessage.message_id,
        chatId: aiMessage.chat_id,
        hasEncryptedContent: !!encryptedFields.encrypted_content,
        role: aiMessage.role,
        newMessagesV: newMessagesV
    });
    
    try {
        // Use a different event type to avoid triggering AI processing
        await webSocketService.sendMessage('ai_response_completed', payload);
        
        // Dispatch event so UI knows chat was updated
        serviceInstance.dispatchEvent(new CustomEvent('chatUpdated', { 
            detail: { chat_id: chat.chat_id, chat: updatedChat } 
        }));
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
        plaintext_icon?: string;
        user_message: Message;
        task_id?: string;
        updated_chat?: Chat;  // Optional pre-fetched chat with updated versions
    }
): Promise<void> {
    if (!(serviceInstance as any).webSocketConnected) {
        console.warn("[ChatSyncService:Senders] Cannot send encrypted storage package, WebSocket not connected.");
        return;
    }

    try {
        const { chat_id, plaintext_title, plaintext_category, plaintext_icon, user_message, task_id, updated_chat } = data;
        
        // Get chat object for version info - use provided chat or fetch from DB
        const chat = updated_chat || await chatDB.getChat(chat_id);
        if (!chat) {
            console.error(`[ChatSyncService:Senders] Chat ${chat_id} not found for encrypted storage`);
            return;
        }
        
        console.debug(`[ChatSyncService:Senders] Using chat with title_v: ${chat.title_v}, messages_v: ${chat.messages_v}`);
        
        // Get or generate chat key for encryption
        const chatKey = chatDB.getOrGenerateChatKey(chat_id);
        
        // Get encrypted chat key for server storage
        const encryptedChatKey = await chatDB.getEncryptedChatKey(chat_id);
        
        // Import encryption functions
        const { encryptWithChatKey } = await import('./cryptoService');
        
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
        
        // Encrypt title with chat-specific key (for chat-level metadata)
        const encryptedTitle = plaintext_title 
            ? encryptWithChatKey(plaintext_title, chatKey)
            : null;
        
        // Encrypt icon with chat-specific key (for chat-level metadata)
        const encryptedIcon = plaintext_icon 
            ? encryptWithChatKey(plaintext_icon, chatKey)
            : null;
        
        // Encrypt category with chat-specific key (for chat-level metadata)
        const encryptedCategory = plaintext_category 
            ? encryptWithChatKey(plaintext_category, chatKey)
            : null;
        
        // Create encrypted metadata payload for new handler
        // CRITICAL: Only include metadata fields if they're actually set (not null)
        // For follow-up messages, metadata fields should be undefined/null and NOT included
        const metadataPayload: any = {
            chat_id,
            // User message fields (ALWAYS included)
            message_id: user_message.message_id,
            encrypted_content: encryptedUserContent,
            encrypted_sender_name: encryptedUserSenderName,
            encrypted_category: encryptedUserCategory,  // User message category
            created_at: user_message.created_at,
            // Chat key (ALWAYS included for new chats, may be undefined for follow-ups if already stored)
            encrypted_chat_key: encryptedChatKey,
            // Version info - use actual values from chat object
            versions: {
                messages_v: chat.messages_v || 0,
                title_v: chat.title_v || 0,  // Use title_v from updated chat (should be incremented)
                last_edited_overall_timestamp: user_message.created_at
            },
            task_id
        };
        
        // ONLY include chat metadata fields if they're set (NEW CHATS ONLY)
        // For follow-ups, these will be null and should NOT be sent to avoid overwriting existing metadata
        if (encryptedTitle) {
            metadataPayload.encrypted_title = encryptedTitle;
        }
        if (encryptedIcon) {
            metadataPayload.encrypted_icon = encryptedIcon;
        }
        if (encryptedCategory) {
            metadataPayload.encrypted_chat_category = encryptedCategory;
        }
        
        console.info('[ChatSyncService:Senders] Sending encrypted chat metadata:', {
            chatId: chat_id,
            hasEncryptedTitle: !!encryptedTitle,
            hasEncryptedIcon: !!encryptedIcon,
            hasEncryptedCategory: !!encryptedCategory,
            hasEncryptedUserMessage: !!encryptedUserContent,
            titleVersion: metadataPayload.versions.title_v,
            messagesVersion: metadataPayload.versions.messages_v
        });
        
        // Send to server via new encrypted_chat_metadata handler
        await webSocketService.sendMessage('encrypted_chat_metadata', metadataPayload);
        
    } catch (error) {
        console.error('[ChatSyncService:Senders] Error sending encrypted storage package:', error);
    }
}

// Scroll position and read status sync methods
export async function sendScrollPositionUpdateImpl(
    serviceInstance: ChatSynchronizationService,
    chat_id: string,
    message_id: string
): Promise<void> {
    if (!serviceInstance.webSocketConnected_FOR_SENDERS_ONLY) {
        console.warn('[ChatSyncService:Senders] Cannot send scroll position update - WebSocket not connected');
        return;
    }

    try {
        const payload = {
            chat_id,
            message_id
        };

        console.debug('[ChatSyncService:Senders] Sending scroll position update:', payload);
        await webSocketService.sendMessage('scroll_position_update', payload);
    } catch (error) {
        console.error('[ChatSyncService:Senders] Error sending scroll position update:', error);
    }
}

export async function sendChatReadStatusImpl(
    serviceInstance: ChatSynchronizationService,
    chat_id: string,
    unread_count: number
): Promise<void> {
    if (!serviceInstance.webSocketConnected_FOR_SENDERS_ONLY) {
        console.warn('[ChatSyncService:Senders] Cannot send chat read status - WebSocket not connected');
        return;
    }

    try {
        const payload = {
            chat_id,
            unread_count
        };

        console.debug('[ChatSyncService:Senders] Sending chat read status update:', payload);
        await webSocketService.sendMessage('chat_read_status_update', payload);
    } catch (error) {
        console.error('[ChatSyncService:Senders] Error sending chat read status update:', error);
    }
}
