// frontend/packages/ui/src/services/db.ts
// Manages IndexedDB storage for chat-related data.
import type { Chat, Message, TiptapJSON, ChatComponentVersions, OfflineChange, NewChatSuggestion } from '../types/chat';
import { 
    encryptWithMasterKey, 
    decryptWithMasterKey,
    generateChatKey,
    encryptWithChatKey,
    decryptWithChatKey,
    encryptChatKeyWithMasterKey,
    decryptChatKeyWithMasterKey,
    encryptArrayWithChatKey,
    decryptArrayWithChatKey
} from './cryptoService';
// UserChatDraft type is no longer imported as draft info is part of the Chat type.

class ChatDatabase {
    private db: IDBDatabase | null = null;
    private readonly DB_NAME = 'chats_db';
    private readonly CHATS_STORE_NAME = 'chats';
    private readonly MESSAGES_STORE_NAME = 'messages'; // New store for messages
    private readonly OFFLINE_CHANGES_STORE_NAME = 'pending_sync_changes';
    private readonly NEW_CHAT_SUGGESTIONS_STORE_NAME = 'new_chat_suggestions'; // Store for new chat suggestions
    // Version incremented due to schema change (adding new_chat_suggestions store)
    private readonly VERSION = 10;
    private initializationPromise: Promise<void> | null = null;
    
    // Flag to prevent new operations during database deletion
    private isDeleting: boolean = false;
    
    // Chat key cache for performance
    private chatKeys: Map<string, Uint8Array> = new Map();

    /**
     * Initialize the database
     */
    async init(): Promise<void> {
        // Prevent initialization during deletion
        if (this.isDeleting) {
            throw new Error('Database is being deleted and cannot be initialized');
        }
        
        if (this.initializationPromise) {
            return this.initializationPromise;
        }

        this.initializationPromise = new Promise(async (resolve, reject) => {
            console.debug("[ChatDatabase] Initializing database, Version:", this.VERSION);
            const request = indexedDB.open(this.DB_NAME, this.VERSION);

            request.onblocked = (event) => {
                console.error(`[ChatDatabase] CRITICAL: Database open blocked! Please close other tabs. Event:`, event);
                reject(new Error("Database open request is blocked."));
            };

            request.onerror = () => {
                console.error("[ChatDatabase] Error opening database:", request.error);
                this.initializationPromise = null; // Reset promise on failure
                reject(request.error);
            };

            request.onsuccess = async () => {
                console.debug("[ChatDatabase] Database opened successfully");
                this.db = request.result;
                
                // Load chat keys from database into cache
                try {
                    await this.loadChatKeysFromDatabase();
                } catch (error) {
                    console.error("[ChatDatabase] Error loading chat keys during initialization:", error);
                }
                
                // Clean up duplicate messages on initialization
                try {
                    await this.cleanupDuplicateMessages();
                } catch (error) {
                    console.error("[ChatDatabase] Error during duplicate cleanup on initialization:", error);
                    // Don't fail initialization if cleanup fails
                }
                
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
                    chatStore.createIndex('updated_at', 'updated_at', { unique: false });
                } else {
                    // If chats store exists, ensure indexes are present (idempotent)
                    const chatStore = transaction?.objectStore(this.CHATS_STORE_NAME);
                    if (chatStore) {
                        if (!chatStore.indexNames.contains('last_edited_overall_timestamp')) {
                            chatStore.createIndex('last_edited_overall_timestamp', 'last_edited_overall_timestamp', { unique: false });
                        }
                        if (!chatStore.indexNames.contains('updated_at')) {
                             chatStore.createIndex('updated_at', 'updated_at', { unique: false });
                        }
                        if (chatStore.indexNames.contains('updatedAt')) {
                            chatStore.deleteIndex('updatedAt');
                        }
                    }
                }

                // New Messages store
                if (!db.objectStoreNames.contains(this.MESSAGES_STORE_NAME)) {
                    const messagesStore = db.createObjectStore(this.MESSAGES_STORE_NAME, { keyPath: 'message_id' });
                    messagesStore.createIndex('chat_id_created_at', ['chat_id', 'created_at'], { unique: false });
                    messagesStore.createIndex('chat_id', 'chat_id', { unique: false }); // For deleting all messages of a chat
                    messagesStore.createIndex('created_at', 'created_at', { unique: false }); // For general sorting if needed
                } else if (transaction && event.oldVersion < 7) {
                    const messagesStore = transaction.objectStore(this.MESSAGES_STORE_NAME);
                    if (messagesStore.indexNames.contains('chat_id_timestamp')) {
                        messagesStore.deleteIndex('chat_id_timestamp');
                    }
                    if (messagesStore.indexNames.contains('timestamp')) {
                        messagesStore.deleteIndex('timestamp');
                    }
                    if (!messagesStore.indexNames.contains('chat_id_created_at')) {
                        messagesStore.createIndex('chat_id_created_at', ['chat_id', 'created_at'], { unique: false });
                    }
                    if (!messagesStore.indexNames.contains('created_at')) {
                        messagesStore.createIndex('created_at', 'created_at', { unique: false });
                    }
                }

                // Data migration: Move messages from Chat.messages to the new messages store
                if (transaction && event.oldVersion < 6) { // Check oldVersion to run migration only once
                    console.info(`[ChatDatabase] Migrating messages from version ${event.oldVersion} to ${event.newVersion}`);
                    const chatStore = transaction.objectStore(this.CHATS_STORE_NAME);
                    const messagesStore = transaction.objectStore(this.MESSAGES_STORE_NAME);

                    const cursorRequest = chatStore.openCursor();
                    cursorRequest.onsuccess = (e) => {
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
                    cursorRequest.onerror = (e) => {
                        console.error("[ChatDatabase] CRITICAL: Error during message migration (v<6) cursor:", (e.target as IDBRequest).error);
                    };
                }

                // Data migration for version 7: rename timestamp to created_at in messages
                if (transaction && event.oldVersion < 7) {
                    console.info(`[ChatDatabase] Migrating messages for version ${event.oldVersion} to ${event.newVersion}: renaming timestamp to created_at`);
                    const messagesStore = transaction.objectStore(this.MESSAGES_STORE_NAME);
                    const cursorRequest = messagesStore.openCursor();
                    cursorRequest.onsuccess = (e) => {
                        const cursor = (e.target as IDBRequest<IDBCursorWithValue | null>)?.result;
                        if (cursor) {
                            const message = cursor.value as any;
                            if (message.timestamp !== undefined) {
                                message.created_at = message.timestamp;
                                delete message.timestamp;
                                cursor.update(message);
                            }
                            cursor.continue();
                        } else {
                            console.info("[ChatDatabase] Message timestamp migration completed.");
                        }
                    };
                    cursorRequest.onerror = (e) => {
                        console.error("[ChatDatabase] CRITICAL: Error during message migration (v<7) cursor:", (e.target as IDBRequest).error);
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

                // New chat suggestions store (ensure it exists)
                if (!db.objectStoreNames.contains(this.NEW_CHAT_SUGGESTIONS_STORE_NAME)) {
                    const suggestionsStore = db.createObjectStore(this.NEW_CHAT_SUGGESTIONS_STORE_NAME, { keyPath: 'id' });
                    suggestionsStore.createIndex('created_at', 'created_at', { unique: false });
                    suggestionsStore.createIndex('chat_id', 'chat_id', { unique: false }); // For deletion when chat is deleted
                    console.debug('[ChatDatabase] Created new_chat_suggestions store');
                }

                // Contents store for unified message parsing architecture (ensure it exists)
                const CONTENTS_STORE_NAME = 'contents';
                if (!db.objectStoreNames.contains(CONTENTS_STORE_NAME)) {
                    const contentsStore = db.createObjectStore(CONTENTS_STORE_NAME, { keyPath: 'contentRef' });
                    contentsStore.createIndex('type', 'type', { unique: false });
                    contentsStore.createIndex('createdAt', 'createdAt', { unique: false });
                    console.debug('[ChatDatabase] Created contents store for unified parsing');
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

    /**
     * Get transaction without calling init() - for use during initialization
     * WARNING: Only use this when you're certain the DB is already open!
     */
    private getTransactionDuringInit(storeNames: string | string[], mode: IDBTransactionMode): IDBTransaction {
        if (!this.db) {
            throw new Error('Database not initialized - cannot get transaction during init');
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

    /**
     * Encrypt chat data before storing in IndexedDB
     * EXCEPTION: Public chats (chat_id starting with 'demo-' or 'legal-') are NOT encrypted
     * since they contain public template content that's the same for all users
     * 
     * CRITICAL: This function is now async because encryptChatKeyWithMasterKey is async.
     * All callers must await this function to prevent storing Promises in IndexedDB.
     */
    private async encryptChatForStorage(chat: Chat): Promise<Chat> {
        // Skip encryption entirely for public chats (demo + legal) - they're public content
        if (chat.chat_id.startsWith('demo-') || chat.chat_id.startsWith('legal-')) {
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
        let chatKey = this.getChatKey(chat.chat_id);
        if (!chatKey && chat.encrypted_chat_key) {
            // Decrypt the server-provided key and cache it
            // CRITICAL FIX: await decryptChatKeyWithMasterKey since it's async
            chatKey = await decryptChatKeyWithMasterKey(chat.encrypted_chat_key);
            if (chatKey) {
                this.setChatKey(chat.chat_id, chatKey);
                encryptedChat.encrypted_chat_key = chat.encrypted_chat_key; // Keep the server's encrypted key
            } else {
                console.error(`[ChatDatabase] Failed to decrypt chat key for chat ${chat.chat_id}`);
            }
        } else if (!chatKey) {
            // No cached key and no server key - generate new one (new chat creation)
            console.log(`[ChatDatabase] Generating NEW chat key for chat ${chat.chat_id} (new chat creation)`);
            chatKey = generateChatKey();
            this.setChatKey(chat.chat_id, chatKey);
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
    private async decryptChatFromStorage(chat: Chat): Promise<Chat> {
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
            // Get chat key from encrypted_chat_key
            let chatKey = this.getChatKey(chat.chat_id);
            if (!chatKey && chat.encrypted_chat_key) {
                // CRITICAL FIX: await decryptChatKeyWithMasterKey since it's async
                chatKey = await decryptChatKeyWithMasterKey(chat.encrypted_chat_key);
                if (chatKey) {
                    this.setChatKey(chat.chat_id, chatKey);
                }
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
        // console.debug("[ChatDatabase] decryptChatFromStorage preserving draft fields:", {
        //     chatId: chat.chat_id,
        //     hasEncryptedDraftMd: !!decryptedChat.encrypted_draft_md,
        //     hasEncryptedDraftPreview: !!decryptedChat.encrypted_draft_preview,
        //     draftVersion: decryptedChat.draft_v
        // });
        
        return decryptedChat;
    }

    async addChat(chat: Chat, transaction?: IDBTransaction): Promise<void> {
        console.debug(`[ChatDatabase] addChat called for chat ${chat.chat_id} with transaction: ${!!transaction}`);
        await this.init();
        
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
        const chatToSave = await this.encryptChatForStorage(chatWithDefaults);
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
                    const newTransaction = await this.getTransaction(this.CHATS_STORE_NAME, 'readwrite');
                    const store = newTransaction.objectStore(this.CHATS_STORE_NAME);
                    const request = store.put(chatToSave);
                    
                    request.onsuccess = () => {
                        console.debug("[ChatDatabase] Chat added/updated successfully (queued):", chatToSave.chat_id, "Versions:", {m: chatToSave.messages_v, t: chatToSave.title_v, d: chatToSave.draft_v});
                        resolve();
                    };
                    
                    request.onerror = () => {
                        console.error("[ChatDatabase] Error in chat store.put operation:", request.error);
                        reject(request.error);
                    };
                    
                    newTransaction.oncomplete = () => {
                        console.debug("[ChatDatabase] New transaction for addChat completed successfully for chat:", chatToSave.chat_id);
                    };
                    
                    newTransaction.onerror = () => {
                        console.error("[ChatDatabase] New transaction for addChat failed for chat:", chatToSave.chat_id, "Error:", newTransaction.error);
                        reject(newTransaction.error);
                    };
                    
                    return;
                }
            }
            
            const currentTransaction = transaction || await this.getTransaction(this.CHATS_STORE_NAME, 'readwrite');
            
            console.debug(`[ChatDatabase] Using ${usesExternalTransaction ? 'external' : 'internal'} transaction for chat ${chatToSave.chat_id}`);
            
            // CRITICAL FIX: Check transaction state one more time right before using it
            // This catches race conditions where the transaction finished between the check above and now
            try {
                const store = currentTransaction.objectStore(this.CHATS_STORE_NAME);
                const request = store.put(chatToSave);
                
                console.debug(`[ChatDatabase] IndexedDB put request initiated for chat ${chatToSave.chat_id}`);

                request.onsuccess = () => {
                    console.debug("[ChatDatabase] Chat added/updated successfully (queued):", chatToSave.chat_id, "Versions:", {m: chatToSave.messages_v, t: chatToSave.title_v, d: chatToSave.draft_v});
                    if (usesExternalTransaction) {
                        console.debug(`[ChatDatabase] External transaction - operation queued for chat ${chatToSave.chat_id}`);
                        // CRITICAL FIX: Don't resolve yet! The transaction might not be committed.
                        // The calling code should wait for transaction.oncomplete
                        resolve(); // Resolve to indicate the operation was queued successfully
                    }
                };
                request.onerror = () => {
                    console.error("[ChatDatabase] Error in chat store.put operation:", request.error);
                    reject(request.error); // This will also cause the transaction to abort if not handled
                };

                if (!usesExternalTransaction) {
                    currentTransaction.oncomplete = () => {
                        console.debug("[ChatDatabase] Transaction for addChat completed successfully for chat:", chatToSave.chat_id);
                        resolve();
                    };
                    currentTransaction.onerror = () => {
                        console.error("[ChatDatabase] Transaction for addChat failed for chat:", chatToSave.chat_id, "Error:", currentTransaction.error);
                        reject(currentTransaction.error);
                    };
                }
            } catch (error: any) {
                // Transaction is no longer active (InvalidStateError or similar)
                if (error?.name === 'InvalidStateError' || error?.message?.includes('transaction')) {
                    console.warn(`[ChatDatabase] Transaction is no longer active for chat ${chatToSave.chat_id}, creating new transaction:`, error);
                    // Create a new transaction and retry
                    try {
                        const newTransaction = await this.getTransaction(this.CHATS_STORE_NAME, 'readwrite');
                        const store = newTransaction.objectStore(this.CHATS_STORE_NAME);
                        const request = store.put(chatToSave);
                        
                        request.onsuccess = () => {
                            console.debug("[ChatDatabase] Chat added/updated successfully with new transaction (queued):", chatToSave.chat_id);
                            resolve();
                        };
                        
                        request.onerror = () => {
                            console.error("[ChatDatabase] Error in chat store.put operation with new transaction:", request.error);
                            reject(request.error);
                        };
                        
                        newTransaction.oncomplete = () => {
                            console.debug("[ChatDatabase] New transaction for addChat completed successfully for chat:", chatToSave.chat_id);
                        };
                        
                        newTransaction.onerror = () => {
                            console.error("[ChatDatabase] New transaction for addChat failed for chat:", chatToSave.chat_id, "Error:", newTransaction.error);
                            reject(newTransaction.error);
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
    
    async getAllChats(transaction?: IDBTransaction): Promise<Chat[]> {
        console.debug(`[ChatDatabase] getAllChats called with transaction: ${!!transaction}`);
        await this.init();
        return new Promise(async (resolve, reject) => {
            const currentTransaction = transaction || await this.getTransaction(this.CHATS_STORE_NAME, 'readonly');
            const store = currentTransaction.objectStore(this.CHATS_STORE_NAME);
            const index = store.index('last_edited_overall_timestamp');
            const request = index.openCursor(null, 'prev');
            const chats: Chat[] = [];
         
            request.onsuccess = async () => {
                const cursor = request.result;
                if (cursor) {
                    // Ensure messages property is not on the chat object returned
                    const chatData = { ...cursor.value };
                    delete (chatData as any).messages;
                    const decryptedChat = await this.decryptChatFromStorage(chatData);
                    chats.push(decryptedChat);
                    cursor.continue();
                } else {
                    console.debug(`[ChatDatabase] Retrieved ${chats.length} chats from database`);
                    resolve(chats);
                }
            };
            request.onerror = () => {
                console.error("[ChatDatabase] Error getting chats:", request.error);
                reject(request.error);
            };
            if (!transaction) { 
                 currentTransaction.oncomplete = () => {
                     console.debug(`[ChatDatabase] getAllChats transaction completed`);
                 };
                currentTransaction.onerror = () => {
                    console.error(`[ChatDatabase] getAllChats transaction failed:`, currentTransaction.error);
                    reject(currentTransaction.error);
                };
            }
        });
    }

    async getChat(chat_id: string, transaction?: IDBTransaction): Promise<Chat | null> {
        await this.init();
        return new Promise(async (resolve, reject) => {
            try {
                const currentTransaction = transaction || await this.getTransaction(this.CHATS_STORE_NAME, 'readonly');
                const store = currentTransaction.objectStore(this.CHATS_STORE_NAME);
                const request = store.get(chat_id);
                
                request.onsuccess = async () => {
                    const chatData = request.result;
                    if (chatData) {
                        delete (chatData as any).messages; // Ensure messages property is not returned
                        const decryptedChat = await this.decryptChatFromStorage(chatData);
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

    async saveCurrentUserChatDraft(chat_id: string, draft_content: string | null, draft_preview: string | null = null): Promise<Chat | null> {
        await this.init();
        console.debug("[ChatDatabase] Saving current user's encrypted draft for chat:", chat_id);
        
        try {
            // Get the chat first to check if it exists
            const chat = await this.getChat(chat_id);
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
            chat.last_edited_overall_timestamp = nowTimestamp;
            chat.updated_at = nowTimestamp;
            
            console.debug('[ChatDatabase] Saving draft with preview:', {
                chatId: chat_id,
                hasDraftContent: !!draft_content,
                hasPreview: !!draft_preview,
                previewLength: draft_preview?.length || 0,
                draftVersion: chat.draft_v
            });
            
            // Use addChat without external transaction to ensure proper completion
            await this.addChat(chat);
            console.debug(`[ChatDatabase] Successfully saved draft for chat ${chat_id}`);
            return chat;
        } catch (error) {
            console.error(`[ChatDatabase] Error in saveCurrentUserChatDraft for chat ${chat_id}:`, error);
            throw error;
        }
    }
    
    async createNewChatWithCurrentUserDraft(draft_content: string, draft_preview: string | null = null): Promise<Chat> {
        console.debug(`[ChatDatabase] createNewChatWithCurrentUserDraft called with draft_content length: ${draft_content?.length}, draft_preview length: ${draft_preview?.length}`);
        await this.init();
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
            await this.addChat(chatToCreate);
            console.debug(`[ChatDatabase] Successfully created new chat ${newChatId} with draft`);
            
            // Verify the chat was actually saved by trying to retrieve it
            console.debug(`[ChatDatabase] Verifying chat ${newChatId} was saved by retrieving it...`);
            const verificationChat = await this.getChat(newChatId);
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

    async clearCurrentUserChatDraft(chat_id: string): Promise<Chat | null> {
        await this.init();
        try {
            const chat = await this.getChat(chat_id);
            if (chat) {
                // When clearing a draft, the content becomes null and version should be 0.
                chat.encrypted_draft_md = null;
                chat.encrypted_draft_preview = null; // Clear preview as well
                chat.draft_v = 0; // Reset draft version to 0
                // Still update timestamps as an operation occurred
                const nowTimestamp = Math.floor(Date.now() / 1000);
                chat.last_edited_overall_timestamp = nowTimestamp;
                chat.updated_at = nowTimestamp;
                
                // Use addChat without external transaction to ensure proper completion
                await this.addChat(chat);
                console.debug(`[ChatDatabase] Successfully cleared draft for chat ${chat_id}`);
                return chat;
            }
            return null;
        } catch (error) {
            console.error(`[ChatDatabase] Error in clearCurrentUserChatDraft for chat ${chat_id}:`, error);
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
                    resolve();
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
                resolve();
            }
        });
    }

    async saveMessage(message: Message, transaction?: IDBTransaction): Promise<void> {
        await this.init();
        
        const usesExternalTransaction = !!transaction;
        console.debug(`[ChatDatabase] saveMessage called for ${message.message_id} (chat: ${message.chat_id}, role: ${message.role}, status: ${message.status}, external tx: ${usesExternalTransaction})`);
        
        // DEFENSIVE: Validate message has required fields
        if (!message.message_id) {
            console.error(`[ChatDatabase] ❌ Cannot save message without message_id:`, message);
            throw new Error('Message must have a message_id');
        }
        if (!message.chat_id) {
            console.error(`[ChatDatabase] ❌ Cannot save message without chat_id:`, message);
            throw new Error('Message must have a chat_id');
        }
        
        // CRITICAL FIX: Do all async work BEFORE checking transaction state
        // Encrypt message content before storing in IndexedDB (zero-knowledge architecture)
        const encryptedMessage = await this.encryptMessageFields(message, message.chat_id);
        
        // CRITICAL FIX: Check existing messages WITHOUT using the transaction (to avoid expiration)
        // We'll check for duplicates using a separate read-only transaction
        let existingMessage: Message | null = null;
        let contentDuplicate: Message | null = null;
        
        try {
            // Use a separate read-only transaction to check for duplicates
            const checkTransaction = await this.getTransaction(this.MESSAGES_STORE_NAME, 'readonly');
            existingMessage = await this.getMessage(message.message_id, checkTransaction);
            
            if (!existingMessage) {
                contentDuplicate = await this.findContentDuplicate(message, checkTransaction);
            }
        } catch (checkError) {
            // If check fails, continue anyway (will handle duplicate on put)
            console.warn(`[ChatDatabase] Could not check for duplicates for ${message.message_id}:`, checkError);
        }
        
        // Handle duplicates based on check results
        if (existingMessage) {
            // Only update if the new message has higher priority status
            if (this.shouldUpdateMessage(existingMessage, message)) {
                console.info(`[ChatDatabase] ✅ DUPLICATE PREVENTED - Updating existing message with higher priority status: ${message.message_id} (${existingMessage.status} -> ${message.status})`);
            } else {
                console.info(`[ChatDatabase] ✅ DUPLICATE PREVENTED - Message ${message.message_id} already exists with equal/higher priority status (${existingMessage.status}), skipping save`);
                return Promise.resolve();
            }
        } else if (contentDuplicate) {
            console.warn(`[ChatDatabase] ⚠️ CONTENT DUPLICATE DETECTED - Found duplicate with different message_id: ${contentDuplicate.message_id} -> ${message.message_id}`);
            // Update the existing message with higher priority status if applicable
            if (this.shouldUpdateMessage(contentDuplicate, message)) {
                console.info(`[ChatDatabase] ✅ DUPLICATE PREVENTED - Updating content duplicate with higher priority: ${contentDuplicate.message_id} (${contentDuplicate.status} -> ${message.status})`);
                // Delete the old message - use a separate transaction
                try {
                    const deleteTransaction = await this.getTransaction(this.MESSAGES_STORE_NAME, 'readwrite');
                    await this.deleteMessage(contentDuplicate.message_id, deleteTransaction);
                } catch (deleteError) {
                    console.warn(`[ChatDatabase] Could not delete duplicate message ${contentDuplicate.message_id}:`, deleteError);
                }
            } else {
                console.info(`[ChatDatabase] ✅ DUPLICATE PREVENTED - Content duplicate has equal/higher priority (${contentDuplicate.status}), skipping ${message.message_id}`);
                return Promise.resolve();
            }
        } else {
            console.debug(`[ChatDatabase] No existing message found for ${message.message_id}, will insert as new`);
        }
        
        return new Promise(async (resolve, reject) => {
            // CRITICAL FIX: Check if external transaction is still active before using it
            if (usesExternalTransaction && transaction) {
                try {
                    // Try to access the transaction's mode - if it throws, the transaction is finished
                    const _ = transaction.mode;
                    if (transaction.error !== null) {
                        throw new Error(`Transaction has error: ${transaction.error}`);
                    }
                } catch (error) {
                    console.warn(`[ChatDatabase] External transaction is no longer active for message ${message.message_id}, creating new transaction`);
                    // Transaction is finished, create a new one
                    const newTransaction = await this.getTransaction(this.MESSAGES_STORE_NAME, 'readwrite');
                    const store = newTransaction.objectStore(this.MESSAGES_STORE_NAME);
                    const request = store.put(encryptedMessage);
                    
                    request.onsuccess = () => {
                        console.debug(`[ChatDatabase] Message saved/updated successfully with new transaction (queued): ${message.message_id}`);
                        resolve();
                    };
                    
                    request.onerror = () => {
                        console.error(`[ChatDatabase] Error in message store.put operation with new transaction:`, request.error);
                        reject(request.error);
                    };
                    
                    newTransaction.oncomplete = () => {
                        console.debug(`[ChatDatabase] New transaction for saveMessage completed successfully for message: ${message.message_id}`);
                    };
                    
                    newTransaction.onerror = () => {
                        console.error(`[ChatDatabase] New transaction for saveMessage failed for message: ${message.message_id}, Error:`, newTransaction.error);
                        reject(newTransaction.error);
                    };
                    
                    return;
                }
            }
            
            const currentTransaction = transaction || await this.getTransaction(this.MESSAGES_STORE_NAME, 'readwrite');
            
            // CRITICAL FIX: Check transaction state one more time right before using it
            try {
                const store = currentTransaction.objectStore(this.MESSAGES_STORE_NAME);
                const request = store.put(encryptedMessage); // Store encrypted message

                request.onsuccess = () => {
                    console.debug(`[ChatDatabase] ✅ Encrypted message saved/updated successfully (queued): ${message.message_id} (chat: ${message.chat_id})`);
                    if (usesExternalTransaction) {
                        resolve();
                    }
                };
                request.onerror = () => {
                    console.error(`[ChatDatabase] ❌ Error in message store.put operation for ${message.message_id}:`, request.error);
                    reject(request.error);
                };

                if (!usesExternalTransaction) {
                    currentTransaction.oncomplete = () => {
                        console.debug(`[ChatDatabase] ✅ Transaction for saveMessage completed successfully for message: ${message.message_id}`);
                        resolve();
                    };
                    currentTransaction.onerror = () => {
                        console.error(`[ChatDatabase] ❌ Transaction for saveMessage failed for message: ${message.message_id}, Error:`, currentTransaction.error);
                        reject(currentTransaction.error);
                    };
                }
            } catch (error: any) {
                // Transaction is no longer active (InvalidStateError or similar)
                if (error?.name === 'InvalidStateError' || error?.message?.includes('transaction')) {
                    console.warn(`[ChatDatabase] Transaction is no longer active for message ${message.message_id}, creating new transaction:`, error);
                    // Create a new transaction and retry
                    try {
                        const newTransaction = await this.getTransaction(this.MESSAGES_STORE_NAME, 'readwrite');
                        const store = newTransaction.objectStore(this.MESSAGES_STORE_NAME);
                        const request = store.put(encryptedMessage);
                        
                        request.onsuccess = () => {
                            console.debug(`[ChatDatabase] Message saved/updated successfully with new transaction (queued): ${message.message_id}`);
                            resolve();
                        };
                        
                        request.onerror = () => {
                            console.error(`[ChatDatabase] Error in message store.put operation with new transaction:`, request.error);
                            reject(request.error);
                        };
                        
                        newTransaction.oncomplete = () => {
                            console.debug(`[ChatDatabase] New transaction for saveMessage completed successfully for message: ${message.message_id}`);
                        };
                        
                        newTransaction.onerror = () => {
                            console.error(`[ChatDatabase] New transaction for saveMessage failed for message: ${message.message_id}, Error:`, newTransaction.error);
                            reject(newTransaction.error);
                        };
                    } catch (retryError) {
                        console.error(`[ChatDatabase] Failed to create new transaction for message ${message.message_id}:`, retryError);
                        reject(retryError);
                    }
                } else {
                    // Some other error - rethrow it
                    console.error(`[ChatDatabase] Unexpected error in saveMessage for message ${message.message_id}:`, error);
                    reject(error);
                }
            }
        });
    }

    /**
     * Batch save multiple messages efficiently in a single transaction
     * This method prevents transaction auto-commit issues by:
     * 1. Checking for duplicates BEFORE creating the transaction
     * 2. Encrypting all messages BEFORE creating the transaction
     * 3. Queuing all put operations synchronously (no await between them)
     * 
     * @param messages Array of messages to save
     * @returns Promise that resolves when all messages are saved
     */
    async batchSaveMessages(messages: Message[]): Promise<void> {
        await this.init();
        
        if (messages.length === 0) {
            return Promise.resolve();
        }
        
        console.debug(`[ChatDatabase] batchSaveMessages: Processing ${messages.length} messages`);
        
        // Step 1: Validate all messages have required fields
        const validMessages: Message[] = [];
        for (const message of messages) {
            if (!message.message_id) {
                console.error(`[ChatDatabase] ❌ Skipping message without message_id:`, message);
                continue;
            }
            if (!message.chat_id) {
                console.error(`[ChatDatabase] ❌ Skipping message without chat_id:`, message);
                continue;
            }
            validMessages.push(message);
        }
        
        if (validMessages.length === 0) {
            console.warn(`[ChatDatabase] No valid messages to save after validation`);
            return Promise.resolve();
        }
        
        // Step 2: Check for duplicates by fetching all existing messages in a single transaction
        // CRITICAL FIX: Use individual read transactions for each check to avoid transaction auto-commit
        // Since each check is quick, this is more reliable than trying to keep one transaction alive
        const messagesToSkip = new Set<string>();
        const existingMessagesMap = new Map<string, Message>();
        
        // First, get all existing messages by their IDs using individual quick transactions
        // This avoids the transaction auto-commit issue
        const existingMessageChecks = await Promise.all(
            validMessages.map(async (message) => {
                try {
                    // Create a fresh read transaction for each check - quick and safe
                    const checkTransaction = await this.getTransaction(this.MESSAGES_STORE_NAME, 'readonly');
                    const existingMessage = await this.getMessage(message.message_id, checkTransaction);
                    return { message, existingMessage };
                } catch (checkError) {
                    console.warn(`[ChatDatabase] batchSaveMessages: Could not check for existing message ${message.message_id}, will save anyway:`, checkError);
                    return { message, existingMessage: null };
                }
            })
        );
        
        // Process duplicate checks in memory
        for (const { message, existingMessage } of existingMessageChecks) {
            if (existingMessage) {
                existingMessagesMap.set(message.message_id, existingMessage);
                
                // Check if we should update
                if (this.shouldUpdateMessage(existingMessage, message)) {
                    console.debug(`[ChatDatabase] batchSaveMessages: Will update existing message ${message.message_id} with higher priority`);
                    // Will save below - don't skip
                } else {
                    console.debug(`[ChatDatabase] batchSaveMessages: Skipping ${message.message_id} - already exists with equal/higher priority`);
                    messagesToSkip.add(message.message_id);
                }
            } else {
                // Check for content duplicates only if message doesn't exist by ID
                // Note: Content duplicate checking is expensive, so we skip it in batch operations
                // Duplicate cleanup will handle content duplicates later
                // For now, we'll save the message and let duplicate cleanup handle it
            }
        }
        
        // Step 3: Encrypt all messages that need to be saved (BEFORE creating write transaction)
        const messagesToEncrypt = validMessages.filter(msg => !messagesToSkip.has(msg.message_id));
        const encryptionPromises = messagesToEncrypt.map(async (message) => {
            const encrypted = await this.encryptMessageFields(message, message.chat_id);
            return { message, encrypted };
        });
        
        const preparedMessages = await Promise.all(encryptionPromises);
        
        if (preparedMessages.length === 0) {
            console.debug(`[ChatDatabase] batchSaveMessages: No messages to save after duplicate checking`);
            return Promise.resolve();
        }
        
        // Step 4: Create write transaction and queue all operations synchronously
        return new Promise(async (resolve, reject) => {
            try {
                const writeTransaction = await this.getTransaction(this.MESSAGES_STORE_NAME, 'readwrite');
                const store = writeTransaction.objectStore(this.MESSAGES_STORE_NAME);
                
                // Queue all put operations synchronously (no await between them)
                // This keeps the transaction active until all operations are queued
                const requests: IDBRequest[] = [];
                for (const { encrypted } of preparedMessages) {
                    const request = store.put(encrypted);
                    requests.push(request);
                }
                
                console.debug(`[ChatDatabase] batchSaveMessages: Queued ${requests.length} put operations in transaction`);
                
                // Wait for transaction to complete
                writeTransaction.oncomplete = () => {
                    console.debug(`[ChatDatabase] batchSaveMessages: Transaction completed successfully for ${requests.length} messages`);
                    resolve();
                };
                
                writeTransaction.onerror = () => {
                    console.error(`[ChatDatabase] batchSaveMessages: Transaction error:`, writeTransaction.error);
                    reject(writeTransaction.error);
                };
                
                writeTransaction.onabort = () => {
                    console.error(`[ChatDatabase] batchSaveMessages: Transaction aborted`);
                    reject(new Error('Transaction aborted'));
                };
                
                // Check for any request errors
                for (const request of requests) {
                    request.onerror = () => {
                        console.error(`[ChatDatabase] batchSaveMessages: Request error for message:`, request.error);
                        // Don't reject here - let transaction error handler handle it
                    };
                }
            } catch (error) {
                console.error(`[ChatDatabase] batchSaveMessages: Error creating transaction:`, error);
                reject(error);
            }
        });
    }

    async getMessagesForChat(chat_id: string, transaction?: IDBTransaction): Promise<Message[]> {
        await this.init();
        return new Promise(async (resolve, reject) => {
            const currentTransaction = transaction || await this.getTransaction(this.MESSAGES_STORE_NAME, 'readonly');
            const store = currentTransaction.objectStore(this.MESSAGES_STORE_NAME);
            const index = store.index('chat_id_created_at'); // Use compound index for fetching and sorting
            const request = index.getAll(IDBKeyRange.bound([chat_id, -Infinity], [chat_id, Infinity])); // Get all for chat_id, sorted by created_at

            request.onsuccess = async () => {
                const encryptedMessages = request.result || [];
                // Decrypt all messages before returning (zero-knowledge architecture)
                // CRITICAL FIX: await all decryption operations since decryptMessageFields is now async
                const decryptedMessages = await Promise.all(
                    encryptedMessages.map(msg => this.decryptMessageFields(msg, chat_id))
                );
                resolve(decryptedMessages);
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
                const encryptedMessage = request.result;
                if (!encryptedMessage) {
                    resolve(null);
                    return;
                }
                // Decrypt message before returning (zero-knowledge architecture)
                // CRITICAL FIX: await decryption operation since decryptMessageFields is now async
                (async () => {
                    const decryptedMessage = await this.decryptMessageFields(encryptedMessage, encryptedMessage.chat_id);
                    resolve(decryptedMessage);
                })();
            };
            request.onerror = () => {
                console.error(`[ChatDatabase] Error getting message ${message_id}:`, request.error);
                reject(request.error);
            };
        });
    }

    /**
     * Determines if a new message should update an existing message based on status priority
     * Status priority: 'sending' < 'delivered' < 'synced'
     */
    private shouldUpdateMessage(existing: Message, incoming: Message): boolean {
        const statusPriority: Record<string, number> = { 
            'sending': 1, 
            'delivered': 2, 
            'synced': 3 
        };
        
        const existingPriority = statusPriority[existing.status] || 0;
        const incomingPriority = statusPriority[incoming.status] || 0;
        
        // Update if incoming message has higher priority status
        return incomingPriority > existingPriority;
    }

    /**
     * Finds content-based duplicates (same content but different message_id)
     * This handles cases where the same logical message has different IDs from different sync sources
     */
    private async findContentDuplicate(message: Message, transaction?: IDBTransaction): Promise<Message | null> {
        try {
            // Get all messages for the same chat
            const chatMessages = await this.getMessagesForChat(message.chat_id, transaction);
            
            // Look for messages with same content, role, and similar timestamp
            for (const existingMessage of chatMessages) {
                if (existingMessage.message_id === message.message_id) {
                    continue; // Skip same message_id
                }
                
                // Check if it's the same logical message based on content and timing
                if (this.isContentDuplicate(existingMessage, message)) {
                    return existingMessage;
                }
            }
            
            return null;
        } catch (error) {
            console.error("[ChatDatabase] Error finding content duplicate:", error);
            return null;
        }
    }

    /**
     * Determines if two messages are content duplicates (same logical message, different IDs)
     */
    private isContentDuplicate(existing: Message, incoming: Message): boolean {
        // Must be same chat, role, and have similar content
        if (existing.chat_id !== incoming.chat_id || existing.role !== incoming.role) {
            return false;
        }
        
        // Check if content is similar (for encrypted content, we compare the encrypted strings)
        const contentMatch = existing.encrypted_content === incoming.encrypted_content;
        
        // Check if timestamps are close (within 5 minutes) - messages from different sync sources
        const timeDiff = Math.abs(existing.created_at - incoming.created_at);
        const timeMatch = timeDiff < 300; // 5 minutes in seconds
        
        // Check if sender names match (for user messages)
        const senderMatch = existing.encrypted_sender_name === incoming.encrypted_sender_name;
        
        return contentMatch && timeMatch && senderMatch;
    }

    /**
     * Clean up duplicate messages by keeping the one with highest priority status
     * This method should be called during initialization to clean up existing duplicates
     */
    async cleanupDuplicateMessages(): Promise<void> {
        // NOTE: Do NOT call this.init() here! This method is called FROM init()
        // and calling it again would create a deadlock waiting for itself to finish.
        console.debug("[ChatDatabase] Starting duplicate message cleanup...");
        
        try {
            // Get all messages grouped by chat
            // Pass duringInit=true since this is called from init()
            const allMessages = await this.getAllMessages(true);
            const messagesByChat = new Map<string, Message[]>();
            
            // Group messages by chat_id
            allMessages.forEach(msg => {
                if (!messagesByChat.has(msg.chat_id)) {
                    messagesByChat.set(msg.chat_id, []);
                }
                messagesByChat.get(msg.chat_id)!.push(msg);
            });
            
            let duplicatesRemoved = 0;
            
            // Process each chat's messages for duplicates
            const chatIds = Array.from(messagesByChat.keys());
            for (const chatId of chatIds) {
                const messages = messagesByChat.get(chatId)!;
                const processedMessages = new Set<string>();
                
                for (let i = 0; i < messages.length; i++) {
                    const currentMessage = messages[i];
                    
                    if (processedMessages.has(currentMessage.message_id)) {
                        continue; // Already processed
                    }
                    
                    // Find all duplicates of this message (same message_id or content duplicates)
                    const duplicates = [currentMessage];
                    
                    for (let j = i + 1; j < messages.length; j++) {
                        const otherMessage = messages[j];
                        
                        if (processedMessages.has(otherMessage.message_id)) {
                            continue; // Already processed
                        }
                        
                        // Check for exact message_id match or content duplicate
                        if (currentMessage.message_id === otherMessage.message_id || 
                            this.isContentDuplicate(currentMessage, otherMessage)) {
                            duplicates.push(otherMessage);
                            processedMessages.add(otherMessage.message_id);
                        }
                    }
                    
                    if (duplicates.length > 1) {
                        console.debug(`[ChatDatabase] Found ${duplicates.length} duplicates for message ${currentMessage.message_id} in chat ${chatId}`);
                        
                        // Find the message with highest priority status
                        const statusPriority: Record<string, number> = { 
                            'sending': 1, 
                            'delivered': 2, 
                            'synced': 3 
                        };
                        
                        const bestMessage = duplicates.reduce((best, current) => {
                            const bestPriority = statusPriority[best.status] || 0;
                            const currentPriority = statusPriority[current.status] || 0;
                            return currentPriority > bestPriority ? current : best;
                        });
                        
                        // Delete all duplicates except the best one
                        const toDelete = duplicates.filter(msg => msg !== bestMessage);
                        for (const duplicate of toDelete) {
                            await this.deleteMessage(duplicate.message_id);
                            duplicatesRemoved++;
                        }
                        
                        console.debug(`[ChatDatabase] Kept message ${bestMessage.message_id} with status '${bestMessage.status}', removed ${toDelete.length} duplicates`);
                    }
                    
                    processedMessages.add(currentMessage.message_id);
                }
            }
            
            console.debug(`[ChatDatabase] Duplicate cleanup completed. Removed ${duplicatesRemoved} duplicate messages.`);
        } catch (error) {
            console.error("[ChatDatabase] Error during duplicate cleanup:", error);
        }
    }

    /**
     * Get all messages from the database
     * Used for retrying pending messages when connection is restored
     * Can be called during init() (via cleanupDuplicateMessages) or after init()
     * @param duringInit If true, uses getTransactionDuringInit instead of getTransaction
     * @returns Promise resolving to array of all messages
     */
    async getAllMessages(duringInit: boolean = false): Promise<Message[]> {
        // Only call init() if not already during init (to avoid deadlock)
        if (!duringInit) {
            await this.init();
        }
        
        return new Promise(async (resolve, reject) => {
            // Use appropriate transaction method based on context
            const transaction = duringInit 
                ? this.getTransactionDuringInit(this.MESSAGES_STORE_NAME, 'readonly')
                : await this.getTransaction(this.MESSAGES_STORE_NAME, 'readonly');
            
            const store = transaction.objectStore(this.MESSAGES_STORE_NAME);
            const request = store.getAll();

            request.onsuccess = async () => {
                const encryptedMessages = request.result || [];
                // Decrypt all messages before returning (zero-knowledge architecture)
                // CRITICAL FIX: await all decryption operations since decryptMessageFields is now async
                const decryptedMessages = await Promise.all(
                    encryptedMessages.map(msg => this.decryptMessageFields(msg, msg.chat_id))
                );
                resolve(decryptedMessages);
            };
            request.onerror = () => {
                console.error("[ChatDatabase] Error getting all messages:", request.error);
                reject(request.error);
            };
        });
    }

    /**
     * Delete a specific message by message_id
     * NOTE: Can be called during init() cleanup, so init() must already be in progress
     */
    async deleteMessage(message_id: string, transaction?: IDBTransaction): Promise<void> {
        return new Promise(async (resolve, reject) => {
            const currentTransaction = transaction || this.getTransactionDuringInit(this.MESSAGES_STORE_NAME, 'readwrite');
            const store = currentTransaction.objectStore(this.MESSAGES_STORE_NAME);
            const request = store.delete(message_id);

            request.onsuccess = () => {
                console.debug("[ChatDatabase] Message deleted successfully:", message_id);
                resolve();
            };
            request.onerror = () => {
                console.error("[ChatDatabase] Error deleting message:", request.error);
                reject(request.error);
            };

            if (!transaction) {
                currentTransaction.oncomplete = () => resolve();
                currentTransaction.onerror = () => reject(currentTransaction.error);
            }
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

        if (typeof (chatMetadata.created_at as any) === 'string' || (chatMetadata.created_at as any) instanceof Date) {
            chatMetadata.created_at = Math.floor(new Date(chatMetadata.created_at as any).getTime() / 1000);
        }
        if (typeof (chatMetadata.updated_at as any) === 'string' || (chatMetadata.updated_at as any) instanceof Date) {
            chatMetadata.updated_at = Math.floor(new Date(chatMetadata.updated_at as any).getTime() / 1000);
        }
                    if (chatMetadata.encrypted_draft_md === undefined) chatMetadata.encrypted_draft_md = null;
        if (chatMetadata.encrypted_draft_preview === undefined) chatMetadata.encrypted_draft_preview = null;
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
    batchProcessChatData(
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
            if (typeof (chatMetadata.created_at as any) === 'string' || (chatMetadata.created_at as any) instanceof Date) {
                chatMetadata.created_at = Math.floor(new Date(chatMetadata.created_at as any).getTime() / 1000);
            }
            if (typeof (chatMetadata.updated_at as any) === 'string' || (chatMetadata.updated_at as any) instanceof Date) {
                chatMetadata.updated_at = Math.floor(new Date(chatMetadata.updated_at as any).getTime() / 1000);
            }
            if (chatMetadata.encrypted_draft_md === undefined) chatMetadata.encrypted_draft_md = null;
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
        
        // By returning a promise that resolves when all sub-promises have resolved,
        // we allow the caller to await the completion of all database operations
        // without holding up the transaction.
        return Promise.all(promises).then(() => {});
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
                chat.updated_at = Math.floor(Date.now() / 1000);
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
                chat.updated_at = Math.floor(Date.now() / 1000); 
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

    // Update chat scroll position
    async updateChatScrollPosition(chat_id: string, message_id: string): Promise<void> {
        await this.init();
        const tx = await this.getTransaction(this.CHATS_STORE_NAME, 'readwrite');
        try {
            const chat = await this.getChat(chat_id, tx);
            if (chat) {
                chat.last_visible_message_id = message_id;
                chat.updated_at = Math.floor(Date.now() / 1000);
                await this.addChat(chat, tx);
                console.debug(`[ChatDatabase] Updated scroll position for chat ${chat_id}: message ${message_id}`);
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

    // Update chat read status (unread count)
    async updateChatReadStatus(chat_id: string, unread_count: number): Promise<void> {
        await this.init();
        const tx = await this.getTransaction(this.CHATS_STORE_NAME, 'readwrite');
        try {
            const chat = await this.getChat(chat_id, tx);
            if (chat) {
                chat.unread_count = unread_count;
                chat.updated_at = Math.floor(Date.now() / 1000);
                await this.addChat(chat, tx);
                console.debug(`[ChatDatabase] Updated read status for chat ${chat_id}: unread_count = ${unread_count}`);
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

    /**
     * Deletes the IndexedDB database.
     * This method closes the current connection and waits for all active transactions
     * to complete before attempting deletion. If deletion is blocked (due to other
     * connections), it will wait for those connections to close automatically.
     * 
     * Note: The onblocked event doesn't mean deletion failed - it means deletion
     * is waiting for other connections to close. Once they close, deletion proceeds
     * automatically and onsuccess will fire.
     */
    async deleteDatabase(): Promise<void> {
        console.debug(`[ChatDatabase] Attempting to delete database: ${this.DB_NAME}`);
        
        // Set deletion flag to prevent new operations
        this.isDeleting = true;
        
        return new Promise((resolve, reject) => {
            // Close the current database connection first
            // This will abort any active transactions in this connection
            if (this.db) {
                this.db.close(); 
                this.db = null;
                console.debug(`[ChatDatabase] Database connection closed for ${this.DB_NAME}.`);
            }
            this.initializationPromise = null; // Reset initialization promise

            // Wait briefly for any active transactions to complete/abort
            // This gives IndexedDB time to clean up the connection
            setTimeout(() => {
                const request = indexedDB.deleteDatabase(this.DB_NAME);

                request.onsuccess = () => {
                    console.debug(`[ChatDatabase] Database ${this.DB_NAME} deleted successfully.`);
                    this.isDeleting = false; // Reset flag on success
                    resolve();
                };

                request.onerror = (event) => {
                    console.error(`[ChatDatabase] Error deleting database ${this.DB_NAME}:`, (event.target as IDBOpenDBRequest).error);
                    this.isDeleting = false; // Reset flag on error
                    reject((event.target as IDBOpenDBRequest).error);
                };

                /**
                 * The onblocked event fires when there are other connections to the database
                 * (e.g., in other tabs or from pending transactions). This doesn't mean
                 * deletion failed - IndexedDB will automatically proceed with deletion
                 * once all connections are closed. We log a warning but don't reject,
                 * allowing the promise to resolve when onsuccess eventually fires.
                 */
                request.onblocked = (event) => {
                    console.warn(
                        `[ChatDatabase] Deletion of database ${this.DB_NAME} is waiting for other connections to close. ` +
                        `This is normal if you have other tabs open or active transactions. ` +
                        `Deletion will proceed automatically once connections close.`,
                        event
                    );
                    // Don't reject here - wait for onsuccess to fire once connections close
                    // The deletion will complete automatically when all connections are closed
                };
            }, 100); // Brief delay to allow connection cleanup
        });
    }

    // ============================================================================
    // CHAT KEY MANAGEMENT METHODS
    // ============================================================================

    /**
     * Get chat key from cache or generate new one
     */
    public getChatKey(chatId: string): Uint8Array | null {
        // First check if key is in cache
        const cachedKey = this.chatKeys.get(chatId);
        if (cachedKey) {
            return cachedKey;
        }
        
        // If not in cache, try to load from database
        // This is a synchronous method, so we can't await here
        // The ChatMetadataCache will handle loading the key when needed
        return null;
    }

    /**
     * Set chat key in cache
     */
    public setChatKey(chatId: string, chatKey: Uint8Array): void {
        this.chatKeys.set(chatId, chatKey);
    }

    /**
     * Load chat keys from database into cache
     * This should be called when the database is initialized to load all chat keys
     * NOTE: This method must NOT call init() or any method that calls init() to avoid circular dependency
     */
    public async loadChatKeysFromDatabase(): Promise<void> {
        // Don't call getAllChats() here as it calls init(), causing a circular dependency!
        // Instead, directly access the database that's already initialized
        if (!this.db) {
            console.warn('[ChatDatabase] Database not initialized yet, skipping chat key loading');
            return;
        }
        
        return new Promise((resolve, reject) => {
            try {
                const transaction = this.db!.transaction(this.CHATS_STORE_NAME, 'readonly');
                const store = transaction.objectStore(this.CHATS_STORE_NAME);
                const request = store.openCursor();
                
                // CRITICAL FIX: Collect all chat keys to decrypt, then decrypt them after cursor is done
                // Cannot await inside cursor callback because transaction would finish before cursor.continue()
                const keysToDecrypt: Array<{ chatId: string; encryptedKey: string }> = [];
                
                request.onsuccess = (event) => {
                    const cursor = (event.target as IDBRequest<IDBCursorWithValue>).result;
                    if (cursor) {
                        const chat = cursor.value;
                        if (chat.encrypted_chat_key && !this.chatKeys.has(chat.chat_id)) {
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
                                const { decryptChatKeyWithMasterKey } = await import('./cryptoService');
                                for (const { chatId, encryptedKey } of keysToDecrypt) {
                                    try {
                                        // CRITICAL FIX: await decryptChatKeyWithMasterKey since it's async
                                        // This ensures we get a Uint8Array instead of a Promise
                                        const chatKey = await decryptChatKeyWithMasterKey(encryptedKey);
                                        if (chatKey) {
                                            this.chatKeys.set(chatId, chatKey);
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
     * Clear chat key from cache
     */
    private clearChatKey(chatId: string): void {
        this.chatKeys.delete(chatId);
    }

    /**
     * Clear all chat keys from cache
     */
    public clearAllChatKeys(): void {
        this.chatKeys.clear();
    }

    /**
     * Get or generate chat key for a specific chat
     */
    public getOrGenerateChatKey(chatId: string): Uint8Array {
        let chatKey = this.getChatKey(chatId);
        if (!chatKey) {
            // Try to load chat key from database
            // This is a synchronous method, so we can't await here
            // The loadChatKeysFromDatabase method should have loaded all keys during initialization
            // If not, we'll generate a new key (which might cause decryption issues)
            console.warn(`[ChatDatabase] Chat key not found in cache for chat ${chatId}, generating new key. This may cause decryption issues.`);
            chatKey = generateChatKey();
            this.setChatKey(chatId, chatKey);
        }
        return chatKey;
    }

    /**
     * Encrypt message fields with chat-specific key for storage (removes plaintext)
     * EXCEPTION: Public chat messages (chatId starting with 'demo-' or 'legal-') are NOT encrypted
     * since they contain public template content that's the same for all users
     * 
     * CRITICAL: This function is now async because encryptWithChatKey is async.
     * All callers must await this function to prevent storing Promises in IndexedDB.
     */
    public async encryptMessageFields(message: Message, chatId: string): Promise<Message> {
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
        const chatKey = this.getOrGenerateChatKey(chatId);

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

        return encryptedMessage;
    }

    /**
     * Get encrypted fields only (for dual-content approach - preserves original message)
     * CRITICAL: This function is now async because encryptWithChatKey is async.
     * All callers must await this function to prevent storing Promises in IndexedDB.
     */
    public async getEncryptedFields(message: Message, chatId: string): Promise<{ encrypted_content?: string, encrypted_sender_name?: string, encrypted_category?: string }> {
        const chatKey = this.getOrGenerateChatKey(chatId);
        const encryptedFields: { encrypted_content?: string, encrypted_sender_name?: string, encrypted_category?: string } = {};

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

        return encryptedFields;
    }

    /**
     * Get encrypted chat key for server storage (zero-knowledge architecture)
     * The server needs this to store the encrypted chat key in Directus for device sync
     */
    public async getEncryptedChatKey(chatId: string): Promise<string | null> {
        try {
            const chat = await this.getChat(chatId);
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
     * Decrypt message fields with chat-specific key
     * DEFENSIVE: Handles malformed encrypted content from incomplete message sync
     * EXCEPTION: Public chat messages (chatId starting with 'demo-' or 'legal-') are NOT decrypted
     * since they're stored as plaintext (public template content)
     */
    public async decryptMessageFields(message: Message, chatId: string): Promise<Message> {
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
        const chatKey = this.getChatKey(chatId);

        if (!chatKey) {
            console.warn(`[ChatDatabase] No chat key found for chat ${chatId}, cannot decrypt message fields`);
            return decryptedMessage;
        }

        // CRITICAL FIX: Import decryptWithChatKey and await all async decryption calls
        const { decryptWithChatKey } = await import('./cryptoService');

        // Decrypt content if present
        if (message.encrypted_content) {
            try {
                const decryptedContentString = await decryptWithChatKey(message.encrypted_content, chatKey);
                if (decryptedContentString) {
                    // Content is now a markdown string (never Tiptap JSON on server!)
                    decryptedMessage.content = decryptedContentString;
                    // Clear encrypted field
                    delete decryptedMessage.encrypted_content;
                } else {
                    // Decryption failed but didn't throw - encrypted_content might be malformed
                    console.warn(`[ChatDatabase] Failed to decrypt content for message ${message.message_id} - encrypted_content present but decryption returned null`);
                    // Keep encrypted field for debugging, set content to placeholder
                    decryptedMessage.content = message.content || '[Content decryption failed]';
                }
            } catch (error) {
                // DEFENSIVE: Handle malformed encrypted_content (e.g., from messages with status 'sending' that never completed encryption)
                console.error(`[ChatDatabase] Error decrypting content for message ${message.message_id} (status: ${message.status}):`, error);
                // If message already has plaintext content, use it (common for status='sending')
                if (message.content) {
                    console.warn(`[ChatDatabase] Using existing plaintext content for message ${message.message_id} - encryption may not have completed`);
                    decryptedMessage.content = message.content;
                } else {
                    decryptedMessage.content = '[Content decryption failed]';
                }
                // Keep encrypted_content for debugging
            }
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

        return decryptedMessage;
    }

    /**
     * Save new chat suggestions (keeps last 50, encrypted with master key)
     */
    async saveNewChatSuggestions(suggestions: string[], chatId: string): Promise<void> {
        if (!this.db) throw new Error('[ChatDatabase] Database not initialized');

        try {
            // First, get existing suggestions to check for duplicates
            const existingSuggestions = await this.getAllNewChatSuggestions();
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

            const transaction = this.db.transaction([this.NEW_CHAT_SUGGESTIONS_STORE_NAME], 'readwrite');
            const store = transaction.objectStore(this.NEW_CHAT_SUGGESTIONS_STORE_NAME);

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
            const allSuggestions = await this.getAllNewChatSuggestions();

            // Keep only the last 50
            if (allSuggestions.length > 50) {
                const transaction2 = this.db.transaction([this.NEW_CHAT_SUGGESTIONS_STORE_NAME], 'readwrite');
                const store2 = transaction2.objectStore(this.NEW_CHAT_SUGGESTIONS_STORE_NAME);

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
     */
    async saveEncryptedNewChatSuggestions(encryptedSuggestions: string[], chatId: string): Promise<void> {
        if (!this.db) throw new Error('[ChatDatabase] Database not initialized');

        try {
            // First, get existing suggestions to check for duplicates
            const existingSuggestions = await this.getAllNewChatSuggestions();
            const existingEncryptedSet = new Set(existingSuggestions.map(s => s.encrypted_suggestion));
            
            // Filter out suggestions that already exist (deduplicate)
            const newSuggestionsToAdd: string[] = [];
            for (const encryptedSuggestion of encryptedSuggestions) {
                if (encryptedSuggestion && !existingEncryptedSet.has(encryptedSuggestion)) {
                    newSuggestionsToAdd.push(encryptedSuggestion);
                }
            }
            
            if (newSuggestionsToAdd.length === 0) {
                console.debug('[ChatDatabase] No new encrypted suggestions to add (all duplicates)');
                return;
            }
            
            console.debug(`[ChatDatabase] Adding ${newSuggestionsToAdd.length}/${encryptedSuggestions.length} new encrypted suggestions (filtered ${encryptedSuggestions.length - newSuggestionsToAdd.length} duplicates)`);

            const transaction = this.db.transaction([this.NEW_CHAT_SUGGESTIONS_STORE_NAME], 'readwrite');
            const store = transaction.objectStore(this.NEW_CHAT_SUGGESTIONS_STORE_NAME);

            // Add already-encrypted suggestions directly (no re-encryption)
            // CRITICAL: Track individual add operations to catch errors
            const addPromises: Promise<void>[] = [];
            const now = Math.floor(Date.now() / 1000);
            
            for (const encryptedSuggestion of newSuggestionsToAdd) {
                const suggestionRecord: NewChatSuggestion = {
                    id: crypto.randomUUID(),
                    encrypted_suggestion: encryptedSuggestion,
                    chat_id: chatId,
                    created_at: now
                };
                
                // Create promise for each add operation to catch individual errors
                const addPromise = new Promise<void>((resolve, reject) => {
                    const request = store.add(suggestionRecord);
                    request.onsuccess = () => {
                        console.debug(`[ChatDatabase] Successfully queued suggestion ${suggestionRecord.id.substring(0, 8)}...`);
                        resolve();
                    };
                    request.onerror = () => {
                        console.error(`[ChatDatabase] Error adding suggestion ${suggestionRecord.id.substring(0, 8)}...:`, request.error);
                        // Don't reject - log and continue with other suggestions
                        // This prevents one bad suggestion from blocking all others
                        resolve();
                    };
                });
                
                addPromises.push(addPromise);
            }

            // Wait for all individual add operations to complete
            await Promise.all(addPromises);
            console.debug(`[ChatDatabase] All ${addPromises.length} suggestion add operations queued`);

            // Wait for transaction to complete
            await new Promise<void>((resolve, reject) => {
                transaction.oncomplete = () => {
                    console.debug(`[ChatDatabase] Transaction completed successfully for ${newSuggestionsToAdd.length} suggestions`);
                    resolve();
                };
                transaction.onerror = () => {
                    console.error('[ChatDatabase] Transaction error saving suggestions:', transaction.error);
                    reject(transaction.error);
                };
                transaction.onabort = () => {
                    console.error('[ChatDatabase] Transaction aborted while saving suggestions');
                    reject(new Error('Transaction aborted'));
                };
            });

            // Small delay to ensure transaction is fully committed before querying
            await new Promise(resolve => setTimeout(resolve, 50));
            
            // Get all suggestions sorted by created_at (newest first) to verify save
            const allSuggestions = await this.getAllNewChatSuggestions();
            console.debug(`[ChatDatabase] Verification: Found ${allSuggestions.length} total suggestions in IndexedDB after save`);

            // Keep only the last 50
            if (allSuggestions.length > 50) {
                console.debug(`[ChatDatabase] Trimming suggestions to last 50 (current: ${allSuggestions.length})`);
                const transaction2 = this.db.transaction([this.NEW_CHAT_SUGGESTIONS_STORE_NAME], 'readwrite');
                const store2 = transaction2.objectStore(this.NEW_CHAT_SUGGESTIONS_STORE_NAME);

                // Delete oldest suggestions
                const suggestionsToDelete = allSuggestions.slice(50);
                for (const suggestion of suggestionsToDelete) {
                    store2.delete(suggestion.id);
                }

                await new Promise<void>((resolve, reject) => {
                    transaction2.oncomplete = () => {
                        console.debug(`[ChatDatabase] Trimmed ${suggestionsToDelete.length} oldest suggestions`);
                        resolve();
                    };
                    transaction2.onerror = () => {
                        console.error('[ChatDatabase] Error trimming suggestions:', transaction2.error);
                        reject(transaction2.error);
                    };
                });
            }

            // Final verification count
            const finalCount = await this.getAllNewChatSuggestions();
            console.debug(`[ChatDatabase] ✅ Saved ${newSuggestionsToAdd.length} new encrypted chat suggestions. Final count: ${finalCount.length} (keeping last 50)`);
        } catch (error) {
            console.error('[ChatDatabase] Error saving encrypted new chat suggestions:', error);
            throw error;
        }
    }

    /**
     * Get all new chat suggestions (sorted by created_at, newest first)
     */
    async getAllNewChatSuggestions(): Promise<NewChatSuggestion[]> {
        if (!this.db) throw new Error('[ChatDatabase] Database not initialized');

        return new Promise((resolve, reject) => {
            const transaction = this.db!.transaction([this.NEW_CHAT_SUGGESTIONS_STORE_NAME], 'readonly');
            const store = transaction.objectStore(this.NEW_CHAT_SUGGESTIONS_STORE_NAME);
            const index = store.index('created_at');
            const request = index.openCursor(null, 'prev'); // Get newest first

            const suggestions: NewChatSuggestion[] = [];
            request.onsuccess = (event) => {
                const cursor = (event.target as IDBRequest<IDBCursorWithValue>).result;
                if (cursor) {
                    suggestions.push(cursor.value);
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
     */
    async getRandomNewChatSuggestions(count: number = 3): Promise<string[]> {
        const allSuggestions = await this.getAllNewChatSuggestions();

        // Decrypt suggestions
        const decryptedSuggestions = allSuggestions
            .map(s => decryptWithMasterKey(s.encrypted_suggestion))
            .filter((s): s is string => s !== null);

        // Shuffle and return N random suggestions
        const shuffled = decryptedSuggestions.sort(() => Math.random() - 0.5);
        return shuffled.slice(0, Math.min(count, shuffled.length));
    }

    /**
     * Delete a new chat suggestion by its decrypted text (when user clicks and sends it as a message)
     * This encrypts the text to find and delete the matching encrypted suggestion
     */
    async deleteNewChatSuggestionByText(suggestionText: string): Promise<boolean> {
        if (!this.db) throw new Error('[ChatDatabase] Database not initialized');

        try {
            // CRITICAL FIX: await encryptWithMasterKey since it's async to prevent storing Promises
            // Encrypt the suggestion text to match against stored encrypted suggestions
            const encryptedText = await encryptWithMasterKey(suggestionText);
            if (!encryptedText) {
                console.error('[ChatDatabase] Failed to encrypt suggestion text for deletion');
                return false;
            }

            // Find the suggestion record that matches the encrypted text
            const allSuggestions = await this.getAllNewChatSuggestions();
            const suggestionToDelete = allSuggestions.find(s => s.encrypted_suggestion === encryptedText);

            if (!suggestionToDelete) {
                console.warn('[ChatDatabase] Suggestion not found for deletion:', suggestionText);
                return false;
            }

            // Delete the suggestion
            const transaction = this.db.transaction([this.NEW_CHAT_SUGGESTIONS_STORE_NAME], 'readwrite');
            const store = transaction.objectStore(this.NEW_CHAT_SUGGESTIONS_STORE_NAME);
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
    async deleteNewChatSuggestionById(suggestionId: string): Promise<boolean> {
        if (!this.db) throw new Error('[ChatDatabase] Database not initialized');

        try {
            const transaction = this.db.transaction([this.NEW_CHAT_SUGGESTIONS_STORE_NAME], 'readwrite');
            const store = transaction.objectStore(this.NEW_CHAT_SUGGESTIONS_STORE_NAME);
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

}

export const chatDB = new ChatDatabase();
