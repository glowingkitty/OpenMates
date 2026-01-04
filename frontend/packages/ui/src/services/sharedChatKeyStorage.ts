/**
 * IndexedDB Storage for Shared Chat Encryption Keys
 *
 * This service provides persistent storage for shared chat encryption keys,
 * allowing unauthenticated users to reload the page without losing access
 * to shared chats they've opened.
 *
 * Use Case:
 * When a user opens a shared chat link (e.g., /share/chat/{chatId}#key=...),
 * the encryption key is extracted from the URL fragment and decrypted.
 * Without persistence, this key would be lost on page reload since:
 * - Memory cache (chatDB.chatKeys Map) is cleared on page reload
 * - The URL fragment might not be preserved after navigation to /#chat_id=...
 *
 * Architecture:
 * - Keys are stored in IndexedDB (survives page reloads and tab closures)
 * - Keys are stored as raw Uint8Array bytes (the actual AES key material)
 * - Each entry includes metadata: chat_id, created_at timestamp
 * - On page load, keys are loaded back into the chatDB memory cache
 * - Keys are deleted when the user explicitly deletes the shared chat
 *
 * Security Considerations:
 * - Shared chat keys are NOT wrapped with a master key (unauthenticated users have no master key)
 * - Keys are stored in plaintext in IndexedDB (same security as session cookies)
 * - This is acceptable because:
 *   1. Unauthenticated users have no user-specific secrets to protect
 *   2. The shared chat content is already "semi-public" (shareable via link)
 *   3. XSS could access keys anyway (same as sessionStorage/localStorage)
 *   4. This provides better UX for users exploring shared chats before signup
 */

const DB_NAME = 'openmates_shared_keys';
const DB_VERSION = 1;
const STORE_NAME = 'shared_chat_keys';

/**
 * Entry structure for stored shared chat keys
 */
interface SharedChatKeyEntry {
    /** The chat ID (used as primary key) */
    chat_id: string;
    /** The raw AES key bytes */
    key_bytes: Uint8Array;
    /** Timestamp when the key was stored (Unix seconds) */
    created_at: number;
}

/**
 * Opens the shared keys IndexedDB database, creating it if needed
 * 
 * @returns Promise resolving to the IDBDatabase instance
 */
async function openDB(): Promise<IDBDatabase> {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open(DB_NAME, DB_VERSION);

        request.onerror = () => {
            console.error('[SharedChatKeyStorage] Error opening database:', request.error);
            reject(request.error);
        };
        
        request.onsuccess = () => {
            resolve(request.result);
        };

        request.onupgradeneeded = (event) => {
            console.debug('[SharedChatKeyStorage] Creating/upgrading database');
            const db = (event.target as IDBOpenDBRequest).result;

            // Create object store if it doesn't exist
            if (!db.objectStoreNames.contains(STORE_NAME)) {
                const store = db.createObjectStore(STORE_NAME, { keyPath: 'chat_id' });
                // Add index for created_at (useful for potential cleanup of old keys)
                store.createIndex('created_at', 'created_at', { unique: false });
                console.debug('[SharedChatKeyStorage] Created shared_chat_keys store');
            }
        };
    });
}

/**
 * Saves a shared chat encryption key to IndexedDB
 * 
 * This should be called after successfully decrypting the share link blob
 * and before navigating away from the share page.
 * 
 * @param chatId - The chat ID to store the key for
 * @param keyBytes - The raw AES key bytes (Uint8Array)
 */
export async function saveSharedChatKey(chatId: string, keyBytes: Uint8Array): Promise<void> {
    console.debug(`[SharedChatKeyStorage] Saving key for chat: ${chatId}`);
    
    const db = await openDB();

    return new Promise((resolve, reject) => {
        const transaction = db.transaction([STORE_NAME], 'readwrite');
        const store = transaction.objectStore(STORE_NAME);
        
        const entry: SharedChatKeyEntry = {
            chat_id: chatId,
            key_bytes: keyBytes,
            created_at: Math.floor(Date.now() / 1000)
        };
        
        const request = store.put(entry);

        request.onerror = () => {
            db.close();
            console.error(`[SharedChatKeyStorage] Error saving key for chat ${chatId}:`, request.error);
            reject(request.error);
        };
        
        // Wait for transaction to complete to ensure data is committed
        transaction.oncomplete = () => {
            db.close();
            console.debug(`[SharedChatKeyStorage] Successfully saved key for chat: ${chatId}`);
            resolve();
        };
        
        transaction.onerror = () => {
            db.close();
            console.error(`[SharedChatKeyStorage] Transaction error saving key for chat ${chatId}:`, transaction.error);
            reject(transaction.error);
        };
    });
}

/**
 * Retrieves a shared chat encryption key from IndexedDB
 * 
 * @param chatId - The chat ID to retrieve the key for
 * @returns The key bytes if found, null otherwise
 */
export async function getSharedChatKey(chatId: string): Promise<Uint8Array | null> {
    const db = await openDB();

    return new Promise((resolve, reject) => {
        const transaction = db.transaction([STORE_NAME], 'readonly');
        const store = transaction.objectStore(STORE_NAME);
        const request = store.get(chatId);

        request.onerror = () => {
            db.close();
            console.error(`[SharedChatKeyStorage] Error getting key for chat ${chatId}:`, request.error);
            reject(request.error);
        };
        
        request.onsuccess = () => {
            const result = request.result as SharedChatKeyEntry | undefined;
            if (result?.key_bytes) {
                console.debug(`[SharedChatKeyStorage] Found key for chat: ${chatId}`);
                resolve(result.key_bytes);
            } else {
                console.debug(`[SharedChatKeyStorage] No key found for chat: ${chatId}`);
                resolve(null);
            }
        };

        transaction.oncomplete = () => db.close();
    });
}

/**
 * Retrieves all stored shared chat keys from IndexedDB
 * 
 * Used during database initialization to load all shared chat keys into memory.
 * 
 * @returns Map of chat_id -> key_bytes for all stored keys
 */
export async function getAllSharedChatKeys(): Promise<Map<string, Uint8Array>> {
    const keys = new Map<string, Uint8Array>();
    
    let db: IDBDatabase;
    try {
        db = await openDB();
    } catch {
        // Database might not exist yet (first visit)
        console.debug('[SharedChatKeyStorage] Database not available, returning empty map');
        return keys;
    }

    return new Promise((resolve, reject) => {
        const transaction = db.transaction([STORE_NAME], 'readonly');
        const store = transaction.objectStore(STORE_NAME);
        const request = store.openCursor();

        request.onerror = () => {
            db.close();
            console.error('[SharedChatKeyStorage] Error reading all keys:', request.error);
            reject(request.error);
        };
        
        request.onsuccess = (event) => {
            const cursor = (event.target as IDBRequest<IDBCursorWithValue>).result;
            if (cursor) {
                const entry = cursor.value as SharedChatKeyEntry;
                if (entry.chat_id && entry.key_bytes) {
                    keys.set(entry.chat_id, entry.key_bytes);
                }
                cursor.continue();
            } else {
                // Cursor is done
                db.close();
                console.debug(`[SharedChatKeyStorage] Loaded ${keys.size} shared chat keys`);
                resolve(keys);
            }
        };
    });
}

/**
 * Deletes a shared chat encryption key from IndexedDB
 * 
 * Should be called when:
 * - User explicitly deletes a shared chat from the chat list
 * - Cleaning up old shared chats during session cleanup
 * 
 * @param chatId - The chat ID to delete the key for
 */
export async function deleteSharedChatKey(chatId: string): Promise<void> {
    console.debug(`[SharedChatKeyStorage] Deleting key for chat: ${chatId}`);
    
    let db: IDBDatabase;
    try {
        db = await openDB();
    } catch {
        // Database might not exist, nothing to delete
        console.debug(`[SharedChatKeyStorage] Database not available, nothing to delete for chat: ${chatId}`);
        return;
    }

    return new Promise((resolve, reject) => {
        const transaction = db.transaction([STORE_NAME], 'readwrite');
        const store = transaction.objectStore(STORE_NAME);
        const request = store.delete(chatId);

        request.onerror = () => {
            db.close();
            console.error(`[SharedChatKeyStorage] Error deleting key for chat ${chatId}:`, request.error);
            reject(request.error);
        };
        
        transaction.oncomplete = () => {
            db.close();
            console.debug(`[SharedChatKeyStorage] Successfully deleted key for chat: ${chatId}`);
            resolve();
        };
        
        transaction.onerror = () => {
            db.close();
            // Don't reject on transaction error - key might not exist
            console.debug(`[SharedChatKeyStorage] Transaction completed (key may not have existed) for chat: ${chatId}`);
            resolve();
        };
    });
}

/**
 * Deletes all shared chat keys from IndexedDB
 * 
 * Used during:
 * - User logout (clean slate for next session)
 * - Complete cleanup of shared chats
 * 
 * @returns Number of keys deleted
 */
export async function clearAllSharedChatKeys(): Promise<number> {
    console.debug('[SharedChatKeyStorage] Clearing all shared chat keys');
    
    let db: IDBDatabase;
    try {
        db = await openDB();
    } catch {
        // Database might not exist, nothing to clear
        console.debug('[SharedChatKeyStorage] Database not available, nothing to clear');
        return 0;
    }

    return new Promise((resolve, reject) => {
        const transaction = db.transaction([STORE_NAME], 'readwrite');
        const store = transaction.objectStore(STORE_NAME);
        
        // First count existing entries
        const countRequest = store.count();
        let count = 0;
        
        countRequest.onsuccess = () => {
            count = countRequest.result;
            // Then clear all entries
            const clearRequest = store.clear();
            
            clearRequest.onerror = () => {
                db.close();
                console.error('[SharedChatKeyStorage] Error clearing all keys:', clearRequest.error);
                reject(clearRequest.error);
            };
        };
        
        transaction.oncomplete = () => {
            db.close();
            console.debug(`[SharedChatKeyStorage] Cleared ${count} shared chat keys`);
            resolve(count);
        };
        
        transaction.onerror = () => {
            db.close();
            console.error('[SharedChatKeyStorage] Transaction error clearing keys:', transaction.error);
            reject(transaction.error);
        };
    });
}

/**
 * Checks if any shared chat keys are stored
 * 
 * Useful for quickly checking if there are any shared chats to load
 * without fetching all the keys.
 * 
 * @returns true if at least one shared chat key is stored
 */
export async function hasSharedChatKeys(): Promise<boolean> {
    let db: IDBDatabase;
    try {
        db = await openDB();
    } catch {
        return false;
    }

    return new Promise((resolve, reject) => {
        const transaction = db.transaction([STORE_NAME], 'readonly');
        const store = transaction.objectStore(STORE_NAME);
        const countRequest = store.count();

        countRequest.onerror = () => {
            db.close();
            reject(countRequest.error);
        };
        
        countRequest.onsuccess = () => {
            db.close();
            resolve(countRequest.result > 0);
        };
    });
}

/**
 * Gets list of all stored shared chat IDs (without loading full keys)
 * 
 * Useful for checking which shared chats are available without
 * loading all the key material into memory.
 * 
 * @returns Array of chat IDs that have stored keys
 */
export async function getStoredSharedChatIds(): Promise<string[]> {
    const chatIds: string[] = [];
    
    let db: IDBDatabase;
    try {
        db = await openDB();
    } catch {
        return chatIds;
    }

    return new Promise((resolve, reject) => {
        const transaction = db.transaction([STORE_NAME], 'readonly');
        const store = transaction.objectStore(STORE_NAME);
        const request = store.getAllKeys();

        request.onerror = () => {
            db.close();
            reject(request.error);
        };
        
        request.onsuccess = () => {
            db.close();
            const keys = request.result as string[];
            console.debug(`[SharedChatKeyStorage] Found ${keys.length} stored shared chat IDs`);
            resolve(keys);
        };
    });
}

/**
 * Deletes the entire shared keys database
 * 
 * Used during complete app cleanup (e.g., "delete all local data" option).
 * More thorough than clearAllSharedChatKeys() as it removes the database entirely.
 */
export async function deleteSharedKeysDatabase(): Promise<void> {
    console.debug('[SharedChatKeyStorage] Deleting entire shared keys database');
    
    return new Promise((resolve, reject) => {
        const request = indexedDB.deleteDatabase(DB_NAME);

        request.onerror = () => {
            console.error('[SharedChatKeyStorage] Error deleting database:', request.error);
            reject(request.error);
        };
        
        request.onsuccess = () => {
            console.debug('[SharedChatKeyStorage] Successfully deleted shared keys database');
            resolve();
        };
        
        request.onblocked = () => {
            console.warn('[SharedChatKeyStorage] Database deletion blocked - connections may still be open');
            // Resolve anyway as the database will be deleted once connections close
            resolve();
        };
    });
}

