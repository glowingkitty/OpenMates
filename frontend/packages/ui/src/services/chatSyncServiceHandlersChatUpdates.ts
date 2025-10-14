// frontend/packages/ui/src/services/chatSyncServiceHandlersChatUpdates.ts
import type { ChatSynchronizationService } from './chatSyncService';
import { chatDB } from './db';
import { decryptWithMasterKey } from './cryptoService';
import { chatMetadataCache } from './chatMetadataCache';
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
    
    // Validate payload has required properties
    if (!payload || !payload.chat_id) {
        console.error("[ChatSyncService:ChatUpdates] Invalid payload in handleChatTitleUpdatedImpl: missing chat_id", payload);
        return;
    }
    
    if (!payload.data || payload.data.encrypted_title === undefined) {
        console.error(`[ChatSyncService:ChatUpdates] Invalid payload in handleChatTitleUpdatedImpl: missing data.encrypted_title for chat_id ${payload.chat_id}`, payload);
        return;
    }
    
    if (!payload.versions || payload.versions.title_v === undefined) {
        console.error(`[ChatSyncService:ChatUpdates] Invalid payload in handleChatTitleUpdatedImpl: missing versions.title_v for chat_id ${payload.chat_id}`, payload);
        return;
    }
    
    let tx: IDBTransaction | null = null;
    try {
        tx = await chatDB.getTransaction(chatDB['CHATS_STORE_NAME'], 'readwrite');
        const chat = await chatDB.getChat(payload.chat_id, tx);
        if (chat) {
            // Update encrypted title from broadcast
            chat.encrypted_title = payload.data.encrypted_title;
            chat.title_v = payload.versions.title_v;
            chat.updated_at = Math.floor(Date.now() / 1000);
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
    
    // Validate payload has required properties
    if (!payload || !payload.chat_id) {
        console.error("[ChatSyncService:ChatUpdates] Invalid payload in handleChatDraftUpdatedImpl: missing chat_id", payload);
        return;
    }
    
    if (!payload.data || payload.data.encrypted_draft_md === undefined) {
        console.error(`[ChatSyncService:ChatUpdates] Invalid payload in handleChatDraftUpdatedImpl: missing data.encrypted_draft_md for chat_id ${payload.chat_id}`, payload);
        return;
    }
    
    if (!payload.versions || payload.versions.draft_v === undefined) {
        console.error(`[ChatSyncService:ChatUpdates] Invalid payload in handleChatDraftUpdatedImpl: missing versions.draft_v for chat_id ${payload.chat_id}`, payload);
        return;
    }
    
    let tx: IDBTransaction | null = null;
    try {
        tx = await chatDB.getTransaction(chatDB['CHATS_STORE_NAME'], 'readwrite');
        const chat = await chatDB.getChat(payload.chat_id, tx);
        if (chat) {
            console.debug(`[ChatSyncService:ChatUpdates] Existing chat ${payload.chat_id} found for draft update. Local draft_v: ${chat.draft_v}, Incoming draft_v: ${payload.versions.draft_v}.`);
            
            // Check if this is a draft deletion (encrypted_draft_md is null)
            if (payload.data.encrypted_draft_md === null) {
                console.debug(`[ChatSyncService:ChatUpdates] Received draft deletion for chat ${payload.chat_id}`);
            }
            
            chat.encrypted_draft_md = payload.data.encrypted_draft_md;
            chat.encrypted_draft_preview = payload.data.encrypted_draft_preview || null;
            chat.draft_v = payload.versions.draft_v;
            chat.last_edited_overall_timestamp = payload.last_edited_overall_timestamp;
            chat.updated_at = Math.floor(Date.now() / 1000);
            await chatDB.updateChat(chat, tx);
        } else {
            console.warn(`[ChatSyncService:ChatUpdates] Chat ${payload.chat_id} not found when handling chat_draft_updated broadcast. Creating new chat entry for draft.`);
            const newChatForDraft: Chat = {
                chat_id: payload.chat_id,
                encrypted_title: null, 
                messages_v: 0,
                title_v: 0,
                encrypted_draft_md: payload.data.encrypted_draft_md,
                encrypted_draft_preview: payload.data.encrypted_draft_preview || null,
                draft_v: payload.versions.draft_v,
                last_edited_overall_timestamp: payload.last_edited_overall_timestamp,
                unread_count: 0,
                created_at: payload.last_edited_overall_timestamp,
                updated_at: payload.last_edited_overall_timestamp,
            };
            await chatDB.addChat(newChatForDraft, tx);
        }

        tx.oncomplete = () => {
            console.info(`[ChatSyncService:ChatUpdates] Transaction for handleChatDraftUpdated (chat_id: ${payload.chat_id}) completed successfully.`);
            // Invalidate metadata cache since draft content changed
            chatMetadataCache.invalidateChat(payload.chat_id);
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

/**
 * Handle new_chat_message event from other devices
 * This is sent when a user message is sent from another device
 * It creates a new chat if it doesn't exist locally, or adds the message to an existing chat
 * 
 * IMPORTANT: This event contains plaintext content for display purposes.
 * The encrypted chat key will arrive later via:
 * 1. ai_typing_started event (which includes encrypted metadata), OR
 * 2. Initial sync response when the client reconnects
 * 
 * We create a shell chat here, but DON'T generate a chat key yet.
 * This prevents key mismatch issues between devices.
 */
export async function handleNewChatMessageImpl(
    serviceInstance: ChatSynchronizationService,
    payload: any
): Promise<void> {
    console.info("[ChatSyncService:ChatUpdates] Received new_chat_message (user message from another device):", payload);
    
    // Validate payload has required properties
    if (!payload || !payload.chat_id) {
        console.error("[ChatSyncService:ChatUpdates] Invalid payload in handleNewChatMessageImpl: missing chat_id", payload);
        return;
    }
    
    if (!payload.message_id || !payload.content) {
        console.error(`[ChatSyncService:ChatUpdates] Invalid payload in handleNewChatMessageImpl: missing message data for chat_id ${payload.chat_id}`, payload);
        return;
    }
    
    let tx: IDBTransaction | null = null;
    let isNewChat = false;

    try {
        tx = await chatDB.getTransaction([chatDB['CHATS_STORE_NAME'], chatDB['MESSAGES_STORE_NAME']], 'readwrite');
        
        // Check if chat exists
        let chat = await chatDB.getChat(payload.chat_id, tx);
        
        if (!chat) {
            // Chat doesn't exist locally - create a new chat shell
            // The encrypted_chat_key should come from the payload for proper device sync
            console.info(`[ChatSyncService:ChatUpdates] Creating new chat shell ${payload.chat_id} from new_chat_message event`);
            isNewChat = true;
            
            const newChat: Chat = {
                chat_id: payload.chat_id,
                encrypted_title: null, // Will be populated by ai_typing_started metadata event
                messages_v: payload.messages_v || 1,
                title_v: 0, // Will be updated when metadata arrives
                encrypted_draft_md: null,
                encrypted_draft_preview: null,
                draft_v: 0,
                last_edited_overall_timestamp: payload.last_edited_overall_timestamp || Math.floor(Date.now() / 1000),
                unread_count: 0,
                created_at: payload.created_at || Math.floor(Date.now() / 1000),
                updated_at: Math.floor(Date.now() / 1000),
                encrypted_chat_key: payload.encrypted_chat_key || undefined, // Critical for device sync
            };
            
            // If encrypted_chat_key is provided, decrypt it and cache it for message encryption
            if (payload.encrypted_chat_key) {
                try {
                    const { decryptChatKeyWithMasterKey } = await import('./cryptoService');
                    const chatKey = decryptChatKeyWithMasterKey(payload.encrypted_chat_key);
                    if (chatKey) {
                        chatDB.setChatKey(payload.chat_id, chatKey);
                        console.info(`[ChatSyncService:ChatUpdates] Decrypted and cached chat key for new chat ${payload.chat_id}`);
                    } else {
                        console.error(`[ChatSyncService:ChatUpdates] Failed to decrypt chat key for new chat ${payload.chat_id}`);
                    }
                } catch (error) {
                    console.error(`[ChatSyncService:ChatUpdates] Error decrypting chat key for new chat ${payload.chat_id}:`, error);
                }
            } else {
                console.warn(`[ChatSyncService:ChatUpdates] No encrypted_chat_key in payload for new chat ${payload.chat_id}. Will wait for ai_typing_started event.`);
            }
            
            await chatDB.addChat(newChat, tx);
            chat = newChat; // Use the newly created chat for message saving
            console.info(`[ChatSyncService:ChatUpdates] Created new chat shell ${payload.chat_id} successfully`);
        }
        
        // Create the message object from the payload
        // NOTE: This is plaintext content from the broadcast for immediate display
        // The message will be encrypted when saved via chatDB.saveMessage()
        const newMessage: Message = {
            message_id: payload.message_id,
            chat_id: payload.chat_id,
            role: payload.role || 'user',
            sender_name: payload.sender_name,
            content: payload.content, // This is plaintext from the broadcast
            created_at: payload.created_at || Math.floor(Date.now() / 1000),
            status: 'synced', // Message comes from server, so it's already synced
            encrypted_content: '', // Will be populated by chatDB.saveMessage()
        };
        
        // Save the message (chatDB.saveMessage will handle encryption if chat key is available)
        await chatDB.saveMessage(newMessage, tx);
        console.debug(`[ChatSyncService:ChatUpdates] Saved new message ${payload.message_id} to chat ${payload.chat_id}`);
        
        // Update chat metadata
        chat.messages_v = payload.messages_v || (chat.messages_v + 1);
        chat.last_edited_overall_timestamp = payload.last_edited_overall_timestamp || Math.floor(Date.now() / 1000);
        chat.updated_at = Math.floor(Date.now() / 1000);
        
        await chatDB.updateChat(chat, tx);

        tx.oncomplete = () => {
            console.info(`[ChatSyncService:ChatUpdates] Successfully processed new_chat_message for chat ${payload.chat_id}`);
            // Dispatch event to update UI
            serviceInstance.dispatchEvent(new CustomEvent('chatUpdated', { 
                detail: { 
                    chat_id: payload.chat_id, 
                    newMessage, 
                    chat,
                    isNewChat // Indicate if this was a newly created chat
                } 
            }));
        };
        
    } catch (error) {
        console.error("[ChatSyncService:ChatUpdates] Error in handleNewChatMessage:", error);
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
    
    // Validate payload has required properties
    if (!payload || !payload.chat_id) {
        console.error("[ChatSyncService:ChatUpdates] Invalid payload in handleChatMessageReceivedImpl: missing chat_id", payload);
        return;
    }
    
    if (!payload.message) {
        console.error(`[ChatSyncService:ChatUpdates] Invalid payload in handleChatMessageReceivedImpl: missing message for chat_id ${payload.chat_id}`, payload);
        return;
    }
    
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
        let chat = await chatDB.getChat(payload.chat_id, tx);
        if (chat) {
            // CRITICAL: Only update specific fields, preserve all encrypted metadata
            // Create a minimal update object that only touches what we need to change
            const chatUpdate: Chat = {
                ...chat, // Preserve ALL existing fields including encrypted_title, encrypted_icon, encrypted_category
                messages_v: payload.versions.messages_v,
                last_edited_overall_timestamp: payload.last_edited_overall_timestamp,
                updated_at: Math.floor(Date.now() / 1000)
            };
            
            console.debug(`[ChatSyncService:ChatUpdates] Updating chat ${payload.chat_id} with messages_v: ${chatUpdate.messages_v}`, {
                preservedEncryptedTitle: !!chatUpdate.encrypted_title,
                preservedEncryptedIcon: !!chatUpdate.encrypted_icon,
                preservedEncryptedCategory: !!chatUpdate.encrypted_category
            });
            
            await chatDB.updateChat(chatUpdate, tx); // updateChat saves the whole chat object

            tx.oncomplete = () => {
                console.info(`[ChatSyncService:ChatUpdates] Chat ${payload.chat_id} updated with messages_v: ${chat.messages_v}`);
                // Dispatch with the full chat object from DB to ensure consistency
                chatDB.getChat(payload.chat_id).then(finalChatState => { // Get the latest state after tx completion
                    serviceInstance.dispatchEvent(new CustomEvent('chatUpdated', { detail: { chat_id: payload.chat_id, newMessage: incomingMessage, chat: finalChatState || chat } }));
                });
            };
            // tx.onerror handled by outer catch
        } else {
            // This case implies a message arrived for a chat not in local DB.
            // This could happen if initial sync was incomplete or chat was deleted locally then message arrived.
            // For now, log a warning. A more robust solution might involve creating a shell chat.
            console.warn(`[ChatSyncService:ChatUpdates] Chat ${payload.chat_id} not found when handling 'chat_message_added'. Message ID: ${incomingMessage.message_id}.`);
            if (tx && tx.abort) {
                try { tx.abort(); } catch (e) { console.error("Error aborting transaction:", e); }
            }
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
    
    // Validate payload has required properties
    if (!payload || !payload.chat_id) {
        console.error("[ChatSyncService:ChatUpdates] Invalid payload in handleChatMessageConfirmedImpl: missing chat_id", payload);
        return;
    }
    
    if (!payload.message_id) {
        console.error(`[ChatSyncService:ChatUpdates] Invalid payload in handleChatMessageConfirmedImpl: missing message_id for chat_id ${payload.chat_id}`, payload);
        return;
    }
    
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
            // Only update if the values are defined and valid
            if (payload.new_messages_v !== undefined && payload.new_messages_v !== null) {
                chat.messages_v = payload.new_messages_v;
            }
            if (payload.new_last_edited_overall_timestamp !== undefined && payload.new_last_edited_overall_timestamp !== null) {
                chat.last_edited_overall_timestamp = payload.new_last_edited_overall_timestamp;
            }
            chat.updated_at = Math.floor(Date.now() / 1000);
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
    console.info("[ChatSyncService:ChatUpdates] Received chat_deleted from server:", payload);
    
    // Validate payload has required properties
    if (!payload || !payload.chat_id) {
        console.error("[ChatSyncService:ChatUpdates] Invalid payload in handleChatDeletedImpl: missing chat_id", payload);
        return;
    }
    
    if (payload.tombstone) {
        try {
            // Check if chat still exists before attempting delete
            const chatExists = await chatDB.getChat(payload.chat_id);
            
            if (chatExists) {
                // Chat exists - this deletion was initiated by another device
                console.debug(`[ChatSyncService:ChatUpdates] Chat ${payload.chat_id} exists, deleting from IndexedDB (initiated by another device)`);
                await chatDB.deleteChat(payload.chat_id);
                console.debug(`[ChatSyncService:ChatUpdates] Chat ${payload.chat_id} deleted from IndexedDB`);
                
                // Dispatch event to update UI since this is a deletion from another device
                serviceInstance.dispatchEvent(new CustomEvent('chatDeleted', { detail: { chat_id: payload.chat_id } }));
                console.debug(`[ChatSyncService:ChatUpdates] chatDeleted event dispatched for chat ${payload.chat_id}`);
            } else {
                // Chat already deleted - this was an optimistic delete from this device
                console.debug(`[ChatSyncService:ChatUpdates] Chat ${payload.chat_id} already deleted (optimistic delete from this device)`);
                // No need to dispatch event - it was already dispatched during optimistic delete
            }
        } catch (error) {
            console.error("[ChatSyncService:ChatUpdates] Error in handleChatDeleted (calling chatDB.deleteChat):", error);
        }
    }
}

/**
 * Handle metadata for encryption - Dual-Phase Architecture
 * Server sends plaintext metadata (title, category) for client-side encryption
 */
export async function handleChatMetadataForEncryptionImpl(
    serviceInstance: ChatSynchronizationService,
    payload: any
): Promise<void> {
    console.info("[ChatSyncService:ChatUpdates] Received chat_metadata_for_encryption:", payload);
    
    // Validate payload
    if (!payload || !payload.chat_id) {
        console.error("[ChatSyncService:ChatUpdates] Invalid payload: missing chat_id", payload);
        return;
    }
    
    try {
        const { chat_id, plaintext_title, plaintext_category, task_id } = payload;
        
        // Get the current chat to access stored user message for encryption
        const chat = await chatDB.getChat(chat_id);
        if (!chat) {
            console.error(`[ChatSyncService:ChatUpdates] Chat ${chat_id} not found for metadata encryption`);
            return;
        }
        
        // Get the user's pending message (the one being processed)
        // This should be the most recent user message in the chat
        const messages = await chatDB.getMessagesForChat(chat_id);
        const userMessage = messages
            .filter(m => m.role === 'user')
            .sort((a, b) => b.created_at - a.created_at)[0];
            
        if (!userMessage) {
            console.error(`[ChatSyncService:ChatUpdates] No user message found for chat ${chat_id} to encrypt`);
            return;
        }
        
        console.info(`[ChatSyncService:ChatUpdates] Updating local chat with encrypted metadata for chat ${chat_id}:`, {
            hasTitle: !!plaintext_title,
            hasCategory: !!plaintext_category,
            hasUserMessage: !!userMessage,
            taskId: task_id
        });
        
        // PHASE 2: Update local chat with encrypted metadata
        // Get or generate chat key for encryption
        const chatKey = chatDB.getOrGenerateChatKey(chat_id);
        
        // Import chat-specific encryption function
        const { encryptWithChatKey } = await import('./cryptoService');
        
        // Encrypt title with chat-specific key for local storage
        let encryptedTitle: string | null = null;
        if (plaintext_title) {
            encryptedTitle = encryptWithChatKey(plaintext_title, chatKey);
            if (!encryptedTitle) {
                console.error(`[ChatSyncService:ChatUpdates] Failed to encrypt title for chat ${chat_id}`);
                return;
            }
        }
        
        // Update local chat with encrypted metadata
        const tx = await chatDB.getTransaction(chatDB['CHATS_STORE_NAME'], 'readwrite');
        try {
            const chatToUpdate = await chatDB.getChat(chat_id, tx);
            if (chatToUpdate) {
                // Update chat with encrypted title
                if (encryptedTitle) {
                    chatToUpdate.encrypted_title = encryptedTitle;
                    chatToUpdate.title_v = (chatToUpdate.title_v || 0) + 1; // Frontend increments title_v
                }
                
                // Update timestamps
                chatToUpdate.updated_at = Math.floor(Date.now() / 1000);
                
                await chatDB.updateChat(chatToUpdate, tx);
                
                tx.oncomplete = () => {
                    console.info(`[ChatSyncService:ChatUpdates] Local chat ${chat_id} updated with encrypted metadata`);
                    serviceInstance.dispatchEvent(new CustomEvent('chatUpdated', { 
                        detail: { chat_id, type: 'metadata_updated', chat: chatToUpdate } 
                    }));
                };
            } else {
                console.error(`[ChatSyncService:ChatUpdates] Chat ${chat_id} not found for metadata update`);
                if (tx.abort) tx.abort();
                return;
            }
        } catch (error) {
            console.error(`[ChatSyncService:ChatUpdates] Error updating local chat ${chat_id}:`, error);
            if (tx.abort) tx.abort();
            return;
        }
        
        // Import the storage sender
        const { sendEncryptedStoragePackage } = await import('./chatSyncServiceSenders');
        
        // Send encrypted storage package to server for permanent storage
        await sendEncryptedStoragePackage(
            serviceInstance,
            {
                chat_id,
                plaintext_title,
                plaintext_category,
                user_message: userMessage,
                task_id
            }
        );
        
    } catch (error) {
        console.error("[ChatSyncService:ChatUpdates] Error handling metadata for encryption:", error);
    }
}
