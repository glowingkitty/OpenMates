// frontend/packages/ui/src/services/db/chatCrudOperations.ts
// Handles chat CRUD operations for the ChatDatabase class.
// These operations are extracted from db.ts for better code organization.
//
// This module contains:
// - Chat creation, retrieval, update, deletion
// - Chat encryption/decryption for storage
// - Draft operations (save, create, clear)
// - Batch chat operations

import type { Chat, Message, TiptapJSON } from '../../types/chat';
import { 
    generateChatKey,
    encryptChatKeyWithMasterKey,
    decryptChatKeyWithMasterKey
} from '../cryptoService';
import { get } from 'svelte/store';
import { forcedLogoutInProgress } from '../../stores/signupState';

// Type for ChatDatabase instance to avoid circular import
// Only includes properties/methods needed by this module
interface ChatDatabaseInstance {
    db: IDBDatabase | null;
    CHATS_STORE_NAME: string;
    init(): Promise<void>;
    getTransaction(storeNames: string | string[], mode: IDBTransactionMode): Promise<IDBTransaction>;
    
    // Chat key management methods (from chatKeyManagement)
    getChatKey(chatId: string): Uint8Array | null;
    setChatKey(chatId: string, chatKey: Uint8Array): void;
    clearChatKey(chatId: string): void;
}

// Store name constant for messages (needed for deleteChat)
const MESSAGES_STORE_NAME = 'messages';

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

/**
 * Extract title from TipTap JSON content (first line of text)
 */
export function extractTitleFromContent(content: TiptapJSON): string {
    if (!content) return '';
    try {
        const firstTextNode = content.content?.[0]?.content?.[0];
        if (firstTextNode?.type === 'text' && typeof firstTextNode.text === 'string') {
            return firstTextNode.text.slice(0, 50) + (firstTextNode.text.length > 50 ? '...' : '');
        }
    } catch (error) {
        console.error("[ChatDatabase] Error extracting title from content:", error);
    }
    return '';
}

// ============================================================================
// CHAT ENCRYPTION/DECRYPTION
// ============================================================================

/**
 * Encrypt chat data before storing in IndexedDB
 * EXCEPTION: Public chats (chat_id starting with 'demo-' or 'legal-') are NOT encrypted
 * since they contain public template content that's the same for all users
 * 
 * CRITICAL: This function is now async because encryptChatKeyWithMasterKey is async.
 * All callers must await this function to prevent storing Promises in IndexedDB.
 */
export async function encryptChatForStorage(
    dbInstance: ChatDatabaseInstance,
    chat: Chat
): Promise<Chat> {
    // Skip encryption entirely for public chats (demo + legal) - they're public content
    // Add null check to prevent TypeError when chat.chat_id is undefined
    if (chat.chat_id && (chat.chat_id.startsWith('demo-') || chat.chat_id.startsWith('legal-'))) {
        console.debug(`[ChatDatabase] Skipping encryption for public chat: ${chat.chat_id}`);
        return { ...chat }; // Return as-is without encryption
    }

    const encryptedChat = { ...chat };
    
    // Title is already encrypted in the chat object (encrypted_title field)
    // No need to encrypt again - just ensure it's properly set
    if (chat.encrypted_title) {
        encryptedChat.encrypted_title = chat.encrypted_title;
    }
    
    // Icon is already encrypted in the chat object (encrypted_icon field)
    // No need to encrypt again - just ensure it's properly set
    if (chat.encrypted_icon) {
        encryptedChat.encrypted_icon = chat.encrypted_icon;
    }
    
    // Category is already encrypted in the chat object (encrypted_category field)
    // No need to encrypt again - just ensure it's properly set
    if (chat.encrypted_category) {
        encryptedChat.encrypted_category = chat.encrypted_category;
    }
    
    // Handle chat-specific encryption key
    // CRITICAL: If chat already has encrypted_chat_key from server, decrypt and cache it
    // Only generate new key if this is a brand new chat without a key
    // Add null check for chat.chat_id to prevent errors
    if (!chat.chat_id) {
        console.error('[ChatDatabase] Cannot encrypt chat - chat_id is undefined');
        return encryptedChat;
    }

    let chatKey = dbInstance.getChatKey(chat.chat_id);
    if (!chatKey && chat.encrypted_chat_key) {
        // Decrypt the server-provided key and cache it
        // CRITICAL FIX: await decryptChatKeyWithMasterKey since it's async
        chatKey = await decryptChatKeyWithMasterKey(chat.encrypted_chat_key);
        if (chatKey) {
            dbInstance.setChatKey(chat.chat_id, chatKey);
            encryptedChat.encrypted_chat_key = chat.encrypted_chat_key; // Keep the server's encrypted key
        } else {
            console.error(`[ChatDatabase] Failed to decrypt chat key for chat ${chat.chat_id}`);
        }
    } else if (!chatKey) {
        // No cached key and no server key - generate new one (new chat creation)
        console.log(`[ChatDatabase] Generating NEW chat key for chat ${chat.chat_id} (new chat creation)`);
        chatKey = generateChatKey();
        dbInstance.setChatKey(chat.chat_id, chatKey);
        // CRITICAL FIX: await the async encryption function to prevent storing a Promise in IndexedDB
        const encryptedChatKey = await encryptChatKeyWithMasterKey(chatKey);
        if (encryptedChatKey) {
            encryptedChat.encrypted_chat_key = encryptedChatKey;
            console.log(`[ChatDatabase] ✅ Generated and stored encrypted_chat_key for new chat ${chat.chat_id}: ${encryptedChatKey.substring(0, 20)}... (length: ${encryptedChatKey.length})`);
        } else {
            console.error(`[ChatDatabase] ❌ Failed to encrypt chat key for new chat ${chat.chat_id} - master key may be missing`);
        }
    } else {
        // Key already in cache - make sure encrypted version is in the chat object
        if (!chat.encrypted_chat_key) {
            // CRITICAL FIX: await the async encryption function to prevent storing a Promise in IndexedDB
            const encryptedChatKey = await encryptChatKeyWithMasterKey(chatKey);
            if (encryptedChatKey) {
                encryptedChat.encrypted_chat_key = encryptedChatKey;
            }
        } else {
            encryptedChat.encrypted_chat_key = chat.encrypted_chat_key;
        }
    }
    
    // TODO: Add encryption for new fields when implemented:
    // - encrypted_chat_summary (from post-processing)
    // - encrypted_chat_tags (from post-processing)
    // - encrypted_follow_up_request_suggestions (from post-processing)
    
    // Note: encrypted_draft_md is already encrypted by the draft service, so we don't encrypt it again
    
    return encryptedChat;
}

/**
 * Decrypt chat data after loading from IndexedDB
 * EXCEPTION: Public chats (chat_id starting with 'demo-' or 'legal-') are NOT decrypted
 * since they're stored as plaintext (public template content)
 */
export async function decryptChatFromStorage(
    dbInstance: ChatDatabaseInstance,
    chat: Chat
): Promise<Chat> {
    // Skip decryption entirely for public chats (demo + legal) - they're stored as plaintext
    if (chat.chat_id.startsWith('demo-') || chat.chat_id.startsWith('legal-')) {
        console.debug(`[ChatDatabase] Skipping decryption for public chat: ${chat.chat_id}`);
        return { ...chat }; // Return as-is without decryption
    }
    
    const decryptedChat = { ...chat };
    
    // Ensure required fields have default values if they're undefined
    // This handles cases where older database records might not have these fields
    // Note: Version fields should never be undefined since addChat() ensures defaults
    // But keep fallbacks for safety (e.g., old data from before the fix, or direct DB manipulation)
    if (decryptedChat.messages_v === undefined) {
        decryptedChat.messages_v = 0;
    }
    if (decryptedChat.title_v === undefined) {
        decryptedChat.title_v = 0;
    }
    if (decryptedChat.draft_v === undefined) {
        decryptedChat.draft_v = 0;
    }
    
    // Title decryption is handled by the UI layer when needed
    // The database layer just stores encrypted titles
    // No need to decrypt here as the UI will handle decryption on demand

    // Handle decryption of new encrypted fields with chat-specific key
    if (chat.encrypted_chat_key) {
        // CRITICAL: Always clear is_hidden flags first to ensure fresh state
        // This prevents chats encrypted with a different code from showing up when unlocked with a new code
        (decryptedChat as any).is_hidden = false;
        (decryptedChat as any).is_hidden_candidate = false;
        
        // Always check the decryption path to determine if chat is hidden, even if we have a cached key
        // This ensures hidden chats are properly identified and filtered
        const { hiddenChatService } = await import('../hiddenChatService');
        const result = await hiddenChatService.tryDecryptChatKey(chat.encrypted_chat_key);

        // If normal decryption fails, mark as a hidden candidate for UI filtering.
        // This keeps locked hidden chats out of the main list without a DB flag.
        if (result.isHiddenCandidate) {
            (decryptedChat as any).is_hidden_candidate = true;
        }
        
        if (result.chatKey) {
            // Cache the key (update cache even if it was already cached)
            dbInstance.setChatKey(chat.chat_id, result.chatKey);
            // Mark chat as hidden ONLY if it was decrypted via the hidden path (i.e., unlocked with current password)
            // This ensures only chats that can be decrypted with the current password show up in hidden section
            if (result.isHidden) {
                (decryptedChat as any).is_hidden = true;
            } else {
                // Explicitly mark as not hidden if decrypted via normal path
                (decryptedChat as any).is_hidden = false;
            }
        } else {
            // Both decryption paths failed - could be corrupted or a locked hidden chat
            // OR a hidden chat encrypted with a different password (can't decrypt with current password)
            console.debug(`[ChatDatabase] Failed to decrypt chat key for chat ${chat.chat_id} (both normal and hidden paths failed)`);
            // Clear any cached key since decryption failed
            dbInstance.clearChatKey(chat.chat_id);
            // is_hidden is already false from the initial clear above
        }
        
        // Note: We don't decrypt icon and category here because they should be decrypted
        // on-demand by the UI layer when needed, not stored as part of the Chat object.
        // The Chat object should only contain the encrypted fields for zero-knowledge architecture.
        
        // TODO: Add decryption for other new fields when implemented:
        // - encrypted_chat_summary -> decrypted chat_summary
        // - encrypted_chat_tags -> decrypted chat_tags
        // - encrypted_follow_up_request_suggestions -> decrypted follow_up_request_suggestions
    }
    
    // Note: encrypted_draft_md and encrypted_draft_preview are already encrypted by the draft service 
    // and should be decrypted by the draft service or cache. The database just stores them as-is.
    // Make sure these fields are preserved in the returned chat object.
    
    return decryptedChat;
}

// ============================================================================
// CHAT CRUD OPERATIONS
// ============================================================================

/**
 * Add or update a chat in the database
 */
export async function addChat(
    dbInstance: ChatDatabaseInstance,
    chat: Chat,
    transaction?: IDBTransaction
): Promise<void> {
    console.debug(`[ChatDatabase] addChat called for chat ${chat.chat_id} with transaction: ${!!transaction}`);
    await dbInstance.init();
    
    // CRITICAL FIX: Ensure draft_v always defaults to 0 if undefined
    // This prevents warnings during decryption and ensures consistency
    // CRITICAL FIX: Ensure last_edited_overall_timestamp exists for getAllChats index query
    // If missing, fall back to updated_at (which always exists from server)
    const chatWithDefaults: Chat = {
        ...chat,
        draft_v: chat.draft_v ?? 0,  // Default to 0 if undefined
        title_v: chat.title_v ?? 0,  // Also ensure title_v has a default
        messages_v: chat.messages_v ?? 0,  // And messages_v
        last_edited_overall_timestamp: chat.last_edited_overall_timestamp ?? chat.updated_at ?? Math.floor(Date.now() / 1000)
    };
    
    // CRITICAL FIX: For external transactions, we need to do async work BEFORE checking transaction state
    // because IndexedDB transactions auto-commit when there are no pending operations
    // If we do async work after receiving the transaction, it might finish before we use it
    const usesExternalTransaction = !!transaction;
    
    // CRITICAL FIX: Do async encryption work BEFORE using the transaction
    // This ensures the transaction is still active when we try to use it
    const chatToSave = await encryptChatForStorage(dbInstance, chatWithDefaults);
    delete (chatToSave as any).messages;

    return new Promise(async (resolve, reject) => {
        // CRITICAL FIX: Check if external transaction is still active before using it
        if (usesExternalTransaction && transaction) {
            // Check transaction state - if it's finished, we need to create a new one
            try {
                // Try to access the transaction's mode - if it throws, the transaction is finished
                const _ = transaction.mode;
                // Also check if transaction is still active by checking error property
                if (transaction.error !== null) {
                    throw new Error(`Transaction has error: ${transaction.error}`);
                }
            } catch (error) {
                console.warn(`[ChatDatabase] External transaction is no longer active for chat ${chatToSave.chat_id}, creating new transaction`);
                // Transaction is finished, create a new one
                const newTransaction = await dbInstance.getTransaction(dbInstance.CHATS_STORE_NAME, 'readwrite');
                
                // CRITICAL FIX: Set up transaction handlers BEFORE queuing any operations
                newTransaction.oncomplete = () => {
                    console.debug("[ChatDatabase] ✅ New transaction for addChat completed successfully for chat:", chatToSave.chat_id);
                    resolve();
                };
                
                newTransaction.onerror = () => {
                    console.error("[ChatDatabase] ❌ New transaction for addChat failed for chat:", chatToSave.chat_id, "Error:", newTransaction.error);
                    reject(newTransaction.error);
                };
                
                newTransaction.onabort = () => {
                    console.error("[ChatDatabase] ❌ New transaction for addChat aborted for chat:", chatToSave.chat_id);
                    reject(new Error('Transaction aborted'));
                };
                
                const store = newTransaction.objectStore(dbInstance.CHATS_STORE_NAME);
                const request = store.put(chatToSave);
                
                request.onsuccess = () => {
                    console.debug("[ChatDatabase] Chat put request successful (queued):", chatToSave.chat_id, "Versions:", {m: chatToSave.messages_v, t: chatToSave.title_v, d: chatToSave.draft_v});
                    // resolve() is called in oncomplete handler above
                };
                
                request.onerror = () => {
                    console.error("[ChatDatabase] Error in chat store.put operation:", request.error);
                    // Transaction will abort and onerror/onabort will be called
                };
                
                return;
            }
        }
        
        const currentTransaction = transaction || await dbInstance.getTransaction(dbInstance.CHATS_STORE_NAME, 'readwrite');
        
        console.debug(`[ChatDatabase] Using ${usesExternalTransaction ? 'external' : 'internal'} transaction for chat ${chatToSave.chat_id}`);
        
        // CRITICAL FIX: Check transaction state one more time right before using it
        try {
            // CRITICAL FIX: Set up transaction handlers BEFORE queuing any operations
            // This prevents a race condition where the transaction auto-commits before we set handlers
            if (!usesExternalTransaction) {
                currentTransaction.oncomplete = () => {
                    console.debug("[ChatDatabase] ✅ Transaction for addChat completed successfully for chat:", chatToSave.chat_id);
                    resolve();
                };
                currentTransaction.onerror = () => {
                    const error = currentTransaction.error;
                    const errorName = error instanceof DOMException ? error.name : 'Unknown';
                    const errorMessage = error?.message || 'Unknown error';
                    console.error(`[ChatDatabase] ❌ Transaction for addChat failed for chat: ${chatToSave.chat_id}, Error: ${errorName} - ${errorMessage}`, error);
                    reject(error || new Error('Transaction error'));
                };
                currentTransaction.onabort = () => {
                    const error = currentTransaction.error;
                    const errorName = error instanceof DOMException ? error.name : 'Unknown';
                    const errorMessage = error?.message || 'Unknown reason';
                    console.error(`[ChatDatabase] ❌ Transaction for addChat aborted for chat: ${chatToSave.chat_id}, Error: ${errorName} - ${errorMessage}`, error);
                    
                    // Check for QuotaExceededError - this is critical and should be logged prominently
                    if (error instanceof DOMException && error.name === 'QuotaExceededError') {
                        console.error(`[ChatDatabase] ❌❌❌ CRITICAL: QuotaExceededError when saving chat ${chatToSave.chat_id}! IndexedDB storage quota exceeded!`);
                    }
                    
                    reject(error || new Error(`Transaction aborted: ${errorMessage}`));
                };
            }
            
            const store = currentTransaction.objectStore(dbInstance.CHATS_STORE_NAME);
            const request = store.put(chatToSave);
            
            console.debug(`[ChatDatabase] IndexedDB put request initiated for chat ${chatToSave.chat_id}`);

            request.onsuccess = () => {
                console.debug("[ChatDatabase] Chat put request successful (queued):", chatToSave.chat_id, "Versions:", {m: chatToSave.messages_v, t: chatToSave.title_v, d: chatToSave.draft_v});
                if (usesExternalTransaction) {
                    console.debug(`[ChatDatabase] External transaction - operation queued for chat ${chatToSave.chat_id}`);
                    // CRITICAL FIX: Don't resolve yet! The transaction might not be committed.
                    // The calling code should wait for transaction.oncomplete
                    resolve(); // Resolve to indicate the operation was queued successfully
                }
                // For internal transactions, resolve() is called in oncomplete handler above
            };
            request.onerror = () => {
                const error = request.error;
                const errorName = error instanceof DOMException ? error.name : 'Unknown';
                const errorMessage = error?.message || 'Unknown error';
                console.error(`[ChatDatabase] ❌ Error in chat store.put operation for ${chatToSave.chat_id}: ${errorName} - ${errorMessage}`, error);
                
                // Check for QuotaExceededError - this is critical
                if (error instanceof DOMException && error.name === 'QuotaExceededError') {
                    console.error(`[ChatDatabase] ❌❌❌ CRITICAL: QuotaExceededError when saving chat ${chatToSave.chat_id}! IndexedDB storage quota exceeded!`);
                }
                
                reject(error); // This will also cause the transaction to abort if not handled
            };
        } catch (error: any) {
            // Transaction is no longer active (InvalidStateError or similar)
            if (error?.name === 'InvalidStateError' || error?.message?.includes('transaction')) {
                console.warn(`[ChatDatabase] Transaction is no longer active for chat ${chatToSave.chat_id}, creating new transaction:`, error);
                // Create a new transaction and retry
                try {
                    const newTransaction = await dbInstance.getTransaction(dbInstance.CHATS_STORE_NAME, 'readwrite');
                    
                    // CRITICAL FIX: Set up transaction handlers BEFORE queuing any operations
                    newTransaction.oncomplete = () => {
                        console.debug("[ChatDatabase] ✅ New transaction for addChat completed successfully for chat:", chatToSave.chat_id);
                        resolve();
                    };
                    
                    newTransaction.onerror = () => {
                        console.error("[ChatDatabase] ❌ New transaction for addChat failed for chat:", chatToSave.chat_id, "Error:", newTransaction.error);
                        reject(newTransaction.error);
                    };
                    
                    newTransaction.onabort = () => {
                        console.error("[ChatDatabase] ❌ New transaction for addChat aborted for chat:", chatToSave.chat_id);
                        reject(new Error('Transaction aborted'));
                    };
                    
                    const store = newTransaction.objectStore(dbInstance.CHATS_STORE_NAME);
                    const request = store.put(chatToSave);
                    
                    request.onsuccess = () => {
                        console.debug("[ChatDatabase] Chat put request successful with new transaction (queued):", chatToSave.chat_id);
                        // resolve() is called in oncomplete handler above
                    };
                    
                    request.onerror = () => {
                        console.error("[ChatDatabase] Error in chat store.put operation with new transaction:", request.error);
                        // Transaction will abort and onerror/onabort will be called
                    };
                } catch (retryError) {
                    console.error(`[ChatDatabase] Failed to create new transaction for chat ${chatToSave.chat_id}:`, retryError);
                    reject(retryError);
                }
            } else {
                // Some other error - rethrow it
                console.error(`[ChatDatabase] Unexpected error in addChat for chat ${chatToSave.chat_id}:`, error);
                reject(error);
            }
        }
    });
}

/**
 * Get all chats from the database, sorted by last_edited_overall_timestamp (newest first)
 */
export async function getAllChats(
    dbInstance: ChatDatabaseInstance,
    transaction?: IDBTransaction
): Promise<Chat[]> {
    console.debug(`[ChatDatabase] getAllChats called with transaction: ${!!transaction}`);
    await dbInstance.init();
    return new Promise(async (resolve, reject) => {
        const currentTransaction = transaction || await dbInstance.getTransaction(dbInstance.CHATS_STORE_NAME, 'readonly');
        const store = currentTransaction.objectStore(dbInstance.CHATS_STORE_NAME);
        const index = store.index('last_edited_overall_timestamp');
        const request = index.openCursor(null, 'prev');
        const rawChats: any[] = []; // Collect raw chat data synchronously
     
        request.onsuccess = () => {
            const cursor = request.result;
            if (cursor) {
                // Collect raw chat data synchronously (transaction must stay active)
                const chatData = { ...cursor.value };
                delete (chatData as any).messages;
                rawChats.push(chatData);
                cursor.continue();
            } else {
                // All cursors processed, now decrypt all chats after transaction completes
                // This ensures the transaction doesn't finish while we're still using the cursor
                currentTransaction.oncomplete = async () => {
                    // Decrypt all chats after transaction completes
                    const decryptedChats: Chat[] = [];
                    for (const rawChat of rawChats) {
                        try {
                            const decryptedChat = await decryptChatFromStorage(dbInstance, rawChat);
                            decryptedChats.push(decryptedChat);
                        } catch (error) {
                            console.error(`[ChatDatabase] Error decrypting chat ${rawChat.chat_id}:`, error);
                            // Still include the chat even if decryption fails (with encrypted data)
                            decryptedChats.push(rawChat as Chat);
                        }
                    }
                    console.debug(`[ChatDatabase] Retrieved ${decryptedChats.length} chats from database`);
                    resolve(decryptedChats);
                };
            }
        };
        request.onerror = () => {
            console.error("[ChatDatabase] Error getting chats:", request.error);
            reject(request.error);
        };
        // Note: oncomplete handler is set inside request.onsuccess to handle decryption
        // Only set error handler if we're not using an external transaction
        if (!transaction) {
            currentTransaction.onerror = () => {
                console.error(`[ChatDatabase] getAllChats transaction failed:`, currentTransaction.error);
                reject(currentTransaction.error);
            };
        }
    });
}

/**
 * Get a single chat by ID
 */
export async function getChat(
    dbInstance: ChatDatabaseInstance,
    chat_id: string,
    transaction?: IDBTransaction
): Promise<Chat | null> {
    // CRITICAL: During forced logout (missing master key), only allow loading public chats (demo/legal)
    // Encrypted user chats cannot be decrypted without the master key, so return null to prevent errors
    const isPublicChat = chat_id.startsWith('demo-') || chat_id.startsWith('legal-');
    if (get(forcedLogoutInProgress) && !isPublicChat) {
        console.debug(`[ChatDatabase] Skipping getChat for encrypted chat ${chat_id} during forced logout - returning null`);
        return null;
    }
    
    await dbInstance.init();
    return new Promise(async (resolve, reject) => {
        try {
            const currentTransaction = transaction || await dbInstance.getTransaction(dbInstance.CHATS_STORE_NAME, 'readonly');
            const store = currentTransaction.objectStore(dbInstance.CHATS_STORE_NAME);
            const request = store.get(chat_id);
            
            request.onsuccess = async () => {
                const chatData = request.result;
                if (chatData) {
                    delete (chatData as any).messages; // Ensure messages property is not returned
                    const decryptedChat = await decryptChatFromStorage(dbInstance, chatData);
                    resolve(decryptedChat);
                } else {
                    resolve(null);
                }
            };
            request.onerror = () => {
                console.error(`[ChatDatabase] Error getting chat ${chat_id}:`, request.error);
                reject(request.error);
            };
        } catch (error) {
            console.error(`[ChatDatabase] Error in getChat for chat_id ${chat_id}:`, error);
            reject(error);
        }
    });
}

/**
 * Delete a chat and all its messages
 * Also cleans up associated embeds (if not shared with other chats)
 */
export async function deleteChat(
    dbInstance: ChatDatabaseInstance,
    chat_id: string,
    transaction?: IDBTransaction
): Promise<{ deletedEmbedIds: string[] }> {
    await dbInstance.init();
    console.debug(`[ChatDatabase] Deleting chat ${chat_id} and its messages.`);

    // CRITICAL: Clean up embeds associated with this chat
    let deletedEmbedIds: string[] = [];
    
    // Only perform embed cleanup if NO transaction is provided.
    // If a transaction is provided, we cannot safely await without risking transaction timeout (TransactionInactiveError).
    // The caller of batch operations is responsible for pre-cleaning embeds if needed.
    if (!transaction) {
        // This must happen BEFORE the transaction starts to avoid transaction timeout
        // which happens if we await between transaction creation and first request.
        // Import embedStore dynamically to avoid circular dependencies
        try {
            const { embedStore } = await import('../embedStore');
            deletedEmbedIds = await embedStore.deleteEmbedsForChat(chat_id);
            console.debug(`[ChatDatabase] Cleaned up ${deletedEmbedIds.length} embeds for chat ${chat_id}`);
        } catch (embedError) {
            // Log but don't fail the entire deletion - embeds can be orphaned but chat must be deleted
            console.error(`[ChatDatabase] Error cleaning up embeds for chat ${chat_id}:`, embedError);
        }
    }

    const currentTransaction = transaction || await dbInstance.getTransaction([dbInstance.CHATS_STORE_NAME, MESSAGES_STORE_NAME], 'readwrite');
    
    const chatStore = currentTransaction.objectStore(dbInstance.CHATS_STORE_NAME);
    const messagesStore = currentTransaction.objectStore(MESSAGES_STORE_NAME);
    const messagesChatIdIndex = messagesStore.index('chat_id');

    return new Promise((resolve, reject) => {
        // Step 1: Delete the chat entry
        const deleteChatRequest = chatStore.delete(chat_id);
        
        deleteChatRequest.onsuccess = () => {
            console.debug(`[ChatDatabase] Chat entry ${chat_id} deleted from chats store.`);
            
            // Step 2: Delete all messages for this chat
            const deleteMessagesPromises: Promise<void>[] = [];
            const messagesCursorRequest = messagesChatIdIndex.openCursor(IDBKeyRange.only(chat_id));
            
            messagesCursorRequest.onsuccess = (event) => {
                const cursor = (event.target as IDBRequest<IDBCursorWithValue>).result;
                if (cursor) {
                    // Delete this message
                    deleteMessagesPromises.push(new Promise((res, rej) => {
                        const deleteReq = cursor.delete();
                        deleteReq.onsuccess = () => res();
                        deleteReq.onerror = () => rej(deleteReq.error);
                    }));
                    cursor.continue();
                } else {
                    // Cursor is done - wait for all delete operations to complete
                    console.debug(`[ChatDatabase] Found ${deleteMessagesPromises.length} messages to delete for chat ${chat_id}`);
                    Promise.all(deleteMessagesPromises)
                        .then(() => {
                            console.debug(`[ChatDatabase] All messages deleted for chat ${chat_id}`);
                        })
                        .catch(error => {
                            console.error(`[ChatDatabase] Error deleting messages for chat ${chat_id}:`, error);
                            reject(error);
                        });
                }
            };
            
            messagesCursorRequest.onerror = () => {
                console.error(`[ChatDatabase] Error opening cursor for messages of chat ${chat_id}:`, messagesCursorRequest.error);
                reject(messagesCursorRequest.error);
            };
        };
        
        deleteChatRequest.onerror = () => {
            console.error(`[ChatDatabase] Error deleting chat entry ${chat_id}:`, deleteChatRequest.error);
            reject(deleteChatRequest.error);
        };
        
        // Transaction completion handlers
        if (!transaction) {
            currentTransaction.oncomplete = () => {
                console.debug(`[ChatDatabase] Chat ${chat_id} and its messages deleted successfully.`);
                resolve({ deletedEmbedIds });
            };
            currentTransaction.onerror = () => {
                console.error(`[ChatDatabase] Error in deleteChat transaction for ${chat_id}:`, currentTransaction.error);
                reject(currentTransaction.error);
            };
            currentTransaction.onabort = () => {
                console.error(`[ChatDatabase] Transaction aborted for deleteChat ${chat_id}`);
                reject(new Error('Transaction aborted'));
            };
        } else {
            // If part of a larger transaction, let caller handle oncomplete/onerror
            resolve({ deletedEmbedIds });
        }
    });
}

// ============================================================================
// DRAFT OPERATIONS
// ============================================================================

/**
 * Save a draft for the current user's chat
 */
export async function saveCurrentUserChatDraft(
    dbInstance: ChatDatabaseInstance,
    chat_id: string,
    draft_content: string | null,
    draft_preview: string | null = null
): Promise<Chat | null> {
    await dbInstance.init();
    console.debug("[ChatDatabase] Saving current user's encrypted draft for chat:", chat_id);
    
    try {
        // Get the chat first to check if it exists
        const chat = await getChat(dbInstance, chat_id);
        if (!chat) {
            console.warn(`[ChatDatabase] Chat ${chat_id} not found when trying to save draft.`);
            return null;
        }

        const nowTimestamp = Math.floor(Date.now() / 1000);
        const contentChanged = chat.encrypted_draft_md !== draft_content;

        if (contentChanged) {
            chat.draft_v = (chat.draft_v || 0) + 1;
        }
        chat.encrypted_draft_md = draft_content; // Now stores encrypted markdown string
        chat.encrypted_draft_preview = draft_preview; // Store encrypted preview for chat list display
        // CRITICAL: Don't update last_edited_overall_timestamp for drafts
        // Only messages should update this timestamp for proper sorting
        // Chats with drafts will appear at the top via sorting logic, but won't affect message-based sorting
        chat.updated_at = nowTimestamp; // Keep updated_at for internal tracking
        
        console.debug('[ChatDatabase] Saving draft with preview:', {
            chatId: chat_id,
            hasDraftContent: !!draft_content,
            hasPreview: !!draft_preview,
            previewLength: draft_preview?.length || 0,
            draftVersion: chat.draft_v
        });
        
        // Use addChat without external transaction to ensure proper completion
        await addChat(dbInstance, chat);
        console.debug(`[ChatDatabase] Successfully saved draft for chat ${chat_id}`);
        return chat;
    } catch (error) {
        console.error(`[ChatDatabase] Error in saveCurrentUserChatDraft for chat ${chat_id}:`, error);
        throw error;
    }
}

/**
 * Create a new chat with a draft
 */
export async function createNewChatWithCurrentUserDraft(
    dbInstance: ChatDatabaseInstance,
    draft_content: string,
    draft_preview: string | null = null
): Promise<Chat> {
    console.debug(`[ChatDatabase] createNewChatWithCurrentUserDraft called with draft_content length: ${draft_content?.length}, draft_preview length: ${draft_preview?.length}`);
    await dbInstance.init();
    const nowTimestamp = Math.floor(Date.now() / 1000);
    const newChatId = crypto.randomUUID();
    console.debug(`[ChatDatabase] Creating new chat ${newChatId} with current user's draft`);

    const chatToCreate: Chat = {
        chat_id: newChatId,
        encrypted_title: null,
        messages_v: 0,
        title_v: 0,
        draft_v: 1, // Initial draft version
        encrypted_draft_md: draft_content,
        encrypted_draft_preview: draft_preview,
        last_edited_overall_timestamp: nowTimestamp,
        unread_count: 0,
        created_at: nowTimestamp,
        updated_at: nowTimestamp,
    };
    
    console.debug('[ChatDatabase] Creating new chat with draft preview:', {
        chatId: newChatId,
        hasDraftContent: !!draft_content,
        hasPreview: !!draft_preview,
        previewLength: draft_preview?.length || 0,
        hasEncryptedTitle: !!chatToCreate.encrypted_title,
        draftContentLength: draft_content?.length || 0,
        draftPreviewLength: draft_preview?.length || 0
    });
    
    try {
        console.debug(`[ChatDatabase] About to call addChat for new chat ${newChatId}`);
        // Use addChat without external transaction to ensure proper completion
        await addChat(dbInstance, chatToCreate);
        console.debug(`[ChatDatabase] Successfully created new chat ${newChatId} with draft`);
        
        // Verify the chat was actually saved by trying to retrieve it
        console.debug(`[ChatDatabase] Verifying chat ${newChatId} was saved by retrieving it...`);
        const verificationChat = await getChat(dbInstance, newChatId);
        console.debug(`[ChatDatabase] Verification result:`, {
            chatId: newChatId,
            found: !!verificationChat,
            hasEncryptedDraftMd: !!verificationChat?.encrypted_draft_md,
            hasEncryptedDraftPreview: !!verificationChat?.encrypted_draft_preview,
            draftVersion: verificationChat?.draft_v
        });
        
        return chatToCreate;
    } catch (error) {
        console.error(`[ChatDatabase] Error in createNewChatWithCurrentUserDraft for chat ${newChatId}:`, error);
        throw error;
    }
}

/**
 * Clear a draft from a chat
 */
export async function clearCurrentUserChatDraft(
    dbInstance: ChatDatabaseInstance,
    chat_id: string
): Promise<Chat | null> {
    await dbInstance.init();
    try {
        const chat = await getChat(dbInstance, chat_id);
        if (chat) {
            // When clearing a draft, the content becomes null and version should be 0.
            chat.encrypted_draft_md = null;
            chat.encrypted_draft_preview = null; // Clear preview as well
            chat.draft_v = 0; // Reset draft version to 0
            // CRITICAL: Don't update last_edited_overall_timestamp when clearing drafts
            // Only messages should update this timestamp for proper sorting
            // The chat should revert to its position based on last message timestamp
            const nowTimestamp = Math.floor(Date.now() / 1000);
            chat.updated_at = nowTimestamp; // Keep updated_at for internal tracking
            
            // Use addChat without external transaction to ensure proper completion
            await addChat(dbInstance, chat);
            console.debug(`[ChatDatabase] Successfully cleared draft for chat ${chat_id}`);
            return chat;
        }
        return null;
    } catch (error) {
        console.error(`[ChatDatabase] Error in clearCurrentUserChatDraft for chat ${chat_id}:`, error);
        throw error;
    }
}

// ============================================================================
// BATCH/COMBINED OPERATIONS
// ============================================================================

/**
 * Add or update a chat with all its data (chat metadata + messages)
 */
export async function addOrUpdateChatWithFullData(
    dbInstance: ChatDatabaseInstance,
    chatData: Chat,
    messages: Message[] = [],
    transaction?: IDBTransaction,
    saveMessageFn?: (message: Message, tx?: IDBTransaction) => Promise<void>
): Promise<void> {
    await dbInstance.init();
    console.debug("[ChatDatabase] Adding/updating chat with full data:", chatData.chat_id);
    const chatMetadata = { ...chatData };
    delete (chatMetadata as any).messages; // Ensure messages are not part of chat metadata

    if (typeof (chatMetadata.created_at as any) === 'string' || (chatMetadata.created_at as any) instanceof Date) {
        chatMetadata.created_at = Math.floor(new Date(chatMetadata.created_at as any).getTime() / 1000);
    }
    if (typeof (chatMetadata.updated_at as any) === 'string' || (chatMetadata.updated_at as any) instanceof Date) {
        chatMetadata.updated_at = Math.floor(new Date(chatMetadata.updated_at as any).getTime() / 1000);
    }
    if (chatMetadata.encrypted_draft_md === undefined) chatMetadata.encrypted_draft_md = null;
    if (chatMetadata.encrypted_draft_preview === undefined) chatMetadata.encrypted_draft_preview = null;
    if (chatMetadata.draft_v === undefined) chatMetadata.draft_v = 0;

    const currentTransaction = transaction || await dbInstance.getTransaction([dbInstance.CHATS_STORE_NAME, MESSAGES_STORE_NAME], 'readwrite');
    
    const chatPromise = addChat(dbInstance, chatMetadata, currentTransaction);
    const messagePromises = saveMessageFn 
        ? messages.map(msg => saveMessageFn(msg, currentTransaction))
        : [];

    return new Promise<void>((resolve, reject) => {
        Promise.all([chatPromise, ...messagePromises]).then(() => {
            if (!transaction) {
                currentTransaction.oncomplete = () => resolve();
                currentTransaction.onerror = () => reject(currentTransaction.error);
            } else {
                resolve();
            }
        }).catch(error => {
            if (!transaction && currentTransaction.abort) currentTransaction.abort();
            reject(error);
        });
    });
}

