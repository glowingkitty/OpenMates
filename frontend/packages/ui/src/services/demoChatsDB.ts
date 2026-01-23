// frontend/packages/ui/src/services/demoChatsDB.ts
// Separate IndexedDB database for caching community demo chats.
//
// ARCHITECTURE:
// - Separate from `chats_db` (user's encrypted chats)
// - Never deleted during logout/cleanup (unlike `chats_db`)
// - Stores community demo chats for offline support
// - No encryption (public content)
// - Simple CRUD operations for demo chats
//
// This database is initialized separately from the main chatDB and is never
// affected by user logout or database cleanup operations.

import type { Chat, Message } from '../types/chat';

// ============================================================================
// TYPES
// ============================================================================

interface DemoChatRecord {
    chat_id: string;
    chat: Chat;
    messages: Message[];
    created_at: number; // When this was cached
    demo_id: string; // Original server demo_id
}

// ============================================================================
// DEMO CHATS DATABASE CLASS
// ============================================================================

class DemoChatsDB {
    private db: IDBDatabase | null = null;
    private initializationPromise: Promise<void> | null = null;
    private readonly DB_NAME = 'demo_chats_db';
    private readonly VERSION = 1;

    // Store names
    private readonly CHATS_STORE_NAME = 'demo_chats';
    private readonly MESSAGES_STORE_NAME = 'demo_messages';

    // ============================================================================
    // INITIALIZATION
    // ============================================================================

    /**
     * Initialize the demo chats database
     * This is separate from the main chatDB and never blocked during logout
     */
    async init(): Promise<void> {
        if (this.db) return;
        if (this.initializationPromise) return this.initializationPromise;

        this.initializationPromise = new Promise((resolve, reject) => {
            const request = indexedDB.open(this.DB_NAME, this.VERSION);

            request.onupgradeneeded = (event) => {
                const db = (event.target as IDBOpenDBRequest).result;

                // Create object stores if they don't exist
                if (!db.objectStoreNames.contains(this.CHATS_STORE_NAME)) {
                    const chatsStore = db.createObjectStore(this.CHATS_STORE_NAME, { keyPath: 'chat_id' });
                    chatsStore.createIndex('demo_id', 'demo_id', { unique: true });
                    chatsStore.createIndex('created_at', 'created_at');
                }

                if (!db.objectStoreNames.contains(this.MESSAGES_STORE_NAME)) {
                    const messagesStore = db.createObjectStore(this.MESSAGES_STORE_NAME, { keyPath: 'message_id' });
                    messagesStore.createIndex('chat_id', 'chat_id');
                }
            };

            request.onsuccess = () => {
                this.db = request.result;
                console.debug('[DemoChatsDB] Database opened successfully');
                resolve();
            };

            request.onerror = () => {
                console.error('[DemoChatsDB] Failed to open database:', request.error);
                reject(request.error);
            };
        });

        return this.initializationPromise;
    }

    /**
     * Close the database connection
     */
    close(): void {
        if (this.db) {
            this.db.close();
            this.db = null;
            console.debug('[DemoChatsDB] Database closed');
        }
    }

    // ============================================================================
    // TRANSACTION HELPERS
    // ============================================================================

    /**
     * Get a transaction for the specified stores
     */
    private async getTransaction(storeNames: string | string[], mode: IDBTransactionMode = 'readonly'): Promise<IDBTransaction> {
        if (!this.db) {
            await this.init();
        }
        if (!this.db) {
            throw new Error('DemoChatsDB not initialized');
        }
        return this.db.transaction(storeNames, mode);
    }

    // ============================================================================
    // CHAT CRUD OPERATIONS
    // ============================================================================

    /**
     * Store a demo chat and its messages
     */
    async storeDemoChat(demoId: string, chat: Chat, messages: Message[]): Promise<void> {
        await this.init();

        const transaction = await this.getTransaction([this.CHATS_STORE_NAME, this.MESSAGES_STORE_NAME], 'readwrite');

        try {
            // Store chat record
            const chatRecord: DemoChatRecord = {
                chat_id: chat.chat_id,
                chat,
                messages: [], // We store messages separately
                created_at: Date.now(),
                demo_id: demoId
            };

            const chatStore = transaction.objectStore(this.CHATS_STORE_NAME);
            await new Promise<void>((resolve, reject) => {
                const request = chatStore.put(chatRecord);
                request.onsuccess = () => resolve();
                request.onerror = () => reject(request.error);
            });

            // Store messages
            const messageStore = transaction.objectStore(this.MESSAGES_STORE_NAME);
            for (const message of messages) {
                await new Promise<void>((resolve, reject) => {
                    const request = messageStore.put(message);
                    request.onsuccess = () => resolve();
                    request.onerror = () => reject(request.error);
                });
            }

            console.debug(`[DemoChatsDB] Stored demo chat ${demoId} (${chat.chat_id}) with ${messages.length} messages`);
        } catch (error) {
            console.error('[DemoChatsDB] Error storing demo chat:', error);
            throw error;
        }
    }

    /**
     * Get a demo chat by chat_id
     */
    async getDemoChat(chatId: string): Promise<Chat | null> {
        await this.init();

        const transaction = await this.getTransaction(this.CHATS_STORE_NAME, 'readonly');
        const store = transaction.objectStore(this.CHATS_STORE_NAME);

        return new Promise<Chat | null>((resolve, reject) => {
            const request = store.get(chatId);
            request.onsuccess = () => {
                const record = request.result as DemoChatRecord | undefined;
                resolve(record?.chat || null);
            };
            request.onerror = () => reject(request.error);
        });
    }

    /**
     * Get messages for a demo chat
     */
    async getDemoMessages(chatId: string): Promise<Message[]> {
        await this.init();

        const transaction = await this.getTransaction(this.MESSAGES_STORE_NAME, 'readonly');
        const store = transaction.objectStore(this.MESSAGES_STORE_NAME);
        const index = store.index('chat_id');

        return new Promise<Message[]>((resolve, reject) => {
            const request = index.getAll(chatId);
            request.onsuccess = () => {
                const messages = request.result as Message[];
                resolve(messages);
            };
            request.onerror = () => reject(request.error);
        });
    }

    /**
     * Get all cached demo chats
     */
    async getAllDemoChats(): Promise<Chat[]> {
        await this.init();

        const transaction = await this.getTransaction(this.CHATS_STORE_NAME, 'readonly');
        const store = transaction.objectStore(this.CHATS_STORE_NAME);

        return new Promise<Chat[]>((resolve, reject) => {
            const request = store.getAll();
            request.onsuccess = () => {
                const records = request.result as DemoChatRecord[];
                const chats = records.map(record => record.chat);
                console.debug(`[DemoChatsDB] Found ${chats.length} cached demo chats`);
                resolve(chats);
            };
            request.onerror = () => reject(request.error);
        });
    }

    /**
     * Check if a demo chat is cached
     */
    async hasDemoChat(chatId: string): Promise<boolean> {
        await this.init();

        const transaction = await this.getTransaction(this.CHATS_STORE_NAME, 'readonly');
        const store = transaction.objectStore(this.CHATS_STORE_NAME);

        return new Promise<boolean>((resolve, reject) => {
            const request = store.getKey(chatId);
            request.onsuccess = () => {
                resolve(request.result !== undefined);
            };
            request.onerror = () => reject(request.error);
        });
    }

    /**
     * Delete a demo chat and its messages
     */
    async deleteDemoChat(chatId: string): Promise<void> {
        await this.init();

        const transaction = await this.getTransaction([this.CHATS_STORE_NAME, this.MESSAGES_STORE_NAME], 'readwrite');

        try {
            // Delete chat
            const chatStore = transaction.objectStore(this.CHATS_STORE_NAME);
            await new Promise<void>((resolve, reject) => {
                const request = chatStore.delete(chatId);
                request.onsuccess = () => resolve();
                request.onerror = () => reject(request.error);
            });

            // Delete messages
            const messageStore = transaction.objectStore(this.MESSAGES_STORE_NAME);
            const messageIndex = messageStore.index('chat_id');
            const messagesToDelete = await new Promise<string[]>((resolve, reject) => {
                const request = messageIndex.getAllKeys(chatId);
                request.onsuccess = () => resolve(request.result as string[]);
                request.onerror = () => reject(request.error);
            });

            for (const messageId of messagesToDelete) {
                await new Promise<void>((resolve, reject) => {
                    const request = messageStore.delete(messageId);
                    request.onsuccess = () => resolve();
                    request.onerror = () => reject(request.error);
                });
            }

            console.debug(`[DemoChatsDB] Deleted demo chat ${chatId} and ${messagesToDelete.length} messages`);
        } catch (error) {
            console.error('[DemoChatsDB] Error deleting demo chat:', error);
            throw error;
        }
    }

    /**
     * Clear all demo chats (useful for testing or cache invalidation)
     */
    async clearAllDemoChats(): Promise<void> {
        await this.init();

        const transaction = await this.getTransaction([this.CHATS_STORE_NAME, this.MESSAGES_STORE_NAME], 'readwrite');

        try {
            // Clear chats
            const chatStore = transaction.objectStore(this.CHATS_STORE_NAME);
            await new Promise<void>((resolve, reject) => {
                const request = chatStore.clear();
                request.onsuccess = () => resolve();
                request.onerror = () => reject(request.error);
            });

            // Clear messages
            const messageStore = transaction.objectStore(this.MESSAGES_STORE_NAME);
            await new Promise<void>((resolve, reject) => {
                const request = messageStore.clear();
                request.onsuccess = () => resolve();
                request.onerror = () => reject(request.error);
            });

            console.debug('[DemoChatsDB] Cleared all demo chats from cache');
        } catch (error) {
            console.error('[DemoChatsDB] Error clearing demo chats:', error);
            throw error;
        }
    }

    /**
     * Get cache statistics
     */
    async getCacheStats(): Promise<{ chatCount: number; messageCount: number; }> {
        await this.init();

        const transaction = await this.getTransaction([this.CHATS_STORE_NAME, this.MESSAGES_STORE_NAME], 'readonly');

        const chatStore = transaction.objectStore(this.CHATS_STORE_NAME);
        const messageStore = transaction.objectStore(this.MESSAGES_STORE_NAME);

        const [chatCount, messageCount] = await Promise.all([
            new Promise<number>((resolve, reject) => {
                const request = chatStore.count();
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
            }),
            new Promise<number>((resolve, reject) => {
                const request = messageStore.count();
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
            })
        ]);

        return { chatCount, messageCount };
    }
}

// ============================================================================
// SINGLETON INSTANCE
// ============================================================================

/**
 * Singleton instance of DemoChatsDB
 * This ensures we don't create multiple database connections
 */
const demoChatsDB = new DemoChatsDB();

export { demoChatsDB };
export default demoChatsDB;