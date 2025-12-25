// frontend/packages/ui/src/services/db/newChatSuggestions.ts
// Handles new chat suggestions CRUD operations for the ChatDatabase class.
// These operations are extracted from db.ts for better code organization.

import type { NewChatSuggestion } from '../../types/chat';
import { encryptWithMasterKey, decryptWithMasterKey } from '../cryptoService';

// Type for ChatDatabase instance to avoid circular import
interface ChatDatabaseInstance {
    db: IDBDatabase | null;
    NEW_CHAT_SUGGESTIONS_STORE_NAME: string;
    getAllNewChatSuggestions(includeHidden?: boolean): Promise<NewChatSuggestion[]>;
}

/**
 * Save new chat suggestions (keeps last 50, encrypted with master key)
 */
export async function saveNewChatSuggestions(
    dbInstance: ChatDatabaseInstance,
    suggestions: string[],
    chatId: string
): Promise<void> {
    if (!dbInstance.db) throw new Error('[ChatDatabase] Database not initialized');

    try {
        // First, get existing suggestions to check for duplicates
        const existingSuggestions = await dbInstance.getAllNewChatSuggestions();
        const existingEncryptedSet = new Set(existingSuggestions.map(s => s.encrypted_suggestion));
        
        // Filter out suggestions that already exist (deduplicate)
        // CRITICAL FIX: await encryptWithMasterKey since it's async to prevent storing Promises
        const newSuggestionsToAdd: string[] = [];
        for (const suggestion of suggestions) {
            const encryptedSuggestion = await encryptWithMasterKey(suggestion);
            if (encryptedSuggestion && !existingEncryptedSet.has(encryptedSuggestion)) {
                newSuggestionsToAdd.push(encryptedSuggestion);
            }
        }
        
        if (newSuggestionsToAdd.length === 0) {
            console.debug('[ChatDatabase] No new suggestions to add (all duplicates)');
            return;
        }
        
        console.debug(`[ChatDatabase] Adding ${newSuggestionsToAdd.length}/${suggestions.length} new suggestions (filtered ${suggestions.length - newSuggestionsToAdd.length} duplicates)`);

        const transaction = dbInstance.db.transaction([dbInstance.NEW_CHAT_SUGGESTIONS_STORE_NAME], 'readwrite');
        const store = transaction.objectStore(dbInstance.NEW_CHAT_SUGGESTIONS_STORE_NAME);

        // Encrypt and add new unique suggestions
        const now = Math.floor(Date.now() / 1000);
        for (const encryptedSuggestion of newSuggestionsToAdd) {
            const suggestionRecord: NewChatSuggestion = {
                id: crypto.randomUUID(),
                encrypted_suggestion: encryptedSuggestion,
                chat_id: chatId,
                created_at: now
            };
            store.add(suggestionRecord);
        }

        // Wait for additions to complete
        await new Promise<void>((resolve, reject) => {
            transaction.oncomplete = () => resolve();
            transaction.onerror = () => reject(transaction.error);
        });

        // Get all suggestions sorted by created_at (newest first)
        const allSuggestions = await dbInstance.getAllNewChatSuggestions();

        // Keep only the last 50
        if (allSuggestions.length > 50) {
            const transaction2 = dbInstance.db.transaction([dbInstance.NEW_CHAT_SUGGESTIONS_STORE_NAME], 'readwrite');
            const store2 = transaction2.objectStore(dbInstance.NEW_CHAT_SUGGESTIONS_STORE_NAME);

            // Delete oldest suggestions
            const suggestionsToDelete = allSuggestions.slice(50);
            for (const suggestion of suggestionsToDelete) {
                store2.delete(suggestion.id);
            }

            await new Promise<void>((resolve, reject) => {
                transaction2.oncomplete = () => resolve();
                transaction2.onerror = () => reject(transaction2.error);
            });
        }

        console.debug(`[ChatDatabase] Saved ${newSuggestionsToAdd.length} new chat suggestions, keeping last 50`);
    } catch (error) {
        console.error('[ChatDatabase] Error saving new chat suggestions:', error);
        throw error;
    }
}

/**
 * Save already-encrypted new chat suggestions (for server-synced suggestions from Directus)
 * 
 * CRITICAL FIX: This function now properly handles transaction lifecycle and quota:
 * 1. Get existing suggestions first (separate readonly transaction)
 * 2. Trim to limit BEFORE adding new ones to prevent QuotaExceededError
 * 3. Wait for readonly transaction to complete before opening readwrite transaction
 * 4. Use put() instead of add() to handle any edge cases with duplicate IDs
 * 5. Handle QuotaExceededError gracefully - save in smaller batches or skip
 * 6. Don't throw on transaction errors - log and continue (suggestions are non-critical)
 */
export async function saveEncryptedNewChatSuggestions(
    dbInstance: ChatDatabaseInstance,
    suggestions: NewChatSuggestion[] | string[],
    chatId: string
): Promise<void> {
    if (!dbInstance.db) throw new Error('[ChatDatabase] Database not initialized');

    try {
        // Normalize input: convert string array to NewChatSuggestion array if needed (backward compatibility)
        const normalizedSuggestions: NewChatSuggestion[] = suggestions.map(s => {
            if (typeof s === 'string') {
                // Backward compatibility: generate ID for string-only input
                return {
                    id: crypto.randomUUID(),
                    encrypted_suggestion: s,
                    chat_id: chatId,
                    created_at: Math.floor(Date.now() / 1000)
                };
            }
            return s;
        });

        // First, get existing suggestions to check for duplicates
        // CRITICAL: Wait for this transaction to fully complete before opening another
        const existingSuggestions = await dbInstance.getAllNewChatSuggestions();
        const existingIdSet = new Set(existingSuggestions.map(s => s.id));
        const existingEncryptedSet = new Set(existingSuggestions.map(s => s.encrypted_suggestion));
        
        // Filter out suggestions that already exist (deduplicate by ID or encrypted value)
        const newSuggestionsToAdd: NewChatSuggestion[] = [];
        for (const suggestion of normalizedSuggestions) {
            // Check both ID and encrypted value to avoid duplicates
            if (suggestion.id && !existingIdSet.has(suggestion.id) && 
                suggestion.encrypted_suggestion && !existingEncryptedSet.has(suggestion.encrypted_suggestion)) {
                newSuggestionsToAdd.push(suggestion);
            }
        }
        
        if (newSuggestionsToAdd.length === 0) {
            console.debug('[ChatDatabase] No new suggestions to add (all duplicates)');
            return;
        }
        
        console.debug(`[ChatDatabase] Adding ${newSuggestionsToAdd.length}/${normalizedSuggestions.length} new suggestions (filtered ${normalizedSuggestions.length - newSuggestionsToAdd.length} duplicates)`);

        // CRITICAL FIX: Trim to limit BEFORE adding new suggestions to prevent QuotaExceededError
        const LIMIT = 50;
        const currentCount = existingSuggestions.length;
        
        if (currentCount + newSuggestionsToAdd.length > LIMIT) {
            // Need to trim before adding
            const toDelete = currentCount + newSuggestionsToAdd.length - LIMIT;
            console.debug(`[ChatDatabase] Trimming ${toDelete} oldest suggestions before adding ${newSuggestionsToAdd.length} new ones`);
            await trimSuggestionsToLimit(dbInstance, LIMIT - newSuggestionsToAdd.length);
        }

        // CRITICAL FIX: Small delay to ensure previous readonly transaction is fully released
        await new Promise(resolve => setTimeout(resolve, 10));

        const transaction = dbInstance.db.transaction([dbInstance.NEW_CHAT_SUGGESTIONS_STORE_NAME], 'readwrite');
        const store = transaction.objectStore(dbInstance.NEW_CHAT_SUGGESTIONS_STORE_NAME);

        // Use the suggestions as-is (they already have IDs from the server)
        const records: NewChatSuggestion[] = newSuggestionsToAdd.map(suggestion => ({
            id: suggestion.id,
            encrypted_suggestion: suggestion.encrypted_suggestion,
            chat_id: suggestion.chat_id || chatId,
            created_at: suggestion.created_at || Math.floor(Date.now() / 1000)
        }));

        // CRITICAL: Set up transaction handlers BEFORE starting any operations
        const transactionComplete = new Promise<void>((resolve, reject) => {
            transaction.oncomplete = () => {
                console.debug(`[ChatDatabase] ✅ Transaction completed successfully for ${records.length} suggestions`);
                resolve();
            };
            transaction.onerror = (event) => {
                const target = event.target as IDBRequest;
                const error = target?.error || transaction.error;
                console.error('[ChatDatabase] Transaction error saving suggestions:', error);
                
                if (error instanceof DOMException && error.name === 'QuotaExceededError') {
                    console.error('[ChatDatabase] ❌ QuotaExceededError: IndexedDB storage quota exceeded. Cannot save suggestions.');
                    resolve();
                } else {
                    reject(error || new Error('Transaction error'));
                }
            };
            transaction.onabort = (event) => {
                const target = event.target as IDBTransaction;
                const error = target?.error;
                const errorMessage = error?.message || 'Unknown reason';
                const errorName = error instanceof DOMException ? error.name : 'Unknown';
                
                console.error(`[ChatDatabase] Transaction aborted while saving suggestions. Error: ${errorName} - ${errorMessage}`);
                
                if (error instanceof DOMException && error.name === 'QuotaExceededError') {
                    console.error('[ChatDatabase] ❌ QuotaExceededError: IndexedDB storage quota exceeded. Cannot save suggestions.');
                    resolve();
                } else {
                    reject(new Error(`Transaction aborted: ${errorMessage}`));
                }
            };
        });

        // Queue all put operations synchronously (no await between them)
        for (const record of records) {
            store.put(record);
        }

        console.debug(`[ChatDatabase] All ${records.length} suggestion put operations queued`);

        // Wait for transaction to complete
        await transactionComplete;

        // Final trim to ensure we're at exactly LIMIT (in case of edge cases)
        await trimSuggestionsToLimit(dbInstance, LIMIT);

        console.debug(`[ChatDatabase] ✅ Saved ${newSuggestionsToAdd.length} new encrypted chat suggestions`);
    } catch (error) {
        // Log error but don't throw - suggestions are non-critical and shouldn't break sync
        if (error instanceof DOMException && error.name === 'QuotaExceededError') {
            console.error('[ChatDatabase] ❌ QuotaExceededError saving suggestions (non-fatal): IndexedDB quota exceeded. Sync will continue without suggestions.');
        } else {
            console.error('[ChatDatabase] Error saving encrypted new chat suggestions (non-fatal):', error);
        }
    }
}

/**
 * Trim suggestions to a maximum count (keeps newest)
 */
async function trimSuggestionsToLimit(dbInstance: ChatDatabaseInstance, limit: number): Promise<void> {
    if (!dbInstance.db) return;

    try {
        const allSuggestions = await dbInstance.getAllNewChatSuggestions();
        
        if (allSuggestions.length <= limit) {
            return;
        }

        console.debug(`[ChatDatabase] Trimming suggestions to last ${limit} (current: ${allSuggestions.length})`);
        
        // Small delay to ensure previous transaction is released
        await new Promise(resolve => setTimeout(resolve, 10));

        const transaction = dbInstance.db.transaction([dbInstance.NEW_CHAT_SUGGESTIONS_STORE_NAME], 'readwrite');
        const store = transaction.objectStore(dbInstance.NEW_CHAT_SUGGESTIONS_STORE_NAME);

        // Delete oldest suggestions (allSuggestions is sorted newest first)
        const suggestionsToDelete = allSuggestions.slice(limit);
        for (const suggestion of suggestionsToDelete) {
            store.delete(suggestion.id);
        }

        await new Promise<void>((resolve, reject) => {
            transaction.oncomplete = () => {
                console.debug(`[ChatDatabase] Trimmed ${suggestionsToDelete.length} oldest suggestions`);
                resolve();
            };
            transaction.onerror = () => reject(transaction.error);
            transaction.onabort = () => reject(new Error('Trim transaction aborted'));
        });
    } catch (error) {
        console.error('[ChatDatabase] Error trimming suggestions (non-fatal):', error);
    }
}

/**
 * Get all new chat suggestions (excluding hidden ones by default)
 */
export async function getAllNewChatSuggestions(
    dbInstance: ChatDatabaseInstance,
    includeHidden: boolean = false
): Promise<NewChatSuggestion[]> {
    if (!dbInstance.db) throw new Error('[ChatDatabase] Database not initialized');

    return new Promise((resolve, reject) => {
        const transaction = dbInstance.db!.transaction([dbInstance.NEW_CHAT_SUGGESTIONS_STORE_NAME], 'readonly');
        const store = transaction.objectStore(dbInstance.NEW_CHAT_SUGGESTIONS_STORE_NAME);
        const index = store.index('created_at');
        const request = index.openCursor(null, 'prev'); // Get newest first

        const suggestions: NewChatSuggestion[] = [];
        request.onsuccess = (event) => {
            const cursor = (event.target as IDBRequest<IDBCursorWithValue>).result;
            if (cursor) {
                const suggestion = cursor.value;
                // Only include suggestions that are not hidden (unless includeHidden is true)
                if (includeHidden || !suggestion.is_hidden) {
                    suggestions.push(suggestion);
                }
                cursor.continue();
            } else {
                resolve(suggestions);
            }
        };
        request.onerror = () => reject(request.error);
    });
}

/**
 * Get N random new chat suggestions (decrypted)
 * CRITICAL FIX: decryptWithMasterKey is async, so we must await all decryption operations
 */
export async function getRandomNewChatSuggestions(
    dbInstance: ChatDatabaseInstance,
    count: number = 3
): Promise<string[]> {
    const allSuggestions = await dbInstance.getAllNewChatSuggestions();

    // Decrypt suggestions - CRITICAL: await all async decryption operations
    const decryptionPromises = allSuggestions.map(s => decryptWithMasterKey(s.encrypted_suggestion));
    const decryptedResults = await Promise.all(decryptionPromises);
    
    // Filter out null results (failed decryptions)
    const decryptedSuggestions = decryptedResults.filter((s): s is string => s !== null);

    // Shuffle and return N random suggestions
    const shuffled = decryptedSuggestions.sort(() => Math.random() - 0.5);
    return shuffled.slice(0, Math.min(count, shuffled.length));
}

/**
 * Delete a new chat suggestion by its decrypted text (when user clicks and sends it as a message)
 */
export async function deleteNewChatSuggestionByText(
    dbInstance: ChatDatabaseInstance,
    suggestionText: string
): Promise<boolean> {
    if (!dbInstance.db) throw new Error('[ChatDatabase] Database not initialized');

    try {
        // Encrypt the suggestion text to match against stored encrypted suggestions
        const encryptedText = await encryptWithMasterKey(suggestionText);
        if (!encryptedText) {
            console.error('[ChatDatabase] Failed to encrypt suggestion text for deletion');
            return false;
        }

        // Find the suggestion record that matches the encrypted text
        const allSuggestions = await dbInstance.getAllNewChatSuggestions();
        const suggestionToDelete = allSuggestions.find(s => s.encrypted_suggestion === encryptedText);

        if (!suggestionToDelete) {
            console.warn('[ChatDatabase] Suggestion not found for deletion:', suggestionText);
            return false;
        }

        // Delete the suggestion
        const transaction = dbInstance.db.transaction([dbInstance.NEW_CHAT_SUGGESTIONS_STORE_NAME], 'readwrite');
        const store = transaction.objectStore(dbInstance.NEW_CHAT_SUGGESTIONS_STORE_NAME);
        store.delete(suggestionToDelete.id);

        await new Promise<void>((resolve, reject) => {
            transaction.oncomplete = () => resolve();
            transaction.onerror = () => reject(transaction.error);
        });

        console.debug('[ChatDatabase] Successfully deleted new chat suggestion:', suggestionText);
        return true;
    } catch (error) {
        console.error('[ChatDatabase] Error deleting new chat suggestion:', error);
        return false;
    }
}

/**
 * Delete a new chat suggestion by its ID (for server-initiated deletions)
 */
export async function deleteNewChatSuggestionById(
    dbInstance: ChatDatabaseInstance,
    suggestionId: string
): Promise<boolean> {
    if (!dbInstance.db) throw new Error('[ChatDatabase] Database not initialized');

    try {
        const transaction = dbInstance.db.transaction([dbInstance.NEW_CHAT_SUGGESTIONS_STORE_NAME], 'readwrite');
        const store = transaction.objectStore(dbInstance.NEW_CHAT_SUGGESTIONS_STORE_NAME);
        store.delete(suggestionId);

        await new Promise<void>((resolve, reject) => {
            transaction.oncomplete = () => resolve();
            transaction.onerror = () => reject(transaction.error);
        });

        console.debug('[ChatDatabase] Successfully deleted new chat suggestion by ID:', suggestionId);
        return true;
    } catch (error) {
        console.error('[ChatDatabase] Error deleting new chat suggestion by ID:', error);
        return false;
    }
}

/**
 * Delete a new chat suggestion by its encrypted content (for context menu deletions)
 */
export async function deleteNewChatSuggestionByEncrypted(
    dbInstance: ChatDatabaseInstance,
    encryptedSuggestion: string
): Promise<boolean> {
    if (!dbInstance.db) throw new Error('[ChatDatabase] Database not initialized');

    // Reject empty strings - these indicate default suggestions which don't exist in IndexedDB
    if (!encryptedSuggestion || encryptedSuggestion.trim() === '') {
        console.warn('[ChatDatabase] Cannot delete suggestion with empty encrypted value (default suggestions cannot be deleted)');
        return false;
    }

    try {
        const allSuggestions = await dbInstance.getAllNewChatSuggestions(true); // Include hidden suggestions for deletion
        const suggestionToDelete = allSuggestions.find(s => s.encrypted_suggestion === encryptedSuggestion);

        if (!suggestionToDelete) {
            console.warn('[ChatDatabase] Suggestion with encrypted content not found for deletion');
            return false;
        }

        return await deleteNewChatSuggestionById(dbInstance, suggestionToDelete.id);
    } catch (error) {
        console.error('[ChatDatabase] Error deleting new chat suggestion by encrypted content:', error);
        return false;
    }
}

/**
 * Hide new chat suggestions associated with a specific chat
 */
export async function hideNewChatSuggestionsForChat(
    dbInstance: ChatDatabaseInstance,
    chatId: string
): Promise<void> {
    if (!dbInstance.db) throw new Error('[ChatDatabase] Database not initialized');

    try {
        const allSuggestions = await dbInstance.getAllNewChatSuggestions(true);
        const suggestionsToUpdate = allSuggestions.filter(s => s.chat_id === chatId);

        if (suggestionsToUpdate.length === 0) {
            console.debug('[ChatDatabase] No suggestions found for chat to hide:', chatId);
            return;
        }

        const transaction = dbInstance.db.transaction([dbInstance.NEW_CHAT_SUGGESTIONS_STORE_NAME], 'readwrite');
        const store = transaction.objectStore(dbInstance.NEW_CHAT_SUGGESTIONS_STORE_NAME);

        for (const suggestion of suggestionsToUpdate) {
            const updatedSuggestion = { ...suggestion, is_hidden: true };
            store.put(updatedSuggestion);
        }

        await new Promise<void>((resolve, reject) => {
            transaction.oncomplete = () => resolve();
            transaction.onerror = () => reject(transaction.error);
        });

        console.debug(`[ChatDatabase] Successfully hidden ${suggestionsToUpdate.length} suggestions for chat:`, chatId);
    } catch (error) {
        console.error('[ChatDatabase] Error hiding suggestions for chat:', error);
    }
}

/**
 * Unhide new chat suggestions associated with a specific chat
 */
export async function unhideNewChatSuggestionsForChat(
    dbInstance: ChatDatabaseInstance,
    chatId: string
): Promise<void> {
    if (!dbInstance.db) throw new Error('[ChatDatabase] Database not initialized');

    try {
        const allSuggestions = await dbInstance.getAllNewChatSuggestions(true);
        const suggestionsToUpdate = allSuggestions.filter(s => s.chat_id === chatId);

        if (suggestionsToUpdate.length === 0) {
            console.debug('[ChatDatabase] No suggestions found for chat to unhide:', chatId);
            return;
        }

        const transaction = dbInstance.db.transaction([dbInstance.NEW_CHAT_SUGGESTIONS_STORE_NAME], 'readwrite');
        const store = transaction.objectStore(dbInstance.NEW_CHAT_SUGGESTIONS_STORE_NAME);

        for (const suggestion of suggestionsToUpdate) {
            const updatedSuggestion = { ...suggestion, is_hidden: false };
            store.put(updatedSuggestion);
        }

        await new Promise<void>((resolve, reject) => {
            transaction.oncomplete = () => resolve();
            transaction.onerror = () => reject(transaction.error);
        });

        console.debug(`[ChatDatabase] Successfully unhidden ${suggestionsToUpdate.length} suggestions for chat:`, chatId);
    } catch (error) {
        console.error('[ChatDatabase] Error unhiding suggestions for chat:', error);
    }
}


