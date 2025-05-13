import type { Chat, Message, ChatListItem, OfflineChange, TiptapJSON, ChatComponentVersions } from '../types/chat';
// Assuming UserChatDraft will be available from draftTypes or moved to a central types location
import type { UserChatDraft } from './drafts/draftTypes';

class ChatDatabase {
    private db: IDBDatabase | null = null;
    private readonly DB_NAME = 'chats_db';
    private readonly CHATS_STORE_NAME = 'chats';
    private readonly USER_DRAFTS_STORE_NAME = 'user_drafts'; // New store for user drafts
    private readonly OFFLINE_CHANGES_STORE_NAME = 'pending_sync_changes';
    // Version incremented due to USER_DRAFTS_STORE_NAME keyPath change
    private readonly VERSION = 4;

    /**
     * Initialize the database
     */
    async init(): Promise<void> {
        console.debug("[ChatDatabase] Initializing database, Version:", this.VERSION);
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
                const transaction = (event.target as IDBOpenDBRequest).transaction;
                
                // Chats store
                if (!db.objectStoreNames.contains(this.CHATS_STORE_NAME)) {
                    const chatStore = db.createObjectStore(this.CHATS_STORE_NAME, { keyPath: 'chat_id' });
                    chatStore.createIndex('last_edited_overall_timestamp', 'last_edited_overall_timestamp', { unique: false });
                    chatStore.createIndex('updatedAt', 'updatedAt', { unique: false });
                } else {
                    const chatStore = transaction?.objectStore(this.CHATS_STORE_NAME);
                    if (chatStore) {
                        if (chatStore.keyPath !== 'chat_id') {
                            console.warn(`[ChatDatabase] Chats store exists with keyPath ${chatStore.keyPath}. Expected chat_id.`);
                        }
                        if (!chatStore.indexNames.contains('last_edited_overall_timestamp')) {
                            chatStore.createIndex('last_edited_overall_timestamp', 'last_edited_overall_timestamp', { unique: false });
                        }
                        if (!chatStore.indexNames.contains('updatedAt')) {
                             chatStore.createIndex('updatedAt', 'updatedAt', { unique: false });
                        }
                    }
                }

                // User Drafts store
                // KeyPath is 'chat_id' as this DB is specific to the current user.
                if (!db.objectStoreNames.contains(this.USER_DRAFTS_STORE_NAME)) {
                    db.createObjectStore(this.USER_DRAFTS_STORE_NAME, { keyPath: 'chat_id' });
                } else {
                    // If store exists, ensure keyPath is correct. If not, it needs migration (delete & recreate for simplicity here).
                    const draftStore = transaction?.objectStore(this.USER_DRAFTS_STORE_NAME);
                    if (draftStore && draftStore.keyPath !== 'chat_id') {
                        console.warn(`[ChatDatabase] ${this.USER_DRAFTS_STORE_NAME} store exists with incorrect keyPath '${draftStore.keyPath}'. Recreating.`);
                        db.deleteObjectStore(this.USER_DRAFTS_STORE_NAME);
                        db.createObjectStore(this.USER_DRAFTS_STORE_NAME, { keyPath: 'chat_id' });
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
                // Removed draft_v from log as it's no longer part of the main Chat object
                console.debug("[ChatDatabase] Chat added/updated successfully:", chat.chat_id, "Versions:", {m: chat.messages_v, t: chat.title_v});
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

    // --- User Draft Store Methods ---

    async addOrUpdateUserChatDraft(draft: UserChatDraft): Promise<void> {
        return new Promise((resolve, reject) => {
            const store = this.getStore(this.USER_DRAFTS_STORE_NAME, 'readwrite');
            const request = store.put(draft);

            request.onsuccess = () => {
                // Removed user_id from log as it's implicit now for client-side DB
                console.debug("[ChatDatabase] User draft added/updated successfully for chat:", draft.chat_id, "version:", draft.version);
                resolve();
            };
            request.onerror = () => {
                console.error("[ChatDatabase] Error adding/updating user draft:", request.error);
                reject(request.error);
            };
        });
    }

    async getUserChatDraft(chat_id: string): Promise<UserChatDraft | null> {
        // user_id is implicit as client DB is user-specific.
        return new Promise((resolve, reject) => {
            const store = this.getStore(this.USER_DRAFTS_STORE_NAME, 'readonly');
            const request = store.get(chat_id); // Keyed by chat_id
            request.onsuccess = () => {
                resolve(request.result || null);
            };
            request.onerror = () => {
                console.error("[ChatDatabase] Error getting user draft for chat_id:", chat_id, request.error);
                reject(request.error);
            };
        });
    }
    
    async saveCurrentUserChatDraft(chat_id: string, draft_content: TiptapJSON | null): Promise<UserChatDraft | null> {
        // user_id is implicit (current user)
        console.debug("[ChatDatabase] Saving current user's draft for chat:", chat_id);
        
        let draft = await this.getUserChatDraft(chat_id); // No user_id needed here
        const nowTimestamp = Math.floor(Date.now() / 1000);

        if (draft) {
            // Only increment version if content has actually changed
            const contentChanged = JSON.stringify(draft.draft_json) !== JSON.stringify(draft_content);
            if (contentChanged) {
                draft.version = (draft.version || 0) + 1;
            }
            draft.draft_json = draft_content;
            draft.last_edited_timestamp = nowTimestamp;
            // user_id is not part of UserChatDraft anymore for client-side storage
        } else {
            // UserChatDraft type no longer has user_id
            draft = {
                chat_id: chat_id,
                draft_json: draft_content,
                version: 1, // Initial version
                last_edited_timestamp: nowTimestamp,
            };
        }
        
        await this.addOrUpdateUserChatDraft(draft);

        // Also update the chat's last_edited_overall_timestamp in the 'chats' store
        const chat = await this.getChat(chat_id);
        if (chat) {
            chat.last_edited_overall_timestamp = nowTimestamp;
            chat.updatedAt = new Date();
            await this.addChat(chat);
        } else {
            console.warn(`[ChatDatabase] Chat ${chat_id} not found when trying to update its last_edited_overall_timestamp after saving draft.`);
        }
        return draft;
    }
    
    async createNewChatWithCurrentUserDraft(draft_content: TiptapJSON): Promise<{chat: Chat, draft: UserChatDraft}> {
        // user_id is implicit
        const now = new Date();
        const nowTimestamp = Math.floor(now.getTime() / 1000);
        const newChatId = crypto.randomUUID();
        console.debug(`[ChatDatabase] Creating new chat ${newChatId} with current user's draft`);

        const chat: Chat = {
            chat_id: newChatId,
            title: this.extractTitleFromContent(draft_content) || 'New Chat',
            messages_v: 0,
            title_v: 0,
            last_edited_overall_timestamp: nowTimestamp,
            unread_count: 0,
            messages: [],
            createdAt: now,
            updatedAt: now,
        };
        await this.addChat(chat);

        const currentUserDraft: UserChatDraft = { // UserChatDraft type no longer has user_id
            chat_id: newChatId,
            draft_json: draft_content,
            version: 1,
            last_edited_timestamp: nowTimestamp,
        };
        await this.addOrUpdateUserChatDraft(currentUserDraft);
        
        return { chat, draft: currentUserDraft };
    }

    async clearCurrentUserChatDraft(chat_id: string): Promise<UserChatDraft | null> {
        // user_id is implicit
        const draft = await this.getUserChatDraft(chat_id); // No user_id needed
        if (draft) {
            draft.draft_json = null;
            draft.version = (draft.version || 0) + 1;
            draft.last_edited_timestamp = Math.floor(Date.now() / 1000);
            await this.addOrUpdateUserChatDraft(draft);

            const chat = await this.getChat(chat_id);
            if (chat) {
                chat.last_edited_overall_timestamp = draft.last_edited_timestamp;
                chat.updatedAt = new Date();
                await this.addChat(chat);
            }
            return draft;
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

    async clearAllChatData(): Promise<void> {
        console.debug("[ChatDatabase] Clearing all chat data (chats, user_drafts, pending_sync_changes).");
        if (!this.db) {
            // If DB not initialized, there's nothing to clear.
            // Or, we could await this.init(), but if it's logout, perhaps it's fine if not init'd.
            console.warn("[ChatDatabase] Database not initialized, skipping clear.");
            return Promise.resolve();
        }

        const storesToClear = [this.CHATS_STORE_NAME, this.USER_DRAFTS_STORE_NAME, this.OFFLINE_CHANGES_STORE_NAME];
        
        return new Promise((resolve, reject) => {
            const transaction = this.db!.transaction(storesToClear, 'readwrite');
            let clearedCount = 0;

            transaction.oncomplete = () => {
                console.debug("[ChatDatabase] All chat data stores cleared successfully.");
                resolve();
            };
            transaction.onerror = (event) => {
                console.error("[ChatDatabase] Error clearing chat data stores:", transaction.error);
                reject(transaction.error);
            };

            storesToClear.forEach(storeName => {
                const store = transaction.objectStore(storeName);
                const request = store.clear();
                request.onsuccess = () => {
                    clearedCount++;
                    // console.debug(`[ChatDatabase] Store ${storeName} cleared.`); // Optional: log per store
                };
                // Individual request errors are handled by transaction.onerror
            });
        });
    }

    /**
     * Deletes the entire chat database.
     */
    async deleteDatabase(): Promise<void> {
        console.debug(`[ChatDatabase] Attempting to delete database: ${this.DB_NAME}`);
        return new Promise((resolve, reject) => {
            if (this.db) {
                this.db.close(); // Close the connection before deleting
                this.db = null;
                console.debug(`[ChatDatabase] Database connection closed for ${this.DB_NAME}.`);
            }

            const request = indexedDB.deleteDatabase(this.DB_NAME);

            request.onsuccess = () => {
                console.debug(`[ChatDatabase] Database ${this.DB_NAME} deleted successfully.`);
                resolve();
            };

            request.onerror = (event) => {
                console.error(`[ChatDatabase] Error deleting database ${this.DB_NAME}:`, (event.target as IDBOpenDBRequest).error);
                reject((event.target as IDBOpenDBRequest).error);
            };

            request.onblocked = (event) => {
                // This event occurs if other tabs have the database open.
                // It's good practice to inform the user or handle this gracefully.
                console.warn(`[ChatDatabase] Deletion of database ${this.DB_NAME} blocked. Close other tabs/connections.`, event);
                // For now, we'll reject, but a more sophisticated app might prompt the user.
                reject(new Error(`Database ${this.DB_NAME} deletion blocked. Please close other tabs using the application and try again.`));
            };
        });
    }
}

export const chatDB = new ChatDatabase();
