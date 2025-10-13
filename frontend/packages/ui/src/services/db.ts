// frontend/packages/ui/src/services/db.ts
// Manages IndexedDB storage for chat-related data.
import type { Chat, Message, TiptapJSON, ChatComponentVersions, OfflineChange } from '../types/chat';
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
    // Version incremented due to schema change (adding encrypted_draft_preview field)
    private readonly VERSION = 9;
    private initializationPromise: Promise<void> | null = null;
    
    // Chat key cache for performance
    private chatKeys: Map<string, Uint8Array> = new Map();

    /**
     * Initialize the database
     */
    async init(): Promise<void> {
        if (this.initializationPromise) {
            return this.initializationPromise;
        }

        this.initializationPromise = new Promise(async (resolve, reject) => {
            console.debug("[ChatDatabase] Initializing database, Version:", this.VERSION);
            const request = indexedDB.open(this.DB_NAME, this.VERSION);

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

                // Data migration for version 7: rename timestamp to created_at in messages
                if (transaction && event.oldVersion < 7) {
                    console.info(`[ChatDatabase] Migrating messages for version ${event.oldVersion} to ${event.newVersion}: renaming timestamp to created_at`);
                    const messagesStore = transaction.objectStore(this.MESSAGES_STORE_NAME);
                    messagesStore.openCursor().onsuccess = (e) => {
                        const cursor = (e.target as IDBRequest<IDBCursorWithValue>).result;
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
     */
    private encryptChatForStorage(chat: Chat): Chat {
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
            chatKey = decryptChatKeyWithMasterKey(chat.encrypted_chat_key);
            if (chatKey) {
                this.setChatKey(chat.chat_id, chatKey);
                encryptedChat.encrypted_chat_key = chat.encrypted_chat_key; // Keep the server's encrypted key
            } else {
                console.error(`[ChatDatabase] Failed to decrypt chat key for chat ${chat.chat_id}`);
            }
        } else if (!chatKey) {
            // No cached key and no server key - generate new one (new chat creation)
            chatKey = generateChatKey();
            this.setChatKey(chat.chat_id, chatKey);
            // Encrypt and store new chat key
            const encryptedChatKey = encryptChatKeyWithMasterKey(chatKey);
            if (encryptedChatKey) {
                encryptedChat.encrypted_chat_key = encryptedChatKey;
            }
        } else {
            // Key already in cache - make sure encrypted version is in the chat object
            if (!chat.encrypted_chat_key) {
                const encryptedChatKey = encryptChatKeyWithMasterKey(chatKey);
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
     */
    private async decryptChatFromStorage(chat: Chat): Promise<Chat> {
        const decryptedChat = { ...chat };
        
        // Ensure required fields have default values if they're undefined
        // This handles cases where older database records might not have these fields
        // Only set defaults if the value is truly undefined (not 0, which is a valid value)
        if (decryptedChat.messages_v === undefined) {
            decryptedChat.messages_v = 0;
            console.warn(`[ChatDatabase] messages_v was undefined for chat ${chat.chat_id}, setting to 0`);
        }
        if (decryptedChat.title_v === undefined) {
            decryptedChat.title_v = 0;
            console.warn(`[ChatDatabase] title_v was undefined for chat ${chat.chat_id}, setting to 0`);
        }
        if (decryptedChat.draft_v === undefined) {
            decryptedChat.draft_v = 0;
            console.warn(`[ChatDatabase] draft_v was undefined for chat ${chat.chat_id}, setting to 0`);
        }
        
        // Title decryption is handled by the UI layer when needed
        // The database layer just stores encrypted titles
        // No need to decrypt here as the UI will handle decryption on demand

        // Handle decryption of new encrypted fields with chat-specific key
        if (chat.encrypted_chat_key) {
            // Get chat key from encrypted_chat_key
            let chatKey = this.getChatKey(chat.chat_id);
            if (!chatKey) {
                chatKey = decryptChatKeyWithMasterKey(chat.encrypted_chat_key);
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
        const chatToSave = this.encryptChatForStorage(chat);
        delete (chatToSave as any).messages;
        
        console.debug(`[ChatDatabase] Chat to save after encryption:`, {
            chatId: chatToSave.chat_id,
            hasEncryptedDraftMd: !!chatToSave.encrypted_draft_md,
            hasEncryptedDraftPreview: !!chatToSave.encrypted_draft_preview,
            hasEncryptedTitle: !!chatToSave.encrypted_title,
            hasEncryptedIcon: !!chatToSave.encrypted_icon,
            hasEncryptedCategory: !!chatToSave.encrypted_category,
            encryptedIconPreview: chatToSave.encrypted_icon?.substring(0, 20) || 'null',
            encryptedCategoryPreview: chatToSave.encrypted_category?.substring(0, 20) || 'null',
            draftVersion: chatToSave.draft_v,
            encryptedDraftMdLength: chatToSave.encrypted_draft_md?.length || 0,
            encryptedDraftPreviewLength: chatToSave.encrypted_draft_preview?.length || 0
        });

        return new Promise(async (resolve, reject) => {
            const usesExternalTransaction = !!transaction;
            const currentTransaction = transaction || await this.getTransaction(this.CHATS_STORE_NAME, 'readwrite');
            
            console.debug(`[ChatDatabase] Using ${usesExternalTransaction ? 'external' : 'internal'} transaction for chat ${chatToSave.chat_id}`);
            
            const store = currentTransaction.objectStore(this.CHATS_STORE_NAME);
            const request = store.put(chatToSave);
            
            console.debug(`[ChatDatabase] IndexedDB put request initiated for chat ${chatToSave.chat_id}`);

            request.onsuccess = () => {
                console.debug("[ChatDatabase] Chat added/updated successfully (queued):", chatToSave.chat_id, "Versions:", {m: chatToSave.messages_v, t: chatToSave.title_v, d: chatToSave.draft_v});
                if (usesExternalTransaction) {
                    console.debug(`[ChatDatabase] External transaction - resolving immediately for chat ${chatToSave.chat_id}`);
                    resolve(); // Operation successful within the external transaction
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
            
            console.debug(`[ChatDatabase] Starting to retrieve chats from IndexedDB...`);
         
            request.onsuccess = async () => {
                const cursor = request.result;
                if (cursor) {
                    // Ensure messages property is not on the chat object returned
                    const chatData = { ...cursor.value };
                    delete (chatData as any).messages;
                    const decryptedChat = await this.decryptChatFromStorage(chatData);
                    chats.push(decryptedChat);
                    console.debug(`[ChatDatabase] Retrieved chat: ${decryptedChat.chat_id}, messages_v: ${decryptedChat.messages_v}, title_v: ${decryptedChat.title_v}, draft_v: ${decryptedChat.draft_v}, hasEncryptedDraftMd: ${!!decryptedChat.encrypted_draft_md}`);
                    cursor.continue();
                } else {
                    console.debug(`[ChatDatabase] Retrieved ${chats.length} chats from database`);
                    console.debug(`[ChatDatabase] Chat details:`, chats.map(c => ({
                        chatId: c.chat_id,
                        draftVersion: c.draft_v,
                        hasEncryptedDraftMd: !!c.encrypted_draft_md,
                        hasEncryptedDraftPreview: !!c.encrypted_draft_preview,
                        lastEdited: c.last_edited_overall_timestamp
                    })));
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
        
        // Check for existing message to prevent duplicates and manage status properly
        const existingMessage = await this.getMessage(message.message_id, transaction);
        if (existingMessage) {
            // Only update if the new message has higher priority status
            if (this.shouldUpdateMessage(existingMessage, message)) {
                console.debug("[ChatDatabase] Updating existing message with higher priority status:", message.message_id, `${existingMessage.status} -> ${message.status}`);
            } else {
                console.debug("[ChatDatabase] Message already exists with equal or higher priority status, skipping:", message.message_id, existingMessage.status);
                return Promise.resolve();
            }
        } else {
            // Check for content-based duplicates (different message_id but same content)
            const contentDuplicate = await this.findContentDuplicate(message, transaction);
            if (contentDuplicate) {
                console.debug("[ChatDatabase] Found content duplicate with different message_id:", contentDuplicate.message_id, "->", message.message_id);
                // Update the existing message with higher priority status if applicable
                if (this.shouldUpdateMessage(contentDuplicate, message)) {
                    console.debug("[ChatDatabase] Updating content duplicate with higher priority status:", contentDuplicate.message_id, `${contentDuplicate.status} -> ${message.status}`);
                    // Delete the old message and save the new one
                    await this.deleteMessage(contentDuplicate.message_id, transaction);
                } else {
                    console.debug("[ChatDatabase] Content duplicate has equal or higher priority status, skipping:", message.message_id);
                    return Promise.resolve();
                }
            }
        }
        
        // Encrypt message content before storing in IndexedDB (zero-knowledge architecture)
        const encryptedMessage = this.encryptMessageFields(message, message.chat_id);
        
        return new Promise(async (resolve, reject) => {
            const usesExternalTransaction = !!transaction;
            const currentTransaction = transaction || await this.getTransaction(this.MESSAGES_STORE_NAME, 'readwrite');
            const store = currentTransaction.objectStore(this.MESSAGES_STORE_NAME);
            const request = store.put(encryptedMessage); // Store encrypted message

            request.onsuccess = () => {
                console.debug("[ChatDatabase] Encrypted message saved/updated successfully (queued):", message.message_id);
                if (usesExternalTransaction) {
                    resolve();
                }
            };
            request.onerror = () => {
                console.error("[ChatDatabase] Error in message store.put operation:", request.error);
                reject(request.error);
            };

            if (!usesExternalTransaction) {
                currentTransaction.oncomplete = () => {
                    console.debug("[ChatDatabase] Transaction for saveMessage completed successfully for message:", message.message_id);
                    resolve();
                };
                currentTransaction.onerror = () => {
                    console.error("[ChatDatabase] Transaction for saveMessage failed for message:", message.message_id, "Error:", currentTransaction.error);
                    reject(currentTransaction.error);
                };
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

            request.onsuccess = () => {
                const encryptedMessages = request.result || [];
                // Decrypt all messages before returning (zero-knowledge architecture)
                const decryptedMessages = encryptedMessages.map(msg => this.decryptMessageFields(msg, chat_id));
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
                const decryptedMessage = this.decryptMessageFields(encryptedMessage, encryptedMessage.chat_id);
                resolve(decryptedMessage);
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
            const allMessages = await this.getAllMessages();
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
     * Get all messages from the database (for cleanup purposes)
     * NOTE: This is called during init() cleanup, so don't call init() here
     */
    private async getAllMessages(): Promise<Message[]> {
        return new Promise(async (resolve, reject) => {
            const transaction = this.getTransactionDuringInit(this.MESSAGES_STORE_NAME, 'readonly');
            const store = transaction.objectStore(this.MESSAGES_STORE_NAME);
            const request = store.getAll();

            request.onsuccess = () => {
                const encryptedMessages = request.result || [];
                // Decrypt all messages before returning (zero-knowledge architecture)
                const decryptedMessages = encryptedMessages.map(msg => this.decryptMessageFields(msg, msg.chat_id));
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
                
                request.onsuccess = (event) => {
                    const cursor = (event.target as IDBRequest<IDBCursorWithValue>).result;
                    if (cursor) {
                        const chat = cursor.value;
                        if (chat.encrypted_chat_key && !this.chatKeys.has(chat.chat_id)) {
                            try {
                                const chatKey = decryptChatKeyWithMasterKey(chat.encrypted_chat_key);
                                if (chatKey) {
                                    this.chatKeys.set(chat.chat_id, chatKey);
                                }
                            } catch (decryptError) {
                                console.error(`[ChatDatabase] Error decrypting chat key for ${chat.chat_id}:`, decryptError);
                            }
                        }
                        cursor.continue();
                    } else {
                        resolve();
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
     */
    public encryptMessageFields(message: Message, chatId: string): Message {
        const encryptedMessage = { ...message };
        const chatKey = this.getOrGenerateChatKey(chatId);

        // Encrypt content if present - ZERO-KNOWLEDGE: Remove plaintext content
        if (message.content) {
            // Content is now a markdown string (never Tiptap JSON on server!)
            const contentString = typeof message.content === 'string' ? message.content : JSON.stringify(message.content);
            encryptedMessage.encrypted_content = encryptWithChatKey(contentString, chatKey);
            // CRITICAL: Remove plaintext content for zero-knowledge architecture
            delete encryptedMessage.content;
        }

        // Encrypt sender_name if present - ZERO-KNOWLEDGE: Remove plaintext sender_name
        if (message.sender_name) {
            encryptedMessage.encrypted_sender_name = encryptWithChatKey(message.sender_name, chatKey);
            // CRITICAL: Remove plaintext sender_name for zero-knowledge architecture
            delete encryptedMessage.sender_name;
        }

        // Encrypt category if present - ZERO-KNOWLEDGE: Remove plaintext category
        if (message.category) {
            encryptedMessage.encrypted_category = encryptWithChatKey(message.category, chatKey);
            // CRITICAL: Remove plaintext category for zero-knowledge architecture
            delete encryptedMessage.category;
        }

        return encryptedMessage;
    }

    /**
     * Get encrypted fields only (for dual-content approach - preserves original message)
     */
    public getEncryptedFields(message: Message, chatId: string): { encrypted_content?: string, encrypted_sender_name?: string, encrypted_category?: string } {
        const chatKey = this.getOrGenerateChatKey(chatId);
        const encryptedFields: { encrypted_content?: string, encrypted_sender_name?: string, encrypted_category?: string } = {};

        // Encrypt content if present
        if (message.content) {
            const contentString = typeof message.content === 'string' ? message.content : JSON.stringify(message.content);
            encryptedFields.encrypted_content = encryptWithChatKey(contentString, chatKey);
        }

        // Encrypt sender_name if present
        if (message.sender_name) {
            encryptedFields.encrypted_sender_name = encryptWithChatKey(message.sender_name, chatKey);
        }

        // Encrypt category if present
        if (message.category) {
            encryptedFields.encrypted_category = encryptWithChatKey(message.category, chatKey);
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
            return chat?.encrypted_chat_key || null;
        } catch (error) {
            console.error(`[ChatDatabase] Error getting encrypted chat key for ${chatId}:`, error);
            return null;
        }
    }

    /**
     * Decrypt message fields with chat-specific key
     */
    public decryptMessageFields(message: Message, chatId: string): Message {
        const decryptedMessage = { ...message };
        const chatKey = this.getChatKey(chatId);

        if (!chatKey) {
            console.warn(`[ChatDatabase] No chat key found for chat ${chatId}, cannot decrypt message fields`);
            return decryptedMessage;
        }

        // Decrypt content if present
        if (message.encrypted_content) {
            const decryptedContentString = decryptWithChatKey(message.encrypted_content, chatKey);
            if (decryptedContentString) {
                // Content is now a markdown string (never Tiptap JSON on server!)
                decryptedMessage.content = decryptedContentString;
                // Clear encrypted field
                delete decryptedMessage.encrypted_content;
            }
        }

        // Decrypt sender_name if present
        if (message.encrypted_sender_name) {
            const decryptedSenderName = decryptWithChatKey(message.encrypted_sender_name, chatKey);
            if (decryptedSenderName) {
                decryptedMessage.sender_name = decryptedSenderName;
                // Clear encrypted field
                delete decryptedMessage.encrypted_sender_name;
            }
        }

        // Decrypt category if present
        if (message.encrypted_category) {
            const decryptedCategory = decryptWithChatKey(message.encrypted_category, chatKey);
            if (decryptedCategory) {
                decryptedMessage.category = decryptedCategory;
                // Clear encrypted field
                delete decryptedMessage.encrypted_category;
            }
        }

        return decryptedMessage;
    }
}

export const chatDB = new ChatDatabase();
