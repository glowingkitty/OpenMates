// frontend/packages/ui/src/services/chatSyncServiceSenders.ts
import type { ChatSynchronizationService } from './chatSyncService';
import { chatDB } from './db';
import { webSocketService } from './websocketService';
import { notificationStore } from '../stores/notificationStore';
import { get } from 'svelte/store';
import { websocketStatus } from '../stores/websocketStatusStore';
import { chatMetadataCache } from './chatMetadataCache';
import type {
    Chat,
    Message,
    OfflineChange,
    // Payloads for sending messages
    UpdateTitlePayload,
    UpdateDraftPayload,
    DeleteDraftPayload,
    DeleteChatPayload,
    SetActiveChatPayload,
    CancelAITaskPayload,
    SyncOfflineChangesPayload, // Assuming this is used by a sender method if sendOfflineChanges is moved
    StoreEmbedPayload
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
    const encryptedTitle = await encryptWithChatKey(new_title, chatKey);
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
                serviceInstance.dispatchEvent(new CustomEvent('chatUpdated', { detail: { chat_id, type: 'title_updated', chat } }));
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
            // CRITICAL: Invalidate cache before dispatching event to ensure UI components fetch fresh data
            // This prevents stale draft previews from appearing in the chat list
            chatMetadataCache.invalidateChat(chat_id);
            console.debug('[sendDeleteDraftImpl] Invalidated cache for chat:', chat_id);
            
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
            // Access public method for queueing offline changes
            const queueMethod = (serviceInstance as ChatSynchronizationService & { queueOfflineChange?: (change: OfflineChange) => void }).queueOfflineChange;
            if (queueMethod) {
                queueMethod(offlineChange);
            }
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
 * @param chat_id - The ID of the chat to delete
 * @param embed_ids_to_delete - Optional array of embed IDs that were deleted from IndexedDB
 *                              Server will verify these embeds are not used by other chats before deleting from Directus
 */
export async function sendDeleteChatImpl(
    serviceInstance: ChatSynchronizationService,
    chat_id: string,
    embed_ids_to_delete: string[] = []
): Promise<void> {
    // Include embed_ids in the payload for server-side cleanup
    // Server will check if each embed is used by any other chat (not in last 100)
    // before permanently deleting from Directus
    const payload: DeleteChatPayload & { embed_ids_to_delete?: string[] } = { 
        chatId: chat_id,
        embed_ids_to_delete: embed_ids_to_delete.length > 0 ? embed_ids_to_delete : undefined
    };
    
    try {
        // Send delete request to server
        console.debug(`[ChatSyncService:Senders] Sending delete_chat request to server for chat ${chat_id}`, {
            embedIdsToDelete: embed_ids_to_delete.length
        });
        await webSocketService.sendMessage('delete_chat', payload);
        console.debug(`[ChatSyncService:Senders] Delete request sent successfully for chat ${chat_id} with ${embed_ids_to_delete.length} embed deletions`);
        
        // NOTE: chatDeleted event is now dispatched by Chat.svelte after IndexedDB deletion
        // to ensure proper UI update timing. No need to dispatch it here.
    } catch (error) {
        console.error(`[ChatSyncService:Senders] Error sending delete_chat request for chat ${chat_id}:`, error);
        throw error; // Re-throw so caller can handle the error
    }
}

export async function sendNewMessageImpl(
    serviceInstance: ChatSynchronizationService,
    message: Message,
    encryptedSuggestionToDelete?: string | null
): Promise<void> {
    // Check WebSocket connection status using public getter
    const isConnected = serviceInstance.webSocketConnected_FOR_SENDERS_ONLY;
    
    if (!isConnected) {
        console.warn("[ChatSyncService:Senders] WebSocket not connected. Message saved locally with 'waiting_for_internet' status.");
        
        // Update message status to 'waiting_for_internet' if it's currently 'sending'
        // This ensures the UI shows the correct status when offline
        if (message.status === 'sending') {
            try {
                const updatedMessage: Message = { ...message, status: 'waiting_for_internet' };
                await chatDB.saveMessage(updatedMessage);
                
                // Dispatch event to update UI with new status
                serviceInstance.dispatchEvent(new CustomEvent('messageStatusChanged', {
                    detail: { 
                        chatId: message.chat_id, 
                        messageId: message.message_id, 
                        status: 'waiting_for_internet' 
                    }
                }));
                
                console.debug(`[ChatSyncService:Senders] Updated message ${message.message_id} status to 'waiting_for_internet'`);
            } catch (dbError) {
                console.error(`[ChatSyncService:Senders] Error updating message status to 'waiting_for_internet' for ${message.message_id}:`, dbError);
            }
        }
        
        return;
    }
    
    // DUAL-PHASE ARCHITECTURE - Phase 1: Send ONLY plaintext for AI processing
    // Encrypted data will be sent separately after preprocessing completes via chat_metadata_for_encryption event
    
    // CRITICAL: Determine if this is a NEW chat or FOLLOW-UP message
    // Check if chat has existing messages (messages_v > 1, since current message is #1 for new chats)
    // NOT just encrypted_title, because title generation might have been skipped/failed
    // Also check if this is an incognito chat
    let chat: Chat | null = null;
    let isIncognitoChat = false;
    
    // First check if it's an incognito chat
    const { incognitoChatService } = await import('./incognitoChatService');
    try {
        chat = await incognitoChatService.getChat(message.chat_id);
        if (chat) {
            isIncognitoChat = true;
        }
        } catch {
            // Not an incognito chat, continue to check IndexedDB
        }
    
    // If not found in incognito service, check IndexedDB
    if (!chat) {
        chat = await chatDB.getChat(message.chat_id);
    }
    
    const chatHasMessages = (chat?.messages_v ?? 0) > 1; // > 1 because current message will be message #1
    
    console.debug(`[ChatSyncService:Senders] Chat has existing messages: ${chatHasMessages} (messages_v: ${chat?.messages_v}) - ${chatHasMessages ? 'FOLLOW-UP' : 'NEW CHAT'}, isIncognito: ${isIncognitoChat}`);
    
    // Extract embed references from message content
    // Embeds are referenced as JSON code blocks: ```json\n{"type": "app_skill_use", "embed_id": "..."}\n```
    const { extractEmbedReferences, loadEmbeds } = await import('./embedResolver');
    const embedRefs = extractEmbedReferences(message.content);
    
    // Load embeds from EmbedStore (decrypted, ready to send as cleartext)
    interface EmbedForServer {
        embed_id: string;
        type: string;
        status?: string;
        content: string;
        text_preview?: string;
        embed_ids?: string[];
        createdAt?: number;
        updatedAt?: number;
    }
    const embeds: EmbedForServer[] = [];
    if (embedRefs.length > 0) {
        const embedIds = embedRefs.map(ref => ref.embed_id);
        const loadedEmbeds = await loadEmbeds(embedIds);
        
        // Convert embeds to format expected by server (cleartext, will be encrypted server-side)
        for (const embed of loadedEmbeds) {
            embeds.push({
                embed_id: embed.embed_id,
                type: embed.type, // Decrypted type (client-side only)
                status: embed.status,
                content: embed.content, // TOON-encoded string (cleartext for server)
                text_preview: embed.text_preview,
                embed_ids: embed.embed_ids, // For composite embeds
                createdAt: embed.createdAt,
                updatedAt: embed.updatedAt
            });
        }
        
        console.debug('[ChatSyncService:Senders] Extracted and loaded embeds:', {
            embedRefCount: embedRefs.length,
            loadedCount: embeds.length,
            embedIds: embedIds
        });
    }
    
    // For incognito chats, load full message history (no server-side caching)
    let messageHistory: Message[] = [];
    if (isIncognitoChat) {
        try {
            messageHistory = await incognitoChatService.getMessagesForChat(message.chat_id);
            console.debug(`[ChatSyncService:Senders] Loaded ${messageHistory.length} messages from incognito chat history`);
        } catch (error) {
            console.error(`[ChatSyncService:Senders] Error loading incognito chat message history:`, error);
        }
    }
    
    // Phase 1 payload: ONLY fields needed for AI processing
    interface SendMessagePayload {
        chat_id: string;
        message: {
            message_id: string;
            role: string;
            content: string;
            created_at: number;
            sender_name?: string;
            category?: string;
            model_name?: string;
            chat_has_title?: boolean;
        };
        is_incognito?: boolean;
        embeds?: EmbedForServer[];
        message_history?: Message[];
        encrypted_suggestion_to_delete?: string | null;
    }
    const payload: SendMessagePayload = {
        chat_id: message.chat_id,
        message: {
            message_id: message.message_id,
            role: message.role,
            content: message.content, // ONLY plaintext for AI processing (contains embed references as JSON blocks)
            created_at: message.created_at,
            sender_name: message.sender_name, // Include for cache but not critical for AI
            chat_has_title: chatHasMessages // ZERO-KNOWLEDGE: Send true if chat has messages (follow-up), false if new
            // NO category or encrypted fields - those go to Phase 2
            // NO message_history - server will request if cache is stale (unless incognito)
        },
        is_incognito: isIncognitoChat // Flag for backend to skip persistence
    };
    
    // For incognito chats, include full message history (no server-side caching)
    if (isIncognitoChat && messageHistory.length > 0) {
        payload.message_history = messageHistory.map(msg => ({
            message_id: msg.message_id,
            role: msg.role,
            content: typeof msg.content === 'string' ? msg.content : JSON.stringify(msg.content),
            created_at: msg.created_at,
            sender_name: msg.sender_name
        } as Message));
        console.debug(`[ChatSyncService:Senders] Including full message history for incognito chat: ${messageHistory.length} messages`);
    }
    
    // Include embeds if any were found in the message
    if (embeds.length > 0) {
        payload.embeds = embeds; // Send embeds as cleartext (server will encrypt for cache)
        console.debug('[ChatSyncService:Senders] Including embeds with message:', embeds.length);
    }
    
    // Include encrypted suggestion for deletion if user clicked a new chat suggestion
    if (encryptedSuggestionToDelete) {
        payload.encrypted_suggestion_to_delete = encryptedSuggestionToDelete;
        console.debug('[ChatSyncService:Senders] Including encrypted suggestion for server deletion');
    }
    
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
    if (!serviceInstance.webSocketConnected_FOR_SENDERS_ONLY) {
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
    // CRITICAL FIX: await getEncryptedFields since it's now async to prevent storing Promises
    const encryptedFields = await chatDB.getEncryptedFields(aiMessage, aiMessage.chat_id);
    
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
            encrypted_category: encryptedFields.encrypted_category,
            encrypted_model_name: encryptedFields.encrypted_model_name
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
    // CRITICAL: Update IndexedDB immediately when switching chats or opening new chat window
    // This ensures tab reload uses the correct last_opened chat (from IndexedDB, not server)
    // The server update happens via WebSocket, but IndexedDB update is immediate for better UX
    try {
        // Import userDB and updateProfile dynamically to avoid circular dependencies
        const { userDB } = await import('../services/userDB');
        const { updateProfile } = await import('../stores/userProfile');
        
        // Determine the last_opened value:
        // - If chatId is a real chat ID, use it
        // - If chatId is null (new chat window), use '/chat/new'
        // - This ensures tab reload opens the correct view (chat or new chat window)
        const lastOpenedValue = chatId || '/chat/new';
        
        // Update IndexedDB with new last_opened chat/window
        // This is the source of truth for tab reload scenarios
        await userDB.updateUserData({ last_opened: lastOpenedValue });
        
        // Also update the userProfile store to keep it in sync
        updateProfile({ last_opened: lastOpenedValue });
        
        console.debug(`[ChatSyncService:Senders] Updated IndexedDB with last_opened: ${lastOpenedValue} (chatId: ${chatId})`);
    } catch (error) {
        console.error(`[ChatSyncService:Senders] Error updating IndexedDB with last_opened: ${chatId}:`, error);
        // Don't fail the whole operation if IndexedDB update fails
    }
    
    // Send to server via WebSocket (for cross-device sync and login scenarios)
    // Note: Server handles null chatId by not updating last_opened (per backend logic)
    if (!(serviceInstance as any).webSocketConnected) {
        console.warn("[ChatSyncService:Senders] WebSocket not connected. Cannot send 'set_active_chat'.");
        return;
    }
    const payload: SetActiveChatPayload = { chat_id: chatId };
    try {
        await webSocketService.sendMessage('set_active_chat', payload);
        console.debug(`[ChatSyncService:Senders] Sent 'set_active_chat' to server: ${chatId}`);
    } catch (error) {
        console.error(`[ChatSyncService:Senders] Error sending 'set_active_chat' for chat_id: ${chatId}:`, error);
    }
}

/**
 * Sends app settings/memories confirmation to server.
 * 
 * When user confirms app settings/memories request, client:
 * 1. Loads app settings/memories from IndexedDB (encrypted)
 * 2. Decrypts using app-specific keys
 * 3. Sends decrypted data to server (server encrypts with vault key and caches)
 * 
 * Cache is chat-specific, so app settings/memories are automatically evicted
 * when the chat is evicted from cache.
 * 
 * @param serviceInstance ChatSynchronizationService instance
 * @param chatId Chat ID where the request was made
 * @param appSettingsMemories Array of decrypted app settings/memories entries
 *                            Format: [{ app_id: string, item_key: string, content: any }, ...]
 */
export async function sendAppSettingsMemoriesConfirmedImpl(
    serviceInstance: ChatSynchronizationService,
    chatId: string,
    appSettingsMemories: Array<{
        app_id: string;
        item_key: string;
        content: any; // Decrypted content (will be JSON stringified by server)
    }>
): Promise<void> {
    if (!(serviceInstance as any).webSocketConnected) {
        console.warn("[ChatSyncService:Senders] WebSocket not connected. Cannot send 'app_settings_memories_confirmed'.");
        return;
    }
    
    if (!appSettingsMemories || !Array.isArray(appSettingsMemories) || appSettingsMemories.length === 0) {
        console.warn("[ChatSyncService:Senders] No app settings/memories to send");
        return;
    }
    
    const payload = {
        chat_id: chatId,
        app_settings_memories: appSettingsMemories.map(item => ({
            app_id: item.app_id,
            item_key: item.item_key,
            content: item.content // Decrypted content - server will encrypt with vault key
        }))
    };
    
    try {
        await webSocketService.sendMessage('app_settings_memories_confirmed', payload);
        console.info(`[ChatSyncService:Senders] Sent ${appSettingsMemories.length} app settings/memories confirmations for chat ${chatId}`);
    } catch (error) {
        console.error(`[ChatSyncService:Senders] Error sending 'app_settings_memories_confirmed' for chat_id: ${chatId}:`, error);
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
        console.log(`[ChatSyncService:Senders] Getting chat key for ${chat_id}`);
        const chatKey = chatDB.getOrGenerateChatKey(chat_id);
        console.log(`[ChatSyncService:Senders] Chat key obtained for ${chat_id}, length: ${chatKey.length}`);

        // Get encrypted chat key for server storage
        console.log(`[ChatSyncService:Senders] Retrieving encrypted_chat_key for ${chat_id}...`);
        let encryptedChatKey = await chatDB.getEncryptedChatKey(chat_id);

        // DEFENSIVE FIX: If encrypted_chat_key is missing, generate and save it now
        if (!encryptedChatKey) {
            console.warn(`[ChatSyncService:Senders] ⚠️ encrypted_chat_key missing for ${chat_id}, generating and saving now (defensive fix)`);
            const { encryptChatKeyWithMasterKey } = await import('./cryptoService');
            encryptedChatKey = await encryptChatKeyWithMasterKey(chatKey);

            if (encryptedChatKey) {
                // Update chat in DB with the encrypted key
                chat.encrypted_chat_key = encryptedChatKey;
                await chatDB.updateChat(chat);
                console.log(`[ChatSyncService:Senders] ✅ Generated and saved encrypted_chat_key for ${chat_id}: ${encryptedChatKey.substring(0, 20)}...`);
            } else {
                console.error(`[ChatSyncService:Senders] ❌ Failed to encrypt chat key for ${chat_id} - master key may be missing`);
            }
        } else {
            console.log(`[ChatSyncService:Senders] Encrypted chat key for ${chat_id}: ✅ Present (${encryptedChatKey.substring(0, 20)}..., length: ${encryptedChatKey.length})`);
        }
        
        // Import encryption functions
        const { encryptWithChatKey } = await import('./cryptoService');
        
        // CRITICAL FIX: Ensure user message has content before encrypting
        // If content is missing, try to get it from encrypted_content (shouldn't happen, but defensive)
        if (!user_message.content && user_message.encrypted_content) {
            console.warn(`[ChatSyncService:Senders] User message ${user_message.message_id} missing content field, attempting to decrypt from encrypted_content`);
            const { decryptWithChatKey } = await import('./cryptoService');
            try {
                const decrypted = await decryptWithChatKey(user_message.encrypted_content, chatKey);
                if (decrypted) {
                    user_message.content = decrypted;
                    console.info(`[ChatSyncService:Senders] Successfully decrypted content for message ${user_message.message_id}`);
                }
            } catch (decryptError) {
                console.error(`[ChatSyncService:Senders] Failed to decrypt content for message ${user_message.message_id}:`, decryptError);
            }
        }
        
        // CRITICAL FIX: encryptWithChatKey is async - must await it!
        // Encrypt user message content
        const encryptedUserContent = user_message.content 
            ? (typeof user_message.content === 'string' 
                ? await encryptWithChatKey(user_message.content, chatKey)
                : await encryptWithChatKey(JSON.stringify(user_message.content), chatKey))
            : null;
        
        // CRITICAL: Validate that we have encrypted content before sending
        if (!encryptedUserContent) {
            console.error(`[ChatSyncService:Senders] ❌ CRITICAL: Cannot send encrypted user message ${user_message.message_id} - no content available to encrypt!`, {
                hasContent: !!user_message.content,
                hasEncryptedContent: !!user_message.encrypted_content,
                messageId: user_message.message_id,
                chatId: chat_id
            });
            // Don't send if we can't encrypt the user message - this is a critical error
            return;
        }
        
        // CRITICAL FIX: encryptWithChatKey is async - must await all encryption operations!
        // Encrypt user message metadata
        const encryptedUserSenderName = user_message.sender_name 
            ? await encryptWithChatKey(user_message.sender_name, chatKey) 
            : null;
        const encryptedUserCategory = plaintext_category 
            ? await encryptWithChatKey(plaintext_category, chatKey) 
            : null;
        
        // NOTE: encrypted_model_name is NOT sent with user messages - it should only be stored on assistant messages
        // The model_name indicates which AI model generated the assistant's response, not which model will respond
        // The model_name will be sent when the assistant message is completed
        
        // AI response is handled separately - not part of immediate storage
        
        // Encrypt title with chat-specific key (for chat-level metadata)
        const encryptedTitle = plaintext_title 
            ? await encryptWithChatKey(plaintext_title, chatKey)
            : null;
        
        // Encrypt icon with chat-specific key (for chat-level metadata)
        const encryptedIcon = plaintext_icon 
            ? await encryptWithChatKey(plaintext_icon, chatKey)
            : null;
        
        // Encrypt category with chat-specific key (for chat-level metadata)
        const encryptedCategory = plaintext_category 
            ? await encryptWithChatKey(plaintext_category, chatKey)
            : null;
        
        // Create encrypted metadata payload for new handler
        // CRITICAL: Only include metadata fields if they're actually set (not null)
        // For follow-up messages, metadata fields should be undefined/null and NOT included
        interface MetadataPayload {
            chat_id: string;
            message_id: string;
            encrypted_content: string;
            encrypted_sender_name?: string;
            encrypted_category?: string;
            encrypted_title?: string;
            encrypted_chat_category?: string;
            encrypted_icon?: string;
            encrypted_chat_summary?: string;
            encrypted_chat_tags?: string;
            encrypted_follow_up_suggestions?: string;
            encrypted_new_chat_suggestions?: string;
            encrypted_top_recommended_apps_for_chat?: string;
            created_at: number;
            encrypted_chat_key?: string;
            versions: {
                messages_v: number;
                title_v: number;
                last_edited_overall_timestamp: number;
            };
            task_id?: string;
        }
        const metadataPayload: MetadataPayload = {
            chat_id,
            // User message fields (ALWAYS included)
            message_id: user_message.message_id,
            encrypted_content: encryptedUserContent,
            encrypted_sender_name: encryptedUserSenderName,
            encrypted_category: encryptedUserCategory,  // User message category
            // NOTE: encrypted_model_name is NOT included for user messages - only for assistant messages
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
            messageId: metadataPayload.message_id,
            hasEncryptedTitle: !!encryptedTitle,
            hasEncryptedIcon: !!encryptedIcon,
            hasEncryptedCategory: !!encryptedCategory,
            hasEncryptedUserMessage: !!encryptedUserContent,
            hasEncryptedUserContent: !!metadataPayload.encrypted_content,
            encryptedContentLength: encryptedUserContent?.length || 0,
            titleVersion: metadataPayload.versions.title_v,
            messagesVersion: metadataPayload.versions.messages_v,
            payloadKeys: Object.keys(metadataPayload).join(', ')
        });
        
        // CRITICAL: Ensure encrypted_content is always included if we have it
        if (!metadataPayload.encrypted_content && encryptedUserContent) {
            console.error(`[ChatSyncService:Senders] ❌ CRITICAL BUG: encryptedUserContent exists but not in payload!`, {
                encryptedUserContent: encryptedUserContent.substring(0, 50) + '...',
                payloadHasEncryptedContent: !!metadataPayload.encrypted_content
            });
            // Force it into the payload
            metadataPayload.encrypted_content = encryptedUserContent;
        }
        
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

/**
 * Send encrypted post-processing metadata (suggestions, summary, tags) to server for Directus sync
 * Called after client encrypts plaintext suggestions received from post-processing
 */
export async function sendPostProcessingMetadataImpl(
    serviceInstance: ChatSynchronizationService,
    chat_id: string,
    encrypted_follow_up_suggestions: string,
    encrypted_new_chat_suggestions: string[],
    encrypted_chat_summary: string,
    encrypted_chat_tags: string,
    encrypted_top_recommended_apps: string = ''
): Promise<void> {
    if (!serviceInstance.webSocketConnected_FOR_SENDERS_ONLY) {
        console.warn('[ChatSyncService:Senders] Cannot send post-processing metadata - WebSocket not connected');
        return;
    }

    try {
        interface PostProcessingPayload {
            chat_id: string;
            encrypted_follow_up_suggestions?: string;
            encrypted_new_chat_suggestions?: string[];
            encrypted_chat_summary?: string;
            encrypted_chat_tags?: string;
            encrypted_top_recommended_apps_for_chat?: string;
        }
        
        // Build payload with all the encrypted post-processing metadata
        const payload: PostProcessingPayload = {
            chat_id,
            encrypted_follow_up_suggestions,
            encrypted_new_chat_suggestions,
            encrypted_chat_summary,
            encrypted_chat_tags
        };

        // Only include top recommended apps if provided
        if (encrypted_top_recommended_apps) {
            payload.encrypted_top_recommended_apps_for_chat = encrypted_top_recommended_apps;
        }

        console.debug('[ChatSyncService:Senders] Sending encrypted post-processing metadata for sync to Directus');
        await webSocketService.sendMessage('update_post_processing_metadata', payload);
    } catch (error) {
        console.error('[ChatSyncService:Senders] Error sending post-processing metadata:', error);
        throw error; // Don't swallow errors
    }
}

/**
 * Send encrypted embed to server for Directus storage
 */
export async function sendStoreEmbedImpl(
    serviceInstance: ChatSynchronizationService,
    payload: StoreEmbedPayload
): Promise<void> {
    if (!serviceInstance.webSocketConnected_FOR_SENDERS_ONLY) {
        console.warn('[ChatSyncService:Senders] Cannot send store_embed - WebSocket not connected');
        // TODO: Queue for offline sync?
        return;
    }

    try {
        console.debug(`[ChatSyncService:Senders] Sending encrypted embed ${payload.embed_id} to server`);
        await webSocketService.sendMessage('store_embed', payload);
    } catch (error) {
        console.error('[ChatSyncService:Senders] Error sending store_embed:', error);
        throw error;
    }
}

/**
 * Send encrypted_chat_key update to server for chat metadata sync
 * Used for hiding/unhiding chats by updating the encryption wrapper
 * 
 * @param serviceInstance ChatSynchronizationService instance
 * @param chat_id Chat ID to update
 * @param encrypted_chat_key New encrypted chat key (encrypted with combined secret for hidden chats)
 */
export async function sendUpdateChatKeyImpl(
    serviceInstance: ChatSynchronizationService,
    chat_id: string,
    encrypted_chat_key: string
): Promise<void> {
    if (!serviceInstance.webSocketConnected_FOR_SENDERS_ONLY) {
        console.warn('[ChatSyncService:Senders] Cannot send encrypted_chat_key update - WebSocket not connected');
        return;
    }

    try {
        // Get current chat to preserve version info
        const chat = await chatDB.getChat(chat_id);
        if (!chat) {
            console.error(`[ChatSyncService:Senders] Chat ${chat_id} not found for encrypted_chat_key update`);
            return;
        }

        // Create payload for encrypted_chat_metadata handler
        // This handler accepts encrypted_chat_key and updates it in Directus
        // message_id is optional - we omit it since we're only updating metadata
        const payload: any = {
            chat_id,
            encrypted_chat_key,
            // Include version info to preserve chat state
            versions: {
                messages_v: chat.messages_v || 0,
                title_v: chat.title_v || 0,
                last_edited_overall_timestamp: chat.last_edited_overall_timestamp || Math.floor(Date.now() / 1000)
            }
        };

        console.debug(`[ChatSyncService:Senders] Sending encrypted_chat_key update for chat ${chat_id}`, {
            hasEncryptedChatKey: !!encrypted_chat_key,
            encryptedChatKeyLength: encrypted_chat_key?.length || 0,
            messagesV: payload.versions.messages_v,
            titleV: payload.versions.title_v
        });

        // Send via encrypted_chat_metadata handler (backend supports updating just encrypted_chat_key)
        await webSocketService.sendMessage('encrypted_chat_metadata', payload);
        
        console.info(`[ChatSyncService:Senders] Successfully sent encrypted_chat_key update for chat ${chat_id}`);
    } catch (error) {
        console.error(`[ChatSyncService:Senders] Error sending encrypted_chat_key update for chat ${chat_id}:`, error);
        throw error;
    }
}

/**
 * Request embed data from server via WebSocket
 * Server will respond with send_embed_data event containing the embed content
 */
export async function sendRequestEmbed(
    serviceInstance: ChatSynchronizationService,
    embed_id: string
): Promise<void> {
    if (!serviceInstance.webSocketConnected_FOR_SENDERS_ONLY) {
        console.warn('[ChatSyncService:Senders] Cannot send request_embed - WebSocket not connected');
        return;
    }

    try {
        console.debug(`[ChatSyncService:Senders] Requesting embed ${embed_id} from server`);
        await webSocketService.sendMessage('request_embed', { embed_id });
    } catch (error) {
        console.error('[ChatSyncService:Senders] Error requesting embed:', error);
        throw error;
    }
}

/**
 * Send wrapped embed keys to server for embed_keys collection storage
 * This enables offline sharing and cross-chat access (wrapped key architecture)
 * 
 * Payload structure:
 * {
 *   keys: [
 *     {
 *       hashed_embed_id: string,
 *       key_type: 'master' | 'chat',
 *       hashed_chat_id: string | null,
 *       encrypted_embed_key: string,
 *       hashed_user_id: string,
 *       created_at: number
 *     },
 *     ...
 *   ]
 * }
 */
export async function sendStoreEmbedKeysImpl(
    serviceInstance: ChatSynchronizationService,
    payload: {
        keys: Array<{
            hashed_embed_id: string;
            key_type: 'master' | 'chat';
            hashed_chat_id: string | null;
            encrypted_embed_key: string;
            hashed_user_id: string;
            created_at: number;
        }>;
    }
): Promise<void> {
    if (!serviceInstance.webSocketConnected_FOR_SENDERS_ONLY) {
        console.warn('[ChatSyncService:Senders] Cannot send store_embed_keys - WebSocket not connected');
        // TODO: Queue for offline sync?
        return;
    }

    try {
        console.debug(`[ChatSyncService:Senders] Sending ${payload.keys.length} embed key wrapper(s) to server`);
        await webSocketService.sendMessage('store_embed_keys', payload);
        console.info(`[ChatSyncService:Senders] Successfully sent embed key wrappers to server`);
    } catch (error) {
        console.error('[ChatSyncService:Senders] Error sending store_embed_keys:', error);
        throw error;
    }
}

/**
 * Send delete new chat suggestion request to server
 * This removes the suggestion from Directus
 */
export async function sendDeleteNewChatSuggestionImpl(
    serviceInstance: ChatSynchronizationService,
    encryptedSuggestion: string
): Promise<void> {
    if (!serviceInstance.webSocketConnected_FOR_SENDERS_ONLY) {
        console.warn('[ChatSyncService:Senders] Cannot send delete_new_chat_suggestion - WebSocket not connected');
        return;
    }

    // Final validation: reject empty strings (default suggestions cannot be deleted)
    if (!encryptedSuggestion || encryptedSuggestion.trim() === '') {
        console.error('[ChatSyncService:Senders] CRITICAL: Attempted to send empty encrypted_suggestion - rejecting request');
        throw new Error('Cannot delete default suggestion: encrypted_suggestion is empty');
    }

    try {
        console.debug('[ChatSyncService:Senders] Sending delete new chat suggestion request to server');
        await webSocketService.sendMessage('delete_new_chat_suggestion', {
            encrypted_suggestion: encryptedSuggestion
        });
        console.info('[ChatSyncService:Senders] Successfully sent delete suggestion request to server');
    } catch (error) {
        console.error('[ChatSyncService:Senders] Error sending delete_new_chat_suggestion:', error);
        throw error;
    }
}

export async function sendDeleteNewChatSuggestionByIdImpl(
    serviceInstance: ChatSynchronizationService,
    suggestionId: string
): Promise<void> {
    if (!serviceInstance.webSocketConnected_FOR_SENDERS_ONLY) {
        console.warn('[ChatSyncService:Senders] Cannot send delete_new_chat_suggestion - WebSocket not connected');
        return;
    }

    // Final validation: reject empty strings (default suggestions cannot be deleted)
    if (!suggestionId || suggestionId.trim() === '') {
        console.error('[ChatSyncService:Senders] CRITICAL: Attempted to send empty suggestion_id - rejecting request');
        throw new Error('Cannot delete suggestion: suggestion_id is empty');
    }

    try {
        console.debug('[ChatSyncService:Senders] Sending delete new chat suggestion by ID request to server');
        await webSocketService.sendMessage('delete_new_chat_suggestion', {
            suggestion_id: suggestionId
        });
        console.info('[ChatSyncService:Senders] Successfully sent delete suggestion by ID request to server');
    } catch (error) {
        console.error('[ChatSyncService:Senders] Error sending delete_new_chat_suggestion by ID:', error);
        throw error;
    }
}
