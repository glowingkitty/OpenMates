// frontend/packages/ui/src/services/db.ts
// Manages IndexedDB storage for chat-related data.
import type { Chat, Message, TiptapJSON, ChatComponentVersions, OfflineChange } from '../types/chat';
// UserChatDraft type is no longer imported as draft info is part of the Chat type.

class ChatDatabase {
    private db: IDBDatabase | null = null;
    private readonly DB_NAME = 'chats_db';
    private readonly CHATS_STORE_NAME = 'chats';
    private readonly MESSAGES_STORE_NAME = 'messages'; // New store for messages
    private readonly OFFLINE_CHANGES_STORE_NAME = 'pending_sync_changes';
    // Version incremented due to schema change (adding messages store, removing messages from chats store)
    private readonly VERSION = 6;
    private initializationPromise: Promise<void> | null = null;

    /**
     * Initialize the database
     */
    async init(): Promise<void> {
        if (this.initializationPromise) {
            return this.initializationPromise;
        }

        this.initializationPromise = new Promise((resolve, reject) => {
            console.debug("[ChatDatabase] Initializing database, Version:", this.VERSION);
            const request = indexedDB.open(this.DB_NAME, this.VERSION);

            request.onerror = () => {
                console.error("[ChatDatabase] Error opening database:", request.error);
                this.initializationPromise = null; // Reset promise on failure
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
                const transaction = (event.target as IDBOpenDBRequest).transaction; // This is the versionchange transaction
                
                // Chats store (ensure it exists, no changes to its structure here unless removing 'messages' field explicitly)
                if (!db.objectStoreNames.contains(this.CHATS_STORE_NAME)) {
                    const chatStore = db.createObjectStore(this.CHATS_STORE_NAME, { keyPath: 'chat_id' });
                    chatStore.createIndex('last_edited_overall_timestamp', 'last_edited_overall_timestamp', { unique: false });
                    chatStore.createIndex('updatedAt', 'updatedAt', { unique: false });
                } else {
                    // If chats store exists, ensure indexes are present (idempotent)
                    const chatStore = transaction?.objectStore(this.CHATS_STORE_NAME);
                    if (chatStore) {
                        if (!chatStore.indexNames.contains('last_edited_overall_timestamp')) {
                            chatStore.createIndex('last_edited_overall_timestamp', 'last_edited_overall_timestamp', { unique: false });
                        }
                        if (!chatStore.indexNames.contains('updatedAt')) {
                             chatStore.createIndex('updatedAt', 'updatedAt', { unique: false });
                        }
                    }
                }

                // New Messages store
                if (!db.objectStoreNames.contains(this.MESSAGES_STORE_NAME)) {
                    const messagesStore = db.createObjectStore(this.MESSAGES_STORE_NAME, { keyPath: 'message_id' });
                    messagesStore.createIndex('chat_id_timestamp', ['chat_id', 'timestamp'], { unique: false });
                    messagesStore.createIndex('chat_id', 'chat_id', { unique: false }); // For deleting all messages of a chat
                    messagesStore.createIndex('timestamp', 'timestamp', { unique: false }); // For general sorting if needed
                }

                // Data migration: Move messages from Chat.messages to the new messages store
                if (transaction && event.oldVersion < 6) { // Check oldVersion to run migration only once
                    console.info(`[ChatDatabase] Migrating messages from version ${event.oldVersion} to ${event.newVersion}`);
                    const chatStore = transaction.objectStore(this.CHATS_STORE_NAME);
                    const messagesStore = transaction.objectStore(this.MESSAGES_STORE_NAME);

                    chatStore.openCursor().onsuccess = (e) => {
                        const cursor = (e.target as IDBRequest<IDBCursorWithValue>).result;
                        if (cursor) {
                            const chatData = cursor.value as any; // Use 'any' for migration flexibility
                            if (chatData.messages && Array.isArray(chatData.messages)) {
                                for (const message of chatData.messages) {
                                    // Ensure message has chat_id, though it should from the type
                                    if (!message.chat_id) message.chat_id = chatData.chat_id;
                                    messagesStore.put(message);
                                }
                                delete chatData.messages; // Remove messages array from chat object
                                cursor.update(chatData); // Update chat object in store
                            }
                            cursor.continue();
                        } else {
                            console.info("[ChatDatabase] Message migration completed.");
                        }
                    };
                }
                
                // Remove User Drafts store if it exists from a previous version (idempotent check)
                const oldUserDraftsStoreName = 'user_drafts'; 
                if (db.objectStoreNames.contains(oldUserDraftsStoreName)) {
                    console.info(`[ChatDatabase] Deleting old store: ${oldUserDraftsStoreName}`);
                    db.deleteObjectStore(oldUserDraftsStoreName);
                }

                // Offline changes store (ensure it exists)
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
    public async getTransaction(storeNames: string | string[], mode: IDBTransactionMode): Promise<IDBTransaction> {
        await this.init(); // Ensure DB is initialized
        if (!this.db) {
            // This should ideally not be reached if init() succeeded.
            console.error("[ChatDatabase] getTransaction called but DB is still null after init.");
            throw new Error('Database not initialized despite awaiting init()');
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
        await this.init();
        return new Promise(async (resolve, reject) => {
            const currentTransaction = transaction || await this.getTransaction(this.CHATS_STORE_NAME, 'readwrite');
            const store = currentTransaction.objectStore(this.CHATS_STORE_NAME);
            // Ensure chat object does not contain 'messages' array before saving
            const chatToSave = { ...chat };
            delete (chatToSave as any).messages; 

            const request = store.put(chatToSave);

            request.onsuccess = () => {
                console.debug("[ChatDatabase] Chat added/updated successfully:", chatToSave.chat_id, "Versions:", {m: chatToSave.messages_v, t: chatToSave.title_v, d: chatToSave.draft_v});
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
        await this.init();
        return new Promise(async (resolve, reject) => {
            const currentTransaction = transaction || await this.getTransaction(this.CHATS_STORE_NAME, 'readonly');
            const store = currentTransaction.objectStore(this.CHATS_STORE_NAME);
            const index = store.index('last_edited_overall_timestamp');
            const request = index.openCursor(null, 'prev');
            const chats: Chat[] = [];
         
            request.onsuccess = () => {
                const cursor = request.result;
                if (cursor) {
                    // Ensure messages property is not on the chat object returned
                    const chatData = { ...cursor.value };
                    delete (chatData as any).messages;
                    chats.push(chatData);
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
        await this.init();
        return new Promise(async (resolve, reject) => {
            const currentTransaction = transaction || await this.getTransaction(this.CHATS_STORE_NAME, 'readonly');
            const store = currentTransaction.objectStore(this.CHATS_STORE_NAME);
            const request = store.get(chat_id);
            request.onsuccess = () => {
                const chatData = request.result;
                if (chatData) {
                    delete (chatData as any).messages; // Ensure messages property is not returned
                }
                resolve(chatData || null);
            };
            request.onerror = () => {
                console.error("[ChatDatabase] Error getting chat:", request.error);
                reject(request.error);
            };
        });
    }

    async saveCurrentUserChatDraft(chat_id: string, draft_content: TiptapJSON | null): Promise<Chat | null> {
        await this.init();
        console.debug("[ChatDatabase] Saving current user's draft for chat:", chat_id);
        
        const tx = await this.getTransaction(this.CHATS_STORE_NAME, 'readwrite');
        let updatedChat: Chat | null = null;

        try {
            // getChat will also await init, but it's fine.
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
        await this.init();
        const tx = await this.getTransaction(this.CHATS_STORE_NAME, 'readwrite');
        const now = new Date();
        const nowTimestamp = Math.floor(now.getTime() / 1000);
        const newChatId = crypto.randomUUID();
        console.debug(`[ChatDatabase] Creating new chat ${newChatId} with current user's draft`);

        const chatToCreate: Chat = {
            chat_id: newChatId,
            title: '', // Chats with only drafts should have no title
            messages_v: 0,
            title_v: 0,
            draft_v: 1, // Initial draft version
            draft_json: draft_content,
            last_edited_overall_timestamp: nowTimestamp,
            unread_count: 0,
            // messages: [], // Removed as messages are in a separate store
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
        await this.init();
        const tx = await this.getTransaction(this.CHATS_STORE_NAME, 'readwrite');
        let updatedChat: Chat | null = null;
        try {
            const chat = await this.getChat(chat_id, tx);
            if (chat) {
                // When clearing a draft, the content becomes null and version should be 0.
                chat.draft_json = null;
                chat.draft_v = 0; // Reset draft version to 0
                // Still update timestamps as an operation occurred
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
        await this.init();
        console.debug(`[ChatDatabase] Deleting chat ${chat_id} and its messages.`);
        const currentTransaction = transaction || await this.getTransaction([this.CHATS_STORE_NAME, this.MESSAGES_STORE_NAME], 'readwrite');
        
        const chatStore = currentTransaction.objectStore(this.CHATS_STORE_NAME);
        const messagesStore = currentTransaction.objectStore(this.MESSAGES_STORE_NAME);
        const messagesChatIdIndex = messagesStore.index('chat_id');

        const deleteChatRequest = chatStore.delete(chat_id);
        
        const deleteMessagesPromises: Promise<void>[] = [];
        const messagesCursorRequest = messagesChatIdIndex.openCursor(IDBKeyRange.only(chat_id));

        messagesCursorRequest.onsuccess = (event) => {
            const cursor = (event.target as IDBRequest<IDBCursorWithValue>).result;
            if (cursor) {
                deleteMessagesPromises.push(new Promise((res, rej) => {
                    const deleteReq = cursor.delete();
                    deleteReq.onsuccess = () => res();
                    deleteReq.onerror = () => rej(deleteReq.error);
                }));
                cursor.continue();
            }
        };
        
        return new Promise((resolve, reject) => {
            // Wait for all parts of the transaction to be defined
            Promise.all([
                new Promise<void>((res, rej) => {
                    deleteChatRequest.onsuccess = () => res();
                    deleteChatRequest.onerror = () => rej(deleteChatRequest.error);
                }),
                new Promise<void>((res, rej) => {
                    // This promise resolves when the cursor is done and all individual delete promises are set up
                    messagesCursorRequest.onerror = () => rej(messagesCursorRequest.error);
                    messagesCursorRequest.onsuccess = (event) => { // Re-check onsuccess for cursor completion
                        const cursor = (event.target as IDBRequest<IDBCursorWithValue>).result;
                        if (!cursor) { // Cursor is done
                           Promise.all(deleteMessagesPromises).then(() => res()).catch(rej);
                        }
                    };
                })
            ]).then(() => {
                 if (!transaction) {
                    currentTransaction.oncomplete = () => {
                        console.debug(`[ChatDatabase] Chat ${chat_id} and its messages deleted successfully.`);
                        resolve();
                    };
                    currentTransaction.onerror = () => {
                        console.error(`[ChatDatabase] Error in deleteChat transaction for ${chat_id}:`, currentTransaction.error);
                        reject(currentTransaction.error);
                    };
                } else {
                    resolve(); // If part of a larger transaction, let caller handle oncomplete/onerror
                }
            }).catch(error => {
                console.error(`[ChatDatabase] Error during deleteChat for ${chat_id}:`, error);
                if (!transaction) currentTransaction.abort();
                reject(error);
            });
        });
    }

    async saveMessage(message: Message, transaction?: IDBTransaction): Promise<void> {
        await this.init();
        return new Promise(async (resolve, reject) => {
            const currentTransaction = transaction || await this.getTransaction(this.MESSAGES_STORE_NAME, 'readwrite');
            const store = currentTransaction.objectStore(this.MESSAGES_STORE_NAME);
            const request = store.put(message); // put handles both add and update

            request.onsuccess = () => {
                console.debug("[ChatDatabase] Message saved/updated successfully:", message.message_id);
                resolve();
            };
            request.onerror = () => {
                console.error("[ChatDatabase] Error saving/updating message:", request.error);
                reject(request.error);
            };
            if (!transaction) {
                currentTransaction.oncomplete = () => resolve();
                currentTransaction.onerror = () => reject(currentTransaction.error);
            }
        });
    }

    async getMessagesForChat(chat_id: string, transaction?: IDBTransaction): Promise<Message[]> {
        await this.init();
        return new Promise(async (resolve, reject) => {
            const currentTransaction = transaction || await this.getTransaction(this.MESSAGES_STORE_NAME, 'readonly');
            const store = currentTransaction.objectStore(this.MESSAGES_STORE_NAME);
            const index = store.index('chat_id_timestamp'); // Use compound index for fetching and sorting
            const request = index.getAll(IDBKeyRange.bound([chat_id, -Infinity], [chat_id, Infinity])); // Get all for chat_id, sorted by timestamp

            request.onsuccess = () => {
                resolve(request.result || []);
            };
            request.onerror = () => {
                console.error(`[ChatDatabase] Error getting messages for chat ${chat_id}:`, request.error);
                reject(request.error);
            };
        });
    }

    async getMessage(message_id: string, transaction?: IDBTransaction): Promise<Message | null> {
        await this.init();
        return new Promise(async (resolve, reject) => {
            const currentTransaction = transaction || await this.getTransaction(this.MESSAGES_STORE_NAME, 'readonly');
            const store = currentTransaction.objectStore(this.MESSAGES_STORE_NAME);
            const request = store.get(message_id);

            request.onsuccess = () => {
                resolve(request.result || null);
            };
            request.onerror = () => {
                console.error(`[ChatDatabase] Error getting message ${message_id}:`, request.error);
                reject(request.error);
            };
        });
    }
    
    async updateChat(chat: Chat, transaction?: IDBTransaction): Promise<void> {
        // This method now only updates chat metadata. Messages are handled separately.
        // addChat already awaits init()
        return this.addChat(chat, transaction); // addChat already handles stripping 'messages'
    }

    // updateMessageInChat is replaced by saveMessage

    async addOrUpdateChatWithFullData(chatData: Chat, messages: Message[] = [], transaction?: IDBTransaction): Promise<void> {
        await this.init();
        console.debug("[ChatDatabase] Adding/updating chat with full data:", chatData.chat_id);
        const chatMetadata = { ...chatData };
        delete (chatMetadata as any).messages; // Ensure messages are not part of chat metadata

        chatMetadata.createdAt = new Date(chatMetadata.createdAt);
        chatMetadata.updatedAt = new Date(chatMetadata.updatedAt);
        if (chatMetadata.draft_json === undefined) chatMetadata.draft_json = null;
        if (chatMetadata.draft_v === undefined) chatMetadata.draft_v = 0;

        const currentTransaction = transaction || await this.getTransaction([this.CHATS_STORE_NAME, this.MESSAGES_STORE_NAME], 'readwrite');
        
        const chatPromise = this.addChat(chatMetadata, currentTransaction); // addChat will await init again, but it's idempotent
        const messagePromises = messages.map(msg => this.saveMessage(msg, currentTransaction)); // saveMessage will await init

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
    
    /**
     * Performs batch updates and deletions for chats and messages within a single transaction.
     */
    async batchProcessChatData(
        chatsToUpdate: Array<Chat>,      // Chat metadata to add/update
        messagesToSave: Array<Message>,  // Messages to add/update
        chatIdsToDelete: string[],       // Chat IDs to delete (will also delete their messages)
        messageIdsToDelete: string[],    // Specific message IDs to delete
        transaction: IDBTransaction      // Transaction must be provided by the caller. init() must be called before this.
    ): Promise<void> {
        // Caller is responsible for ensuring init() has been called and for providing an active transaction.
        console.debug(`[ChatDatabase] Batch processing: ${chatsToUpdate.length} chat updates, ${messagesToSave.length} message saves, ${chatIdsToDelete.length} chat deletions, ${messageIdsToDelete.length} message deletions.`);
        
        const chatStore = transaction.objectStore(this.CHATS_STORE_NAME);
        const messagesStore = transaction.objectStore(this.MESSAGES_STORE_NAME);

        const promises: Promise<void>[] = [];

        // Process chat updates
        chatsToUpdate.forEach(chatToUpdate => {
            const chatMetadata = { ...chatToUpdate };
            delete (chatMetadata as any).messages; // Ensure no messages array
            if (typeof chatMetadata.createdAt === 'string' || typeof chatMetadata.createdAt === 'number') {
                chatMetadata.createdAt = new Date(chatMetadata.createdAt);
            }
            if (typeof chatMetadata.updatedAt === 'string' || typeof chatMetadata.updatedAt === 'number') {
                chatMetadata.updatedAt = new Date(chatMetadata.updatedAt);
            }
            if (chatMetadata.draft_json === undefined) chatMetadata.draft_json = null;
            if (chatMetadata.draft_v === undefined) chatMetadata.draft_v = 0;
            
            promises.push(new Promise<void>((resolve, reject) => {
                const request = chatStore.put(chatMetadata);
                request.onsuccess = () => resolve();
                request.onerror = () => reject(request.error);
            }));
        });

        // Process message saves/updates
        messagesToSave.forEach(message => {
            promises.push(this.saveMessage(message, transaction)); // saveMessage is already promise-based
        });

        // Process chat deletions (which includes their messages)
        chatIdsToDelete.forEach(chat_id => {
            promises.push(this.deleteChat(chat_id, transaction)); // deleteChat is already promise-based
        });
        
        // Process specific message deletions
        messageIdsToDelete.forEach(message_id => {
            promises.push(new Promise<void>((resolve, reject) => {
                const request = messagesStore.delete(message_id);
                request.onsuccess = () => resolve();
                request.onerror = () => reject(request.error);
            }));
        });
        
        await Promise.all(promises);
        // The transaction's oncomplete/onerror will be handled by the caller.
    }

    // --- Offline Changes Store Methods ---
    async addOfflineChange(change: OfflineChange, transaction?: IDBTransaction): Promise<void> {
        await this.init();
        return new Promise(async (resolve, reject) => {
            const currentTransaction = transaction || await this.getTransaction(this.OFFLINE_CHANGES_STORE_NAME, 'readwrite');
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
        await this.init();
        return new Promise(async (resolve, reject) => {
            const currentTransaction = transaction || await this.getTransaction(this.OFFLINE_CHANGES_STORE_NAME, 'readonly');
            const store = currentTransaction.objectStore(this.OFFLINE_CHANGES_STORE_NAME);
            const request = store.getAll();
            request.onsuccess = () => resolve(request.result || []);
            request.onerror = () => reject(request.error);
        });
    }

    async deleteOfflineChange(change_id: string, transaction?: IDBTransaction): Promise<void> {
        await this.init();
        return new Promise(async (resolve, reject) => {
            const currentTransaction = transaction || await this.getTransaction(this.OFFLINE_CHANGES_STORE_NAME, 'readwrite');
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
        await this.init();
        const tx = await this.getTransaction(this.CHATS_STORE_NAME, 'readwrite');
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
                chat.updatedAt = new Date();
                await this.addChat(chat, tx); // addChat will await init
            }
            return new Promise((resolve, reject) => {
                tx.oncomplete = () => resolve();
                tx.onerror = () => reject(tx.error);
            });
        } catch (error) {
            if (tx.abort) tx.abort();
            throw error;
        }
    }

    async updateChatLastEditedTimestamp(chat_id: string, timestamp: number): Promise<void> {
        await this.init();
        const tx = await this.getTransaction(this.CHATS_STORE_NAME, 'readwrite');
        try {
            const chat = await this.getChat(chat_id, tx);
            if (chat) {
                chat.last_edited_overall_timestamp = timestamp;
                chat.updatedAt = new Date(); 
                await this.addChat(chat, tx); // addChat will await init
            }
            return new Promise((resolve, reject) => {
                tx.oncomplete = () => resolve();
                tx.onerror = () => reject(tx.error);
            });
        } catch (error) {
            if (tx.abort) tx.abort();
            throw error;
        }
    }

    async clearAllChatData(): Promise<void> {
        await this.init();
        console.debug("[ChatDatabase] Clearing all chat data (chats, messages, pending_sync_changes).");
        if (!this.db) {
            // This should not happen if init() was successful
            console.warn("[ChatDatabase] Database not initialized after init(), skipping clear.");
            return Promise.resolve();
        }

        const storesToClear = [this.CHATS_STORE_NAME, this.MESSAGES_STORE_NAME, this.OFFLINE_CHANGES_STORE_NAME];
        
        return new Promise(async (resolve, reject) => {
            // getTransaction now returns a Promise
            const transaction = await this.getTransaction(storesToClear, 'readwrite');
            
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
            this.initializationPromise = null; // Reset initialization promise

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
