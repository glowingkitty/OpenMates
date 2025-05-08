import type { Chat, Message, ChatListItem, OfflineChange, TiptapJSON, ChatComponentVersions } from '../types/chat';

class ChatDatabase {
    private db: IDBDatabase | null = null;
    private readonly DB_NAME = 'chats_db';
    private readonly CHATS_STORE_NAME = 'chats';
    private readonly OFFLINE_CHANGES_STORE_NAME = 'pending_sync_changes';
    // Increment version due to schema changes
    private readonly VERSION = 2;

    /**
     * Initialize the database
     */
    async init(): Promise<void> {
        console.debug("[ChatDatabase] Initializing database");
        return new Promise((resolve, reject) => {
            const request = indexedDB.open(this.DB_NAME, this.VERSION);

            request.onerror = () => {
                console.error("[ChatDatabase] Error opening database:", request.error);
                reject(request.error);
            };

            request.onsuccess = () => {
                console.debug("[ChatDatabase] Database opened successfully");
                this.db = request.result;
                resolve();
            };

            request.onupgradeneeded = (event) => {
                console.debug("[ChatDatabase] Database upgrade needed");
                const db = (event.target as IDBOpenDBRequest).result;
                
                // Chats store
                if (!db.objectStoreNames.contains(this.CHATS_STORE_NAME)) {
                    const store = db.createObjectStore(this.CHATS_STORE_NAME, { keyPath: 'chat_id' });
                    store.createIndex('last_edited_overall_timestamp', 'last_edited_overall_timestamp', { unique: false });
                    store.createIndex('updatedAt', 'updatedAt', { unique: false }); // Keep for potential other uses
                } else {
                    // Handle migration if the store exists from v1
                    const store = (event.target as IDBOpenDBRequest).transaction?.objectStore(this.CHATS_STORE_NAME);
                    if (store) {
                        if (store.keyPath !== 'chat_id') {
                            // This is complex: requires migrating data if keyPath changes.
                            // For simplicity, if keyPath was 'id', we might need to delete and recreate.
                            // Or, assume for now that if it exists, it was already 'chat_id' or we accept data loss on upgrade for old 'id'
                            console.warn(`[ChatDatabase] Chats store exists with keyPath ${store.keyPath}. Expected chat_id. Manual migration might be needed if data used 'id'.`);
                            // If we need to change keyPath, we'd delete the store and recreate it.
                            // db.deleteObjectStore(this.CHATS_STORE_NAME);
                            // const newStore = db.createObjectStore(this.CHATS_STORE_NAME, { keyPath: 'chat_id' });
                            // newStore.createIndex('last_edited_overall_timestamp', 'last_edited_overall_timestamp', { unique: false });
                            // newStore.createIndex('updatedAt', 'updatedAt', { unique: false });
                        }
                        if (!store.indexNames.contains('last_edited_overall_timestamp')) {
                            store.createIndex('last_edited_overall_timestamp', 'last_edited_overall_timestamp', { unique: false });
                        }
                        if (!store.indexNames.contains('updatedAt')) {
                             store.createIndex('updatedAt', 'updatedAt', { unique: false });
                        }
                    }
                }

                // Offline changes store
                if (!db.objectStoreNames.contains(this.OFFLINE_CHANGES_STORE_NAME)) {
                    db.createObjectStore(this.OFFLINE_CHANGES_STORE_NAME, { keyPath: 'change_id' });
                }
            };
        });
    }

    private extractTitleFromContent(content: TiptapJSON): string {
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

    async addChat(chat: Chat): Promise<void> {
        return new Promise((resolve, reject) => {
            const store = this.getStore(this.CHATS_STORE_NAME, 'readwrite');
            const request = store.put(chat);

            request.onsuccess = () => {
                console.debug("[ChatDatabase] Chat added/updated successfully:", chat.chat_id, "Versions:", {m: chat.messages_v, d: chat.draft_v, t: chat.title_v});
                resolve();
            };
            request.onerror = () => {
                console.error("[ChatDatabase] Error adding/updating chat:", request.error);
                reject(request.error);
            };
        });
    }
    
    async getAllChats(): Promise<Chat[]> {
        return new Promise((resolve, reject) => {
            const store = this.getStore(this.CHATS_STORE_NAME, 'readonly');
            const index = store.index('last_edited_overall_timestamp');
            // Sort descending by last_edited_overall_timestamp
            const request = index.openCursor(null, 'prev'); 
            const chats: Chat[] = [];
         
            request.onsuccess = () => {
                const cursor = request.result;
                if (cursor) {
                    chats.push(cursor.value);
                    cursor.continue();
                } else {
                    resolve(chats);
                }
            };
            request.onerror = () => {
                console.error("[ChatDatabase] Error getting chats:", request.error);
                reject(request.error);
            };
        });
    }

    async getChat(chat_id: string): Promise<Chat | null> {
        return new Promise((resolve, reject) => {
            const store = this.getStore(this.CHATS_STORE_NAME, 'readonly');
            const request = store.get(chat_id);
            request.onsuccess = () => {
                resolve(request.result || null);
            };
            request.onerror = () => {
                console.error("[ChatDatabase] Error getting chat:", request.error);
                reject(request.error);
            };
        });
    }

    private getStore(storeName: string, mode: IDBTransactionMode): IDBObjectStore {
        if (!this.db) {
            throw new Error('Database not initialized');
        }
        const transaction = this.db.transaction([storeName], mode);
        return transaction.objectStore(storeName);
    }

    async saveChatDraft(chat_id: string, draft_content: TiptapJSON): Promise<Chat | null> {
        console.debug("[ChatDatabase] Saving draft for chat:", chat_id);
        const chat = await this.getChat(chat_id);
        if (!chat) {
            console.error(`[ChatDatabase] Chat not found for saving draft: ${chat_id}`);
            return null;
        }

        chat.draft_content = draft_content;
        chat.draft_v = (chat.draft_v || 0) + 1;
        chat.last_edited_overall_timestamp = Math.floor(Date.now() / 1000);
        chat.updatedAt = new Date();
        
        await this.addChat(chat);
        return chat;
    }
    
    async createNewChatWithDraft(draft_content: TiptapJSON): Promise<Chat> {
        const now = new Date();
        const nowTimestamp = Math.floor(now.getTime() / 1000);
        const newChatId = crypto.randomUUID();
        console.debug(`[ChatDatabase] Generated newChatId: ${newChatId}, Type: ${typeof newChatId}`);

        const chat: Chat = {
            chat_id: newChatId,
            title: this.extractTitleFromContent(draft_content) || 'New Chat',
            draft_content: draft_content,
            messages_v: 0,
            draft_v: 1, // Initial draft
            title_v: 0,
            draft_version_db: 0,
            last_edited_overall_timestamp: nowTimestamp,
            unread_count: 0,
            messages: [],
            createdAt: now,
            updatedAt: now,
        };
        await this.addChat(chat);
        return chat;
    }

    async clearChatDraft(chat_id: string): Promise<Chat | null> {
        const chat = await this.getChat(chat_id);
        if (chat) {
            chat.draft_content = null;
            chat.draft_v = (chat.draft_v || 0) + 1;
            chat.last_edited_overall_timestamp = Math.floor(Date.now() / 1000);
            chat.updatedAt = new Date();
            await this.addChat(chat);
            return chat;
        }
        return null;
    }

    async deleteChat(chat_id: string): Promise<void> {
        const store = this.getStore(this.CHATS_STORE_NAME, 'readwrite');
        const request = store.delete(chat_id);
        return new Promise((resolve, reject) => {
            request.onsuccess = () => resolve();
            request.onerror = () => reject(request.error);
        });
    }

    async addMessageToChat(chat_id: string, message: Message): Promise<Chat | null> {
        const chat = await this.getChat(chat_id);
        if (!chat) {
            console.error(`[ChatDatabase] Chat not found for adding message: ${chat_id}`);
            return null;
        }
        chat.messages = [...chat.messages, message];
        chat.messages_v = (chat.messages_v || 0) + 1;
        chat.last_edited_overall_timestamp = Math.floor(Date.now() / 1000);
        chat.updatedAt = new Date();
        await this.addChat(chat);
        return chat;
    }
    
    // updateChat is essentially addChat due to 'put' behavior
    async updateChat(chat: Chat): Promise<void> {
        return this.addChat(chat);
    }

    async updateMessageInChat(chat_id: string, updatedMessage: Message): Promise<Chat | null> {
        const chat = await this.getChat(chat_id);
        if (!chat) {
            throw new Error(`Chat with ID ${chat_id} not found`);
        }
        const messageIndex = chat.messages.findIndex(m => m.message_id === updatedMessage.message_id);
        if (messageIndex === -1) {
            // If message not found, add it (could be a new message from sync)
             chat.messages.push(updatedMessage);
        } else {
            chat.messages[messageIndex] = updatedMessage;
        }
        // Note: Updating a single message content doesn't typically change messages_v unless it's a new message.
        // messages_v increments when a message is added or deleted.
        // For simplicity, we can update updatedAt and last_edited_overall_timestamp.
        chat.updatedAt = new Date();
        // Only update last_edited_overall_timestamp if this message is the newest
        if (updatedMessage.timestamp > chat.last_edited_overall_timestamp) {
             chat.last_edited_overall_timestamp = updatedMessage.timestamp;
        }
        await this.addChat(chat);
        return chat;
    }

    async addOrUpdateChatWithFullData(chatData: Chat): Promise<void> {
        console.debug("[ChatDatabase] Adding/updating chat with full data:", chatData.chat_id);
        // Ensure timestamps are correctly handled if they are numbers from server
        chatData.createdAt = new Date(chatData.createdAt);
        chatData.updatedAt = new Date(chatData.updatedAt);
        // messages already have numeric timestamps
        return this.addChat(chatData);
    }
    
    async batchUpdateChats(updates: Array<Partial<Chat> & { chat_id: string }>, deletions: string[]): Promise<void> {
        if (!this.db) throw new Error('Database not initialized');
        const transaction = this.db.transaction([this.CHATS_STORE_NAME], 'readwrite');
        const store = transaction.objectStore(this.CHATS_STORE_NAME);

        return new Promise((resolve, reject) => {
            let operationsCompleted = 0;
            const totalOperations = updates.length + deletions.length;

            if (totalOperations === 0) {
                resolve();
                return;
            }

            const onComplete = () => {
                operationsCompleted++;
                if (operationsCompleted === totalOperations) {
                    resolve();
                }
            };
            const onError = (err: Event) => {
                console.error("[ChatDatabase] Error in batch operation:", err);
                // Attempt to reject, but transaction might already be aborted
                try {
                    transaction.abort();
                } catch (e) { /* ignore */ }
                reject(err);
            };

            updates.forEach(async (updateData) => {
                const existing = await this.getChat(updateData.chat_id); // This needs to be within the transaction or use a separate one.
                                                                      // For simplicity, this example fetches outside, then updates.
                                                                      // A more robust solution uses cursors for updates.
                if (existing) {
                    const merged = { ...existing, ...updateData };
                    // Ensure Date objects are correctly handled if timestamps are numbers
                    if (typeof merged.createdAt === 'number') merged.createdAt = new Date(merged.createdAt);
                    if (typeof merged.updatedAt === 'number') merged.updatedAt = new Date(merged.updatedAt);

                    const request = store.put(merged);
                    request.onsuccess = onComplete;
                    request.onerror = onError;
                } else { // New chat from sync
                    const request = store.put(updateData as Chat); // Cast, assuming all required fields are present for new
                    request.onsuccess = onComplete;
                    request.onerror = onError;
                }
            });

            deletions.forEach(chat_id => {
                const request = store.delete(chat_id);
                request.onsuccess = onComplete;
                request.onerror = onError;
            });

            transaction.oncomplete = () => {
                if (operationsCompleted < totalOperations) {
                     console.warn("[ChatDatabase] Batch transaction completed, but not all operations reported success/error individually.");
                }
                // Resolve here if not all individual onsuccess fired but transaction is done.
                // This path might be hit if some operations were no-ops (e.g. putting identical data).
                resolve(); 
            };
            transaction.onerror = (event) => {
                console.error("[ChatDatabase] Batch transaction error:", event);
                reject(event);
            };
        });
    }

    // --- Offline Changes Store Methods ---
    async addOfflineChange(change: OfflineChange): Promise<void> {
        return new Promise((resolve, reject) => {
            const store = this.getStore(this.OFFLINE_CHANGES_STORE_NAME, 'readwrite');
            const request = store.put(change);
            request.onsuccess = () => resolve();
            request.onerror = () => reject(request.error);
        });
    }

    async getOfflineChanges(): Promise<OfflineChange[]> {
        return new Promise((resolve, reject) => {
            const store = this.getStore(this.OFFLINE_CHANGES_STORE_NAME, 'readonly');
            const request = store.getAll();
            request.onsuccess = () => resolve(request.result || []);
            request.onerror = () => reject(request.error);
        });
    }

    async deleteOfflineChange(change_id: string): Promise<void> {
        return new Promise((resolve, reject) => {
            const store = this.getStore(this.OFFLINE_CHANGES_STORE_NAME, 'readwrite');
            const request = store.delete(change_id);
            request.onsuccess = () => resolve();
            request.onerror = () => reject(request.error);
        });
    }

    // --- Component Version and Timestamp Updates ---
    async updateChatComponentVersion(chat_id: string, component: keyof ChatComponentVersions, version: number): Promise<void> {
        const chat = await this.getChat(chat_id);
        if (chat) {
            chat[component] = version;
            chat.updatedAt = new Date();
            await this.addChat(chat);
        }
    }

    async updateChatLastEditedTimestamp(chat_id: string, timestamp: number): Promise<void> {
        const chat = await this.getChat(chat_id);
        if (chat) {
            chat.last_edited_overall_timestamp = timestamp;
            chat.updatedAt = new Date(); // Also update general updatedAt
            await this.addChat(chat);
        }
    }
}

export const chatDB = new ChatDatabase();
