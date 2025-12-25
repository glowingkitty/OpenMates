// frontend/packages/ui/src/services/db/chatKeyManagement.ts
// Handles chat key management operations for the ChatDatabase class.
// These operations are extracted from db.ts for better code organization.
//
// This module manages the in-memory cache of chat encryption keys and provides
// methods for encrypting/decrypting message fields using chat-specific keys.
// Chat keys are symmetric AES keys that are themselves encrypted with the user's
// master key for zero-knowledge architecture.

import type { Message } from '../../types/chat';
import { 
    generateChatKey, 
    encryptWithChatKey, 
    decryptWithChatKey,
    decryptChatKeyWithMasterKey
} from '../cryptoService';

/**
 * Type for ChatDatabase instance to avoid circular import.
 * This interface defines the minimal required properties from ChatDatabase
 * that this module needs to access.
 */
interface ChatDatabaseInstance {
    db: IDBDatabase | null;
    chatKeys: Map<string, Uint8Array>;
    CHATS_STORE_NAME: string;
    getChat(chatId: string, transaction?: IDBTransaction): Promise<any>;
}

/**
 * Get chat key from cache.
 * If the key is not in cache, returns null. The caller should then either:
 * - Load the key from the database via loadChatKeysFromDatabase
 * - Generate a new key if this is a new chat
 * 
 * @param dbInstance - Reference to the ChatDatabase instance
 * @param chatId - The ID of the chat
 * @returns The chat key if found in cache, null otherwise
 */
export function getChatKey(dbInstance: ChatDatabaseInstance, chatId: string): Uint8Array | null {
    // First check if key is in cache
    const cachedKey = dbInstance.chatKeys.get(chatId);
    if (cachedKey) {
        return cachedKey;
    }
    
    // If not in cache, return null
    // The ChatMetadataCache will handle loading the key when needed
    return null;
}

/**
 * Set chat key in cache.
 * 
 * @param dbInstance - Reference to the ChatDatabase instance
 * @param chatId - The ID of the chat
 * @param chatKey - The chat key to cache
 */
export function setChatKey(dbInstance: ChatDatabaseInstance, chatId: string, chatKey: Uint8Array): void {
    dbInstance.chatKeys.set(chatId, chatKey);
}

/**
 * Clear chat key from cache.
 * Used when locking hidden chats or on logout.
 * 
 * @param dbInstance - Reference to the ChatDatabase instance
 * @param chatId - The ID of the chat whose key should be cleared
 */
export function clearChatKey(dbInstance: ChatDatabaseInstance, chatId: string): void {
    dbInstance.chatKeys.delete(chatId);
}

/**
 * Clear all chat keys from cache.
 * Used on logout to ensure no keys remain in memory.
 * 
 * @param dbInstance - Reference to the ChatDatabase instance
 */
export function clearAllChatKeys(dbInstance: ChatDatabaseInstance): void {
    dbInstance.chatKeys.clear();
}

/**
 * Get or generate chat key for a specific chat.
 * If the key is not in cache, generates a new one and caches it.
 * 
 * WARNING: If generating a new key for an existing chat, decryption of
 * previously encrypted content will fail. Use with caution.
 * 
 * @param dbInstance - Reference to the ChatDatabase instance
 * @param chatId - The ID of the chat
 * @returns The chat key (from cache or newly generated)
 */
export function getOrGenerateChatKey(dbInstance: ChatDatabaseInstance, chatId: string): Uint8Array {
    let chatKey = getChatKey(dbInstance, chatId);
    if (!chatKey) {
        // Try to load chat key from database
        // This is a synchronous method, so we can't await here
        // The loadChatKeysFromDatabase method should have loaded all keys during initialization
        // If not, we'll generate a new key (which might cause decryption issues)
        console.warn(`[ChatDatabase] Chat key not found in cache for chat ${chatId}, generating new key. This may cause decryption issues.`);
        chatKey = generateChatKey();
        setChatKey(dbInstance, chatId, chatKey);
    }
    return chatKey;
}

/**
 * Load chat keys from database into cache.
 * This should be called when the database is initialized to load all chat keys.
 * 
 * NOTE: This method must NOT call init() or any method that calls init() to avoid circular dependency
 * 
 * @param dbInstance - Reference to the ChatDatabase instance
 */
export async function loadChatKeysFromDatabase(dbInstance: ChatDatabaseInstance): Promise<void> {
    // Don't call getAllChats() here as it calls init(), causing a circular dependency!
    // Instead, directly access the database that's already initialized
    if (!dbInstance.db) {
        console.warn('[ChatDatabase] Database not initialized yet, skipping chat key loading');
        return;
    }
    
    return new Promise((resolve) => {
        try {
            const transaction = dbInstance.db!.transaction(dbInstance.CHATS_STORE_NAME, 'readonly');
            const store = transaction.objectStore(dbInstance.CHATS_STORE_NAME);
            const request = store.openCursor();
            
            // CRITICAL FIX: Collect all chat keys to decrypt, then decrypt them after cursor is done
            // Cannot await inside cursor callback because transaction would finish before cursor.continue()
            const keysToDecrypt: Array<{ chatId: string; encryptedKey: string }> = [];
            
            request.onsuccess = (event) => {
                const cursor = (event.target as IDBRequest<IDBCursorWithValue>).result;
                if (cursor) {
                    const chat = cursor.value;
                    if (chat.encrypted_chat_key && !dbInstance.chatKeys.has(chat.chat_id)) {
                        // Collect keys to decrypt after cursor is done
                        keysToDecrypt.push({
                            chatId: chat.chat_id,
                            encryptedKey: chat.encrypted_chat_key
                        });
                    }
                    // Continue cursor synchronously (transaction must stay alive)
                    cursor.continue();
                } else {
                    // Cursor is done - now decrypt all collected keys
                    // This happens after the transaction completes, which is fine
                    (async () => {
                        try {
                            for (const { chatId, encryptedKey } of keysToDecrypt) {
                                try {
                                    // CRITICAL FIX: await decryptChatKeyWithMasterKey since it's async
                                    // This ensures we get a Uint8Array instead of a Promise
                                    const chatKey = await decryptChatKeyWithMasterKey(encryptedKey);
                                    if (chatKey) {
                                        dbInstance.chatKeys.set(chatId, chatKey);
                                    }
                                } catch (decryptError) {
                                    console.error(`[ChatDatabase] Error decrypting chat key for ${chatId}:`, decryptError);
                                }
                            }
                            console.debug(`[ChatDatabase] Loaded ${keysToDecrypt.length} chat keys from database`);
                            resolve();
                        } catch (error) {
                            console.error('[ChatDatabase] Error decrypting chat keys:', error);
                            resolve(); // Don't reject, just resolve to allow init to complete
                        }
                    })();
                }
            };
            
            request.onerror = () => {
                console.error('[ChatDatabase] Error loading chat keys from database:', request.error);
                resolve(); // Don't reject, just resolve to allow init to complete
            };
        } catch (error) {
            console.error('[ChatDatabase] Error in loadChatKeysFromDatabase:', error);
            resolve(); // Don't reject, just resolve to allow init to complete
        }
    });
}

/**
 * Get encrypted chat key for server storage (zero-knowledge architecture).
 * The server needs this to store the encrypted chat key in Directus for device sync.
 * 
 * @param dbInstance - Reference to the ChatDatabase instance
 * @param chatId - The ID of the chat
 * @returns The encrypted chat key string, or null if not found
 */
export async function getEncryptedChatKey(
    dbInstance: ChatDatabaseInstance, 
    chatId: string
): Promise<string | null> {
    try {
        const chat = await dbInstance.getChat(chatId);
        const encryptedKey = chat?.encrypted_chat_key || null;
        if (encryptedKey) {
            console.log(`[ChatDatabase] ✅ Retrieved encrypted_chat_key for chat ${chatId}: ${encryptedKey.substring(0, 20)}... (length: ${encryptedKey.length})`);
        } else {
            console.warn(`[ChatDatabase] ⚠️ No encrypted_chat_key found for chat ${chatId} - chat object:`, chat ? 'exists but missing key' : 'not found');
        }
        return encryptedKey;
    } catch (error) {
        console.error(`[ChatDatabase] ❌ Error getting encrypted chat key for ${chatId}:`, error);
        return null;
    }
}

/**
 * Encrypt message fields with chat-specific key for storage (removes plaintext).
 * EXCEPTION: Public chat messages (chatId starting with 'demo-' or 'legal-') are NOT encrypted
 * since they contain public template content that's the same for all users.
 * 
 * CRITICAL: This function is async because encryptWithChatKey is async.
 * All callers must await this function to prevent storing Promises in IndexedDB.
 * 
 * @param dbInstance - Reference to the ChatDatabase instance
 * @param message - The message to encrypt
 * @param chatId - The ID of the chat the message belongs to
 * @returns A copy of the message with encrypted fields and plaintext removed
 */
export async function encryptMessageFields(
    dbInstance: ChatDatabaseInstance, 
    message: Message, 
    chatId: string
): Promise<Message> {
    // Skip encryption entirely for public chat messages (demo + legal) - they're public content
    if (chatId.startsWith('demo-') || chatId.startsWith('legal-')) {
        console.debug(`[ChatDatabase] Skipping message encryption for public chat: ${chatId}`);
        // For public messages, store content in encrypted_content field (but not actually encrypted)
        const messageToStore = { ...message };
        if (message.content && !message.encrypted_content) {
            messageToStore.encrypted_content = message.content; // Store as plaintext
        }
        return messageToStore;
    }
    
    const encryptedMessage = { ...message };
    const chatKey = getOrGenerateChatKey(dbInstance, chatId);

    // CRITICAL FIX: await all async encryption calls to prevent storing Promises in IndexedDB
    // Encrypt content if present - ZERO-KNOWLEDGE: Remove plaintext content
    if (message.content) {
        // Content is now a markdown string (never Tiptap JSON on server!)
        const contentString = typeof message.content === 'string' ? message.content : JSON.stringify(message.content);
        encryptedMessage.encrypted_content = await encryptWithChatKey(contentString, chatKey);
    }
    // CRITICAL: Always remove plaintext content for zero-knowledge architecture
    // This ensures even undefined/null values are removed from storage
    delete encryptedMessage.content;

    // Encrypt sender_name if present - ZERO-KNOWLEDGE: Remove plaintext sender_name
    if (message.sender_name) {
        encryptedMessage.encrypted_sender_name = await encryptWithChatKey(message.sender_name, chatKey);
    }
    // CRITICAL: Always remove plaintext sender_name for zero-knowledge architecture
    // This ensures even undefined/null values are removed from storage
    delete encryptedMessage.sender_name;

    // Encrypt category if present - ZERO-KNOWLEDGE: Remove plaintext category
    if (message.category) {
        encryptedMessage.encrypted_category = await encryptWithChatKey(message.category, chatKey);
    }
    // CRITICAL: Always remove plaintext category for zero-knowledge architecture
    // This ensures even undefined/null values are removed from storage
    delete encryptedMessage.category;

    // Encrypt model_name if present - ZERO-KNOWLEDGE: Remove plaintext model_name
    if (message.model_name) {
        encryptedMessage.encrypted_model_name = await encryptWithChatKey(message.model_name, chatKey);
    }
    // CRITICAL: Always remove plaintext model_name for zero-knowledge architecture
    delete encryptedMessage.model_name;

    return encryptedMessage;
}

/**
 * Get encrypted fields only (for dual-content approach - preserves original message).
 * CRITICAL: This function is async because encryptWithChatKey is async.
 * All callers must await this function to prevent storing Promises in IndexedDB.
 * 
 * @param dbInstance - Reference to the ChatDatabase instance
 * @param message - The message whose fields should be encrypted
 * @param chatId - The ID of the chat the message belongs to
 * @returns Object containing only the encrypted field values
 */
export async function getEncryptedFields(
    dbInstance: ChatDatabaseInstance,
    message: Message,
    chatId: string
): Promise<{
    encrypted_content?: string;
    encrypted_sender_name?: string;
    encrypted_category?: string;
    encrypted_model_name?: string;
}> {
    const chatKey = getOrGenerateChatKey(dbInstance, chatId);
    const encryptedFields: {
        encrypted_content?: string;
        encrypted_sender_name?: string;
        encrypted_category?: string;
        encrypted_model_name?: string;
    } = {};

    // CRITICAL FIX: await all async encryption calls to prevent storing Promises
    // Encrypt content if present
    if (message.content) {
        const contentString = typeof message.content === 'string' ? message.content : JSON.stringify(message.content);
        encryptedFields.encrypted_content = await encryptWithChatKey(contentString, chatKey);
    }

    // Encrypt sender_name if present
    if (message.sender_name) {
        encryptedFields.encrypted_sender_name = await encryptWithChatKey(message.sender_name, chatKey);
    }

    // Encrypt category if present
    if (message.category) {
        encryptedFields.encrypted_category = await encryptWithChatKey(message.category, chatKey);
    }

    // Encrypt model_name if present
    if (message.model_name) {
        encryptedFields.encrypted_model_name = await encryptWithChatKey(message.model_name, chatKey);
    }

    return encryptedFields;
}

/**
 * Decrypt message fields with chat-specific key.
 * DEFENSIVE: Handles malformed encrypted content from incomplete message sync.
 * EXCEPTION: Public chat messages (chatId starting with 'demo-' or 'legal-') are NOT decrypted
 * since they're stored as plaintext (public template content).
 * 
 * @param dbInstance - Reference to the ChatDatabase instance
 * @param message - The message to decrypt
 * @param chatId - The ID of the chat the message belongs to
 * @returns A copy of the message with decrypted fields and encrypted fields removed
 */
export async function decryptMessageFields(
    dbInstance: ChatDatabaseInstance, 
    message: Message, 
    chatId: string
): Promise<Message> {
    // Skip decryption entirely for public chat messages (demo + legal) - they're stored as plaintext
    if (chatId.startsWith('demo-') || chatId.startsWith('legal-')) {
        console.debug(`[ChatDatabase] Skipping message decryption for public chat: ${chatId}`);
        const messageToReturn = { ...message };
        // For public messages, encrypted_content is actually plaintext - copy to content field
        if (message.encrypted_content && !message.content) {
            messageToReturn.content = message.encrypted_content;
        }
        return messageToReturn;
    }
    
    const decryptedMessage = { ...message };
    const chatKey = getChatKey(dbInstance, chatId);

    if (!chatKey) {
        console.error(
            `[CLIENT_DECRYPT] ❌ CRITICAL: No chat key found for chat ${chatId}, cannot decrypt message fields! ` +
            `Message ID: ${message.message_id}, Role: ${message.role}, Status: ${message.status}, ` +
            `Has encrypted_content: ${!!message.encrypted_content}, ` +
            `Encrypted content length: ${message.encrypted_content?.length || 0}`
        );
        return decryptedMessage;
    }

    // Decrypt content if present
    if (message.encrypted_content) {
        try {
            // Enhanced logging for decryption attempts
            console.log(
                `[CLIENT_DECRYPT] 🔓 Attempting to decrypt message ${message.message_id} ` +
                `(chat: ${chatId}, role: ${message.role}, status: ${message.status}, ` +
                `encrypted_content length: ${message.encrypted_content.length})`
            );
            const decryptedContentString = await decryptWithChatKey(message.encrypted_content, chatKey);
            if (decryptedContentString) {
                // Content is now a markdown string (never Tiptap JSON on server!)
                decryptedMessage.content = decryptedContentString;
                // Clear encrypted field
                delete decryptedMessage.encrypted_content;
                console.log(
                    `[CLIENT_DECRYPT] ✅ Successfully decrypted message ${message.message_id} ` +
                    `(content length: ${decryptedContentString.length} chars)`
                );
            } else {
                // Decryption failed but didn't throw - encrypted_content might be malformed
                console.error(
                    `[CLIENT_DECRYPT] ❌ Failed to decrypt content for message ${message.message_id} - ` +
                    `encrypted_content present but decryption returned null. ` +
                    `This may indicate vault-encrypted content was sent instead of client-encrypted!`
                );
                // Keep encrypted field for debugging, set content to placeholder
                decryptedMessage.content = message.content || '[Content decryption failed]';
            }
        } catch (error) {
            // DEFENSIVE: Handle malformed encrypted_content (e.g., from messages with status 'sending' that never completed encryption)
            console.error(
                `[CLIENT_DECRYPT] ❌ CRITICAL: Error decrypting content for message ${message.message_id} ` +
                `(role: ${message.role}, status: ${message.status}, chat: ${chatId}): ` +
                `${error instanceof Error ? error.message : String(error)}. ` +
                `Encrypted content length: ${message.encrypted_content?.length || 0}, ` +
                `Has plaintext fallback: ${!!message.content}. ` +
                `This may indicate vault-encrypted content was sent instead of client-encrypted!`
            );
            // If message already has plaintext content, use it (common for status='sending')
            if (message.content) {
                console.warn(
                    `[CLIENT_DECRYPT] ⚠️ Using existing plaintext content for message ${message.message_id} - ` +
                    `encryption may not have completed or content was stored incorrectly`
                );
                decryptedMessage.content = message.content;
            } else {
                decryptedMessage.content = '[Content decryption failed]';
            }
            // Keep encrypted_content for debugging
        }
    } else {
        console.debug(
            `[CLIENT_DECRYPT] ⚠️ Message ${message.message_id} has no encrypted_content ` +
            `(chat: ${chatId}, role: ${message.role}, status: ${message.status})`
        );
    }

    // Decrypt sender_name if present
    if (message.encrypted_sender_name) {
        try {
            const decryptedSenderName = await decryptWithChatKey(message.encrypted_sender_name, chatKey);
            if (decryptedSenderName) {
                decryptedMessage.sender_name = decryptedSenderName;
                // Clear encrypted field
                delete decryptedMessage.encrypted_sender_name;
            }
        } catch (error) {
            // DEFENSIVE: Handle malformed encrypted_sender_name
            console.error(`[ChatDatabase] Error decrypting sender_name for message ${message.message_id}:`, error);
            decryptedMessage.sender_name = message.sender_name || 'Unknown';
        }
    }

    // Decrypt category if present
    if (message.encrypted_category) {
        try {
            const decryptedCategory = await decryptWithChatKey(message.encrypted_category, chatKey);
            if (decryptedCategory) {
                decryptedMessage.category = decryptedCategory;
                // Clear encrypted field
                delete decryptedMessage.encrypted_category;
            }
        } catch (error) {
            // DEFENSIVE: Handle malformed encrypted_category
            console.error(`[ChatDatabase] Error decrypting category for message ${message.message_id}:`, error);
            decryptedMessage.category = message.category || undefined;
        }
    }

    // Decrypt model_name if present
    if (message.encrypted_model_name) {
        try {
            const decryptedModelName = await decryptWithChatKey(message.encrypted_model_name, chatKey);
            if (decryptedModelName) {
                decryptedMessage.model_name = decryptedModelName;
                // Clear encrypted field
                delete decryptedMessage.encrypted_model_name;
            }
        } catch (error) {
            console.error(`[ChatDatabase] Error decrypting model_name for message ${message.message_id}:`, error);
            decryptedMessage.model_name = message.model_name || undefined;
        }
    }

    return decryptedMessage;
}


