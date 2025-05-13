// frontend/packages/ui/src/services/db.ts
// Manages IndexedDB storage for chat-related data.
import type { Chat, Message, TiptapJSON, ChatComponentVersions, OfflineChange } from '../types/chat';
// UserChatDraft type is no longer imported as draft info is part of the Chat type.

class ChatDatabase {
    private db: IDBDatabase | null = null;
    private readonly DB_NAME = 'chats_db';
    private readonly CHATS_STORE_NAME = 'chats';
    // USER_DRAFTS_STORE_NAME is removed
    private readonly OFFLINE_CHANGES_STORE_NAME = 'pending_sync_changes';
    // Version incremented due to schema change (removing user_drafts store and adding draft fields to chats store)
    private readonly VERSION = 5; 

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
                            // Potentially recreate or migrate if keyPath is wrong, though this is unlikely for an established store.
                        }
                        if (!chatStore.indexNames.contains('last_edited_overall_timestamp')) {
                            chatStore.createIndex('last_edited_overall_timestamp', 'last_edited_overall_timestamp', { unique: false });
                        }
                        if (!chatStore.indexNames.contains('updatedAt')) {
                             chatStore.createIndex('updatedAt', 'updatedAt', { unique: false });
                        }
                    }
                }

                // Remove User Drafts store if it exists from a previous version
                const oldUserDraftsStoreName = 'user_drafts'; // Keep the old name for deletion
                if (db.objectStoreNames.contains(oldUserDraftsStoreName)) {
                    console.info(`[ChatDatabase] Deleting old store: ${oldUserDraftsStoreName}`);
                    db.deleteObjectStore(oldUserDraftsStoreName);
                }

                // Offline changes store
                if (!db.objectStoreNames.contains(this.OFFLINE_CHANGES_STORE_NAME)) {
                    db.createObjectStore(this.OFFLINE_CHANGES_STORE_NAME, { keyPath: 'change_id' });
                }
            };
        });
    }

    /**
     * Creates a new transaction.
     * @param storeNames The names of the object stores to include in the transaction.
     * @param mode The transaction mode ('readonly' or 'readwrite').
     * @returns The created IDBTransaction.
     */
    public getTransaction(storeNames: string | string[], mode: IDBTransactionMode): IDBTransaction {
        if (!this.db) {
            throw new Error('Database not initialized');
        }
        return this.db.transaction(storeNames, mode);
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

    async addChat(chat: Chat, transaction?: IDBTransaction): Promise<void> {
        return new Promise((resolve, reject) => {
            const currentTransaction = transaction || this.getTransaction(this.CHATS_STORE_NAME, 'readwrite');
            const store = currentTransaction.objectStore(this.CHATS_STORE_NAME);
            const request = store.put(chat);

            request.onsuccess = () => {
                console.debug("[ChatDatabase] Chat added/updated successfully:", chat.chat_id, "Versions:", {m: chat.messages_v, t: chat.title_v, d: chat.draft_v});
                resolve();
            };
            request.onerror = () => {
                console.error("[ChatDatabase] Error adding/updating chat:", request.error);
                reject(request.error);
            };
            if (!transaction) { 
                currentTransaction.oncomplete = () => resolve(); 
                currentTransaction.onerror = () => reject(currentTransaction.error);
            }
        });
    }
    
    async getAllChats(transaction?: IDBTransaction): Promise<Chat[]> {
        return new Promise((resolve, reject) => {
            const currentTransaction = transaction || this.getTransaction(this.CHATS_STORE_NAME, 'readonly');
            const store = currentTransaction.objectStore(this.CHATS_STORE_NAME);
            const index = store.index('last_edited_overall_timestamp');
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
            if (!transaction) { 
                 currentTransaction.oncomplete = () => {
                 };
                currentTransaction.onerror = () => reject(currentTransaction.error);
            }
        });
    }

    async getChat(chat_id: string, transaction?: IDBTransaction): Promise<Chat | null> {
        return new Promise((resolve, reject) => {
            const currentTransaction = transaction || this.getTransaction(this.CHATS_STORE_NAME, 'readonly');
            const store = currentTransaction.objectStore(this.CHATS_STORE_NAME);
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

    async saveCurrentUserChatDraft(chat_id: string, draft_content: TiptapJSON | null): Promise<Chat | null> {
        console.debug("[ChatDatabase] Saving current user's draft for chat:", chat_id);
        
        const tx = this.getTransaction(this.CHATS_STORE_NAME, 'readwrite');
        let updatedChat: Chat | null = null;

        try {
            const chat = await this.getChat(chat_id, tx);
            if (!chat) {
                console.warn(`[ChatDatabase] Chat ${chat_id} not found when trying to save draft.`);
                tx.abort();
                return null;
            }

            const nowTimestamp = Math.floor(Date.now() / 1000);
            const contentChanged = JSON.stringify(chat.draft_json) !== JSON.stringify(draft_content);

            if (contentChanged) {
                chat.draft_v = (chat.draft_v || 0) + 1;
            }
            chat.draft_json = draft_content;
            chat.last_edited_overall_timestamp = nowTimestamp;
            chat.updatedAt = new Date();
            
            await this.addChat(chat, tx);
            updatedChat = chat;
            
            return new Promise((resolve, reject) => {
                tx.oncomplete = () => resolve(updatedChat);
                tx.onerror = () => reject(tx.error);
            });
        } catch (error) {
            console.error(`[ChatDatabase] Error in saveCurrentUserChatDraft transaction for chat ${chat_id}:`, error);
            tx.abort();
            throw error;
        }
    }
    
    async createNewChatWithCurrentUserDraft(draft_content: TiptapJSON): Promise<Chat> {
        const tx = this.getTransaction(this.CHATS_STORE_NAME, 'readwrite');
        const now = new Date();
        const nowTimestamp = Math.floor(now.getTime() / 1000);
        const newChatId = crypto.randomUUID();
        console.debug(`[ChatDatabase] Creating new chat ${newChatId} with current user's draft`);

        const chatToCreate: Chat = {
            chat_id: newChatId,
            title: this.extractTitleFromContent(draft_content) || 'New Chat',
            messages_v: 0,
            title_v: 0,
            draft_v: 1, // Initial draft version
            draft_json: draft_content,
            last_edited_overall_timestamp: nowTimestamp,
            unread_count: 0,
            messages: [],
            createdAt: now,
            updatedAt: now,
        };
        
        try {
            await this.addChat(chatToCreate, tx);

            return new Promise((resolve, reject) => {
                tx.oncomplete = () => resolve(chatToCreate);
                tx.onerror = () => reject(tx.error);
            });
        } catch (error) {
            console.error(`[ChatDatabase] Error in createNewChatWithCurrentUserDraft transaction for chat ${newChatId}:`, error);
            tx.abort();
            throw error;
        }
    }

    async clearCurrentUserChatDraft(chat_id: string): Promise<Chat | null> {
        const tx = this.getTransaction(this.CHATS_STORE_NAME, 'readwrite');
        let updatedChat: Chat | null = null;
        try {
            const chat = await this.getChat(chat_id, tx); 
            if (chat) {
                chat.draft_json = null;
                chat.draft_v = (chat.draft_v || 0) + 1;
                chat.last_edited_overall_timestamp = Math.floor(Date.now() / 1000);
                chat.updatedAt = new Date();
                await this.addChat(chat, tx);
                updatedChat = chat;
            }
            return new Promise((resolve, reject) => {
                tx.oncomplete = () => resolve(updatedChat);
                tx.onerror = () => reject(tx.error);
            });
        } catch (error) {
            console.error(`[ChatDatabase] Error in clearCurrentUserChatDraft transaction for chat ${chat_id}:`, error);
            tx.abort();
            throw error;
        }
    }

    async deleteChat(chat_id: string, transaction?: IDBTransaction): Promise<void> {
        // This method now implicitly handles deleting the draft as it's part of the chat record.
        console.debug(`[ChatDatabase] Deleting chat (and its draft): ${chat_id}`);
        return new Promise((resolve, reject) => {
            const currentTransaction = transaction || this.getTransaction(this.CHATS_STORE_NAME, 'readwrite');
            const store = currentTransaction.objectStore(this.CHATS_STORE_NAME);
            const request = store.delete(chat_id);
            request.onsuccess = () => {
                console.debug(`[ChatDatabase] Chat ${chat_id} deleted successfully.`);
                resolve();
            };
            request.onerror = () => {
                console.error(`[ChatDatabase] Error deleting chat ${chat_id}:`, request.error);
                reject(request.error);
            };
            if (!transaction) {
                currentTransaction.oncomplete = () => resolve();
                currentTransaction.onerror = () => reject(currentTransaction.error);
            }
        });
    }

    async addMessageToChat(chat_id: string, message: Message): Promise<Chat | null> {
        const tx = this.getTransaction(this.CHATS_STORE_NAME, 'readwrite');
        try {
            const chat = await this.getChat(chat_id, tx);
            if (!chat) {
                console.error(`[ChatDatabase] Chat not found for adding message: ${chat_id}`);
                tx.abort();
                return null;
            }
            chat.messages = [...chat.messages, message];
            chat.messages_v = (chat.messages_v || 0) + 1;
            chat.last_edited_overall_timestamp = Math.floor(Date.now() / 1000); // Or use message.timestamp if more appropriate
            chat.updatedAt = new Date();
            await this.addChat(chat, tx);
            
            return new Promise((resolve, reject) => {
                tx.oncomplete = () => resolve(chat);
                tx.onerror = () => reject(tx.error);
            });
        } catch (error) {
            console.error(`[ChatDatabase] Error in addMessageToChat transaction for chat ${chat_id}:`, error);
            tx.abort();
            throw error;
        }
    }
    
    async updateChat(chat: Chat, transaction?: IDBTransaction): Promise<void> {
        return this.addChat(chat, transaction);
    }

    async updateMessageInChat(chat_id: string, updatedMessage: Message): Promise<Chat | null> {
        const tx = this.getTransaction(this.CHATS_STORE_NAME, 'readwrite');
        try {
            const chat = await this.getChat(chat_id, tx);
            if (!chat) {
                tx.abort();
                throw new Error(`Chat with ID ${chat_id} not found`);
            }
            const messageIndex = chat.messages.findIndex(m => m.message_id === updatedMessage.message_id);
            if (messageIndex === -1) {
                 chat.messages.push(updatedMessage);
            } else {
                chat.messages[messageIndex] = updatedMessage;
            }
            chat.updatedAt = new Date();
            if (updatedMessage.timestamp > chat.last_edited_overall_timestamp) {
                 chat.last_edited_overall_timestamp = updatedMessage.timestamp;
            }
            await this.addChat(chat, tx);
            
            return new Promise((resolve, reject) => {
                tx.oncomplete = () => resolve(chat);
                tx.onerror = () => reject(tx.error);
            });
        } catch (error) {
            console.error(`[ChatDatabase] Error in updateMessageInChat transaction for chat ${chat_id}:`, error);
            tx.abort();
            throw error;
        }
    }

    async addOrUpdateChatWithFullData(chatData: Chat, transaction?: IDBTransaction): Promise<void> {
        console.debug("[ChatDatabase] Adding/updating chat with full data:", chatData.chat_id);
        chatData.createdAt = new Date(chatData.createdAt);
        chatData.updatedAt = new Date(chatData.updatedAt);
        // Ensure draft fields are present if not provided, to maintain schema consistency
        if (chatData.draft_json === undefined) chatData.draft_json = null;
        if (chatData.draft_v === undefined) chatData.draft_v = 0;
        return this.addChat(chatData, transaction);
    }
    
    /**
     * Performs batch updates and deletions within a single transaction.
     * Drafts are now part of the Chat objects in `updates`.
     */
    async batchProcessChatData(
        updates: Array<Chat>, // Expect full Chat objects for put
        deletions: string[],
        // userDraftsToUpdate parameter removed
        transaction: IDBTransaction // Transaction must be provided by the caller
    ): Promise<void> {
        console.debug(`[ChatDatabase] Batch processing: ${updates.length} updates, ${deletions.length} deletions.`);
        const chatStore = transaction.objectStore(this.CHATS_STORE_NAME);
        // draftStore is removed

        const promises: Promise<void>[] = [];

        updates.forEach(chatToUpdate => {
            promises.push(new Promise<void>((resolve, reject) => {
                // Ensure Date objects are correctly handled
                if (typeof chatToUpdate.createdAt === 'string' || typeof chatToUpdate.createdAt === 'number') {
                    chatToUpdate.createdAt = new Date(chatToUpdate.createdAt);
                }
                if (typeof chatToUpdate.updatedAt === 'string' || typeof chatToUpdate.updatedAt === 'number') {
                    chatToUpdate.updatedAt = new Date(chatToUpdate.updatedAt);
                }
                // Ensure draft fields are present if not provided, to maintain schema consistency
                if (chatToUpdate.draft_json === undefined) chatToUpdate.draft_json = null;
                if (chatToUpdate.draft_v === undefined) chatToUpdate.draft_v = 0;

                const request = chatStore.put(chatToUpdate);
                request.onsuccess = () => resolve();
                request.onerror = () => reject(request.error);
            }));
        });

        deletions.forEach(chat_id => {
            promises.push(new Promise<void>((resolve, reject) => {
                const request = chatStore.delete(chat_id);
                request.onsuccess = () => resolve();
                request.onerror = () => reject(request.error);
            }));
        });

        // Logic for userDraftsToUpdate is removed
        
        await Promise.all(promises);
        // The transaction's oncomplete/onerror will be handled by the caller who created it.
    }


    // --- Offline Changes Store Methods ---
    async addOfflineChange(change: OfflineChange, transaction?: IDBTransaction): Promise<void> {
        return new Promise((resolve, reject) => {
            const currentTransaction = transaction || this.getTransaction(this.OFFLINE_CHANGES_STORE_NAME, 'readwrite');
            const store = currentTransaction.objectStore(this.OFFLINE_CHANGES_STORE_NAME);
            const request = store.put(change);
            request.onsuccess = () => resolve();
            request.onerror = () => reject(request.error);
            if (!transaction) {
                currentTransaction.oncomplete = () => resolve();
                currentTransaction.onerror = () => reject(currentTransaction.error);
            }
        });
    }

    async getOfflineChanges(transaction?: IDBTransaction): Promise<OfflineChange[]> {
        return new Promise((resolve, reject) => {
            const currentTransaction = transaction || this.getTransaction(this.OFFLINE_CHANGES_STORE_NAME, 'readonly');
            const store = currentTransaction.objectStore(this.OFFLINE_CHANGES_STORE_NAME);
            const request = store.getAll();
            request.onsuccess = () => resolve(request.result || []);
            request.onerror = () => reject(request.error);
        });
    }

    async deleteOfflineChange(change_id: string, transaction?: IDBTransaction): Promise<void> {
        return new Promise((resolve, reject) => {
            const currentTransaction = transaction || this.getTransaction(this.OFFLINE_CHANGES_STORE_NAME, 'readwrite');
            const store = currentTransaction.objectStore(this.OFFLINE_CHANGES_STORE_NAME);
            const request = store.delete(change_id);
            request.onsuccess = () => resolve();
            request.onerror = () => reject(request.error);
            if (!transaction) {
                currentTransaction.oncomplete = () => resolve();
                currentTransaction.onerror = () => reject(currentTransaction.error);
            }
        });
    }

    // --- Component Version and Timestamp Updates ---
    async updateChatComponentVersion(chat_id: string, component: keyof ChatComponentVersions, version: number): Promise<void> {
        const tx = this.getTransaction(this.CHATS_STORE_NAME, 'readwrite');
        try {
            const chat = await this.getChat(chat_id, tx);
            if (chat) {
                if (component === 'draft_v') {
                    chat.draft_v = version;
                } else if (component === 'messages_v') {
                    chat.messages_v = version;
                } else if (component === 'title_v') {
                    chat.title_v = version;
                }
                // (chat as any)[component] = version; // Less type-safe, but was used before
                chat.updatedAt = new Date();
                await this.addChat(chat, tx);
            }
            return new Promise((resolve, reject) => {
                tx.oncomplete = () => resolve();
                tx.onerror = () => reject(tx.error);
            });
        } catch (error) {
            tx.abort();
            throw error;
        }
    }

    async updateChatLastEditedTimestamp(chat_id: string, timestamp: number): Promise<void> {
        const tx = this.getTransaction(this.CHATS_STORE_NAME, 'readwrite');
        try {
            const chat = await this.getChat(chat_id, tx);
            if (chat) {
                chat.last_edited_overall_timestamp = timestamp;
                chat.updatedAt = new Date(); 
                await this.addChat(chat, tx);
            }
            return new Promise((resolve, reject) => {
                tx.oncomplete = () => resolve();
                tx.onerror = () => reject(tx.error);
            });
        } catch (error) {
            tx.abort();
            throw error;
        }
    }

    async clearAllChatData(): Promise<void> {
        console.debug("[ChatDatabase] Clearing all chat data (chats, pending_sync_changes).");
        if (!this.db) {
            console.warn("[ChatDatabase] Database not initialized, skipping clear.");
            return Promise.resolve();
        }

        // USER_DRAFTS_STORE_NAME removed from storesToClear
        const storesToClear = [this.CHATS_STORE_NAME, this.OFFLINE_CHANGES_STORE_NAME];
        
        return new Promise((resolve, reject) => {
            const transaction = this.db!.transaction(storesToClear, 'readwrite');
            
            transaction.oncomplete = () => {
                console.debug("[ChatDatabase] All chat data stores cleared successfully.");
                resolve();
            };
            transaction.onerror = (event) => {
                console.error("[ChatDatabase] Error clearing chat data stores:", transaction.error);
                reject(transaction.error);
            };

            storesToClear.forEach(storeName => {
                if (this.db?.objectStoreNames.contains(storeName)) { // Check if store exists before trying to clear
                    const store = transaction.objectStore(storeName);
                    store.clear(); 
                } else {
                    console.warn(`[ChatDatabase] Store ${storeName} not found during clearAllChatData. Skipping.`);
                }
            });
        });
    }

    async deleteDatabase(): Promise<void> {
        console.debug(`[ChatDatabase] Attempting to delete database: ${this.DB_NAME}`);
        return new Promise((resolve, reject) => {
            if (this.db) {
                this.db.close(); 
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
                console.warn(`[ChatDatabase] Deletion of database ${this.DB_NAME} blocked. Close other tabs/connections.`, event);
                reject(new Error(`Database ${this.DB_NAME} deletion blocked. Please close other tabs using the application and try again.`));
            };
        });
    }
}

export const chatDB = new ChatDatabase();
