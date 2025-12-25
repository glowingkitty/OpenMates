// frontend/packages/ui/src/services/db/offlineChangesAndUpdates.ts
// Handles offline changes and chat update operations for the ChatDatabase class.
// These operations are extracted from db.ts for better code organization.
//
// This module contains:
// - Offline changes CRUD operations (for sync queue)
// - Chat component version updates
// - Chat timestamp updates
// - Chat scroll position and read status updates

import type { OfflineChange, ChatComponentVersions } from '../../types/chat';
import * as chatCrudOps from './chatCrudOperations';

// Type for ChatDatabase instance to avoid circular import
// Only includes properties/methods needed by this module
interface ChatDatabaseInstance {
    db: IDBDatabase | null;
    CHATS_STORE_NAME: string;
    init(): Promise<void>;
    getTransaction(storeNames: string | string[], mode: IDBTransactionMode): Promise<IDBTransaction>;
    
    // Chat key management methods (needed for chatCrudOps)
    getChatKey(chatId: string): Uint8Array | null;
    setChatKey(chatId: string, chatKey: Uint8Array): void;
    clearChatKey(chatId: string): void;
}

// Store name constants (must match db.ts)
const OFFLINE_CHANGES_STORE_NAME = 'pending_sync_changes';

// ============================================================================
// OFFLINE CHANGES OPERATIONS
// ============================================================================

/**
 * Add an offline change to the sync queue
 */
export async function addOfflineChange(
    dbInstance: ChatDatabaseInstance,
    change: OfflineChange,
    transaction?: IDBTransaction
): Promise<void> {
    await dbInstance.init();
    const currentTransaction = transaction || await dbInstance.getTransaction(OFFLINE_CHANGES_STORE_NAME, 'readwrite');
    return new Promise((resolve, reject) => {
        const store = currentTransaction.objectStore(OFFLINE_CHANGES_STORE_NAME);
        const request = store.put(change);
        request.onsuccess = () => resolve();
        request.onerror = () => reject(request.error);
        if (!transaction) {
            currentTransaction.oncomplete = () => resolve();
            currentTransaction.onerror = () => reject(currentTransaction.error);
        }
    });
}

/**
 * Get all pending offline changes
 */
export async function getOfflineChanges(
    dbInstance: ChatDatabaseInstance,
    transaction?: IDBTransaction
): Promise<OfflineChange[]> {
    await dbInstance.init();
    const currentTransaction = transaction || await dbInstance.getTransaction(OFFLINE_CHANGES_STORE_NAME, 'readonly');
    return new Promise((resolve, reject) => {
        const store = currentTransaction.objectStore(OFFLINE_CHANGES_STORE_NAME);
        const request = store.getAll();
        request.onsuccess = () => resolve(request.result || []);
        request.onerror = () => reject(request.error);
    });
}

/**
 * Delete an offline change from the sync queue
 */
export async function deleteOfflineChange(
    dbInstance: ChatDatabaseInstance,
    change_id: string,
    transaction?: IDBTransaction
): Promise<void> {
    await dbInstance.init();
    const currentTransaction = transaction || await dbInstance.getTransaction(OFFLINE_CHANGES_STORE_NAME, 'readwrite');
    return new Promise((resolve, reject) => {
        const store = currentTransaction.objectStore(OFFLINE_CHANGES_STORE_NAME);
        const request = store.delete(change_id);
        request.onsuccess = () => resolve();
        request.onerror = () => reject(request.error);
        if (!transaction) {
            currentTransaction.oncomplete = () => resolve();
            currentTransaction.onerror = () => reject(currentTransaction.error);
        }
    });
}

// ============================================================================
// CHAT COMPONENT VERSION UPDATES
// ============================================================================

/**
 * Update a specific component version of a chat (draft_v, messages_v, or title_v)
 * 
 * CRITICAL: This function gets the chat WITHOUT a transaction first to allow
 * async decryption work to complete, then creates a new transaction for the update.
 * This prevents "transaction no longer active" errors that occur when async work
 * (like decryption) happens while a transaction is open.
 */
export async function updateChatComponentVersion(
    dbInstance: ChatDatabaseInstance,
    chat_id: string,
    component: keyof ChatComponentVersions,
    version: number
): Promise<void> {
    await dbInstance.init();
    
    // CRITICAL FIX: Get chat WITHOUT transaction first to allow async decryption
    // If we pass a transaction to getChat, the async decryption work can cause
    // the transaction to finish before we use it in addChat
    const chat = await chatCrudOps.getChat(dbInstance, chat_id);
    
    if (!chat) {
        console.warn(`[ChatDatabase] Chat ${chat_id} not found when updating component version`);
        return;
    }
    
    // Now create a transaction for the update operation
    const tx = await dbInstance.getTransaction(dbInstance.CHATS_STORE_NAME, 'readwrite');
    
    try {
        if (component === 'draft_v') {
            chat.draft_v = version;
        } else if (component === 'messages_v') {
            chat.messages_v = version;
        } else if (component === 'title_v') {
            chat.title_v = version;
        }
        chat.updated_at = Math.floor(Date.now() / 1000);
        await chatCrudOps.addChat(dbInstance, chat, tx);
        
        return new Promise((resolve, reject) => {
            tx.oncomplete = () => resolve();
            tx.onerror = () => reject(tx.error);
        });
    } catch (error) {
        if (tx.abort) tx.abort();
        throw error;
    }
}

/**
 * Update the last edited timestamp for a chat
 * 
 * CRITICAL: This function gets the chat WITHOUT a transaction first to allow
 * async decryption work to complete, then creates a new transaction for the update.
 * This prevents "transaction no longer active" errors that occur when async work
 * (like decryption) happens while a transaction is open.
 */
export async function updateChatLastEditedTimestamp(
    dbInstance: ChatDatabaseInstance,
    chat_id: string,
    timestamp: number
): Promise<void> {
    await dbInstance.init();
    
    // CRITICAL FIX: Get chat WITHOUT transaction first to allow async decryption
    // If we pass a transaction to getChat, the async decryption work can cause
    // the transaction to finish before we use it in addChat
    const chat = await chatCrudOps.getChat(dbInstance, chat_id);
    
    if (!chat) {
        console.warn(`[ChatDatabase] Chat ${chat_id} not found when updating last edited timestamp`);
        return;
    }
    
    // Now create a transaction for the update operation
    const tx = await dbInstance.getTransaction(dbInstance.CHATS_STORE_NAME, 'readwrite');
    
    try {
        chat.last_edited_overall_timestamp = timestamp;
        chat.updated_at = Math.floor(Date.now() / 1000); 
        await chatCrudOps.addChat(dbInstance, chat, tx);
        
        return new Promise((resolve, reject) => {
            tx.oncomplete = () => resolve();
            tx.onerror = () => reject(tx.error);
        });
    } catch (error) {
        if (tx.abort) tx.abort();
        throw error;
    }
}

// ============================================================================
// CHAT SCROLL POSITION AND READ STATUS
// ============================================================================

/**
 * Update the scroll position (last visible message) for a chat
 * 
 * CRITICAL: This function gets the chat WITHOUT a transaction first to allow
 * async decryption work to complete, then creates a new transaction for the update.
 * This prevents "transaction no longer active" errors that occur when async work
 * (like decryption) happens while a transaction is open.
 */
export async function updateChatScrollPosition(
    dbInstance: ChatDatabaseInstance,
    chat_id: string,
    message_id: string
): Promise<void> {
    await dbInstance.init();
    
    // CRITICAL FIX: Get chat WITHOUT transaction first to allow async decryption
    // If we pass a transaction to getChat, the async decryption work can cause
    // the transaction to finish before we use it in addChat
    const chat = await chatCrudOps.getChat(dbInstance, chat_id);
    
    if (!chat) {
        console.warn(`[ChatDatabase] Chat ${chat_id} not found when updating scroll position`);
        return;
    }
    
    // Now create a transaction for the update operation
    const tx = await dbInstance.getTransaction(dbInstance.CHATS_STORE_NAME, 'readwrite');
    
    try {
        chat.last_visible_message_id = message_id;
        chat.updated_at = Math.floor(Date.now() / 1000);
        await chatCrudOps.addChat(dbInstance, chat, tx);
        console.debug(`[ChatDatabase] Updated scroll position for chat ${chat_id}: message ${message_id}`);
        
        return new Promise((resolve, reject) => {
            tx.oncomplete = () => resolve();
            tx.onerror = () => reject(tx.error);
        });
    } catch (error) {
        if (tx.abort) tx.abort();
        throw error;
    }
}

/**
 * Update the read status (unread count) for a chat
 * 
 * CRITICAL: This function gets the chat WITHOUT a transaction first to allow
 * async decryption work to complete, then creates a new transaction for the update.
 * This prevents "transaction no longer active" errors that occur when async work
 * (like decryption) happens while a transaction is open.
 */
export async function updateChatReadStatus(
    dbInstance: ChatDatabaseInstance,
    chat_id: string,
    unread_count: number
): Promise<void> {
    await dbInstance.init();
    
    // CRITICAL FIX: Get chat WITHOUT transaction first to allow async decryption
    // If we pass a transaction to getChat, the async decryption work can cause
    // the transaction to finish before we use it in addChat
    const chat = await chatCrudOps.getChat(dbInstance, chat_id);
    
    if (!chat) {
        console.warn(`[ChatDatabase] Chat ${chat_id} not found when updating read status`);
        return;
    }
    
    // Now create a transaction for the update operation
    const tx = await dbInstance.getTransaction(dbInstance.CHATS_STORE_NAME, 'readwrite');
    
    try {
        chat.unread_count = unread_count;
        chat.updated_at = Math.floor(Date.now() / 1000);
        await chatCrudOps.addChat(dbInstance, chat, tx);
        console.debug(`[ChatDatabase] Updated read status for chat ${chat_id}: unread_count = ${unread_count}`);
        
        return new Promise((resolve, reject) => {
            tx.oncomplete = () => resolve();
            tx.onerror = () => reject(tx.error);
        });
    } catch (error) {
        if (tx.abort) tx.abort();
        throw error;
    }
}

