import type { Chat, Message, MessageStatus } from '../types/chat';
import exampleChats from '../data/web-app-example-chats.json';

class ChatDatabase {
    private db: IDBDatabase | null = null;
    private readonly DB_NAME = 'chats_db';
    private readonly STORE_NAME = 'chats';
    private readonly VERSION = 1;

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
                
                if (!db.objectStoreNames.contains(this.STORE_NAME)) {
                    const store = db.createObjectStore(this.STORE_NAME, { keyPath: 'id' });
                    // Index by lastMessageTimestamp for sorting as per requirements
                    store.createIndex('lastMessageTimestamp', 'lastMessageTimestamp', { unique: false });
                    // Also index updatedAt for potential future use or alternative sorting
                    store.createIndex('updatedAt', 'updatedAt', { unique: false });
                }
            };
        });
    }

    /**
     * Load example chats into the database
     */
    // loadExampleChats removed: No more example or placeholder chats. Only real data is synced.

    /**
     * Extract a title from Tiptap JSON content
     */
    private extractTitleFromContent(content: any): string {
        if (!content) return '';
        
        try {
            // Find first text content in the document
            const firstTextNode = content.content?.[0]?.content?.[0];
            if (firstTextNode?.type === 'text') {
                // Truncate to reasonable title length
                return firstTextNode.text.slice(0, 50) + (firstTextNode.text.length > 50 ? '...' : '');
            }
        } catch (error) {
            console.error("[ChatDatabase] Error extracting title from content:", error);
        }
        
        return '';
    }

    /**
     * Add a new chat to the database
     */
    async addChat(chat: Chat): Promise<void> {
        return new Promise((resolve, reject) => {
            const store = this.getStore('readwrite');
            // The put operation saves the entire chat object, including the _v field if present.
            const request = store.put(chat);

            request.onsuccess = () => {
                console.debug("[ChatDatabase] Chat added successfully:", chat.id, "Version:", chat.version); // Use version
                resolve();
            };

            request.onerror = () => {
                console.error("[ChatDatabase] Error adding chat:", request.error);
                reject(request.error);
            };
        });
    }

    /**
     * Get all chats from the database
     */
    async getAllChats(): Promise<Chat[]> {
        return new Promise((resolve, reject) => {
            const store = this.getStore('readonly');
            // Sort by lastMessageTimestamp (most recent first) as per requirements
            const request = store.index('lastMessageTimestamp').openCursor(null, 'prev');
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

    /**
     * Get a specific chat by ID
     */
    async getChat(id: string): Promise<Chat | null> {
        return new Promise((resolve, reject) => {
            const store = this.getStore('readonly');
            const request = store.get(id);

            request.onsuccess = () => {
                resolve(request.result || null);
            };

            request.onerror = () => {
                console.error("[ChatDatabase] Error getting chat:", request.error);
                reject(request.error);
            };
        });
    }

    private getStore(mode: IDBTransactionMode): IDBObjectStore {
        if (!this.db) {
            throw new Error('Database not initialized');
        }
        const transaction = this.db.transaction([this.STORE_NAME], mode);
        return transaction.objectStore(this.STORE_NAME);
    }

    /**
     * Updates or creates a chat draft
     * @param chatId Optional ID of existing chat to update
     * @param content Draft content to save
     * @returns The updated or created chat
     */
    async saveDraft(content: any, chatId?: string): Promise<Chat> {
        console.debug("[ChatDatabase] Saving draft", { chatId, content });

        let chat: Chat;

        if (chatId) {
            // Update existing chat
            const existingChat = await this.getChat(chatId);
            if (!existingChat) {
                throw new Error(`Chat not found for saving draft: ${chatId}`);
            }
            chat = existingChat; // Includes existing _v if present

            chat.draft = content; // Update draft content
            chat.updatedAt = new Date(); // Update timestamp
            // isDraft and status removed from type
            // Note: The existing chat.version is preserved here. When the WebSocket service
            // sends the 'draft_update', it should use this chat.version as 'basedOnVersion'.
            // If the update succeeds, the backend sends back the *new* version via handleDraftUpdated,
            // which then calls updateChat to save it back to the DB.

        } else {
            // Create new chat locally (will likely be synced/confirmed by backend later)
            // Create new chat locally according to the Chat interface
            const now = new Date();
            chat = {
                id: crypto.randomUUID(), // Temporary ID, backend will assign final one
                title: this.extractTitleFromContent(content) || 'New Chat',
                draft: content, // Set the draft content
                version: 1, // Start with version 1 for local drafts (backend confirms/updates)
                mates: [], // Initialize mates
                messages: [], // Initialize messages
                createdAt: now, // Set creation time
                updatedAt: now, // Set updated time
                lastMessageTimestamp: null, // No messages yet
                isPersisted: false, // New local drafts are not persisted
                // status removed from type
            };
        }

        await this.addChat(chat); // Saves the chat, including its current _v
        // The returned chat includes the latest known _v (if available).
        // Calling code (e.g., WebSocket logic) should use chat._v as basedOnVersion
        // when sending 'draft_update' messages for existing chats.
        return chat;
    }

    /**
     * Removes draft status from a chat
     * @param chatId ID of the chat to update
     */
    async clearDraft(chatId: string): Promise<void> {
        const chat = await this.getChat(chatId);
        if (chat) {
            chat.draft = null; // Clear the draft content
            chat.updatedAt = new Date(); // Update timestamp
            // isDraft and status removed from type
            await this.updateChat(chat); // Use updateChat instead of addChat
        }
    }

    async removeDraft(chatId: string): Promise<Chat> {
        const chat = await this.getChat(chatId);
        
        if (!chat) {
            throw new Error('Chat not found');
        }

        // Remove draft-related fields
        // Remove draft-related fields by setting draft to null
        const updatedChat: Chat = {
            ...chat,
            draft: null,
            updatedAt: new Date() // Update timestamp
        };

        await this.addChat(updatedChat);
        return updatedChat;
    }

    async deleteChat(chatId: string): Promise<void> {
        const store = this.getStore('readwrite');
        const request = store.delete(chatId);
        
        return new Promise((resolve, reject) => {
            request.onsuccess = () => resolve();
            request.onerror = () => reject(request.error);
        });
    }

    async addMessage(chatId: string, message: Message): Promise<Chat> {
        const chat = await this.getChat(chatId);
        if (!chat) throw new Error('Chat not found');

        chat.messages = [...chat.messages, message];
        await this.updateChat(chat);
        return chat;
    }

    /**
     * Update an existing chat in the database
     */
    async updateChat(chat: Chat): Promise<void> {
        return new Promise((resolve, reject) => {
            const store = this.getStore('readwrite');
             // The put operation saves the entire chat object, including the _v field if present.
            const request = store.put(chat);

            request.onsuccess = () => {
                console.debug("[ChatDatabase] Chat updated successfully:", chat.id, "Version:", chat.version); // Use version
                resolve();
            };

            request.onerror = () => {
                console.error("[ChatDatabase] Error updating chat:", request.error);
                reject(request.error);
            };
        });
    }
    /**
     * Update the status of a message in a chat
     * @param chatId ID of the chat containing the message
     * @param messageId ID of the message to update
     * @param status New status of the message
     */
    async updateMessageStatus(chatId: string, messageId: string, status: MessageStatus): Promise<Chat> {
        const chat = await this.getChat(chatId);
        if (!chat) throw new Error('Chat not found');

        chat.messages = chat.messages.map(msg => 
            msg.id === messageId ? { ...msg, status } : msg
        );

        await this.updateChat(chat);
        return chat;
    }

    /**
     * Updates an existing message in a chat
     * @param chatId The ID of the chat
     * @param message The updated message object
     * @returns The updated chat object
     */
    async updateMessage(chatId: string, message: Message): Promise<Chat> {
        const chat = await this.getChat(chatId);
        if (!chat) {
            throw new Error(`Chat with ID ${chatId} not found`);
        }

        const messages = chat.messages || [];
        const messageIndex = messages.findIndex(m => m.id === message.id);
        
        if (messageIndex === -1) {
            throw new Error(`Message with ID ${message.id} not found in chat ${chatId}`);
        }

        // Update the message
        messages[messageIndex] = message;

        // Update the chat with new messages
        const updatedChat = {
            ...chat,
            messages,
            updatedAt: new Date()  // Update timestamp
        };

        await this.updateChat(updatedChat);
        return updatedChat;
    }
}

export const chatDB = new ChatDatabase();
