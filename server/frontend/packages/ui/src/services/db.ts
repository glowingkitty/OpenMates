import type { Chat } from '../types/chat';
import exampleChats from '../data/example-chats.json';

class ChatDatabase {
    private db: IDBDatabase | null = null;
    private readonly DB_NAME = 'chats_db';
    private readonly STORE_NAME = 'chats';
    private readonly VERSION = 1;

    /**
     * Initialize the database
     */
    async init(): Promise<void> {
        console.log("[ChatDatabase] Initializing database");
        return new Promise((resolve, reject) => {
            const request = indexedDB.open(this.DB_NAME, this.VERSION);

            request.onerror = () => {
                console.error("[ChatDatabase] Error opening database:", request.error);
                reject(request.error);
            };

            request.onsuccess = () => {
                console.log("[ChatDatabase] Database opened successfully");
                this.db = request.result;
                resolve();
            };

            request.onupgradeneeded = (event) => {
                console.log("[ChatDatabase] Database upgrade needed");
                const db = (event.target as IDBOpenDBRequest).result;
                
                if (!db.objectStoreNames.contains(this.STORE_NAME)) {
                    const store = db.createObjectStore(this.STORE_NAME, { keyPath: 'id' });
                    store.createIndex('lastUpdated', 'lastUpdated', { unique: false });
                }
            };
        });
    }

    /**
     * Load example chats into the database
     */
    async loadExampleChats(): Promise<void> {
        console.log("[ChatDatabase] Loading example chats");
        const store = this.getStore('readwrite');
        
        const chats = exampleChats.chats.map((chat: any) => {
            let title = chat.title || 'Untitled';
            let draftContent = undefined;

            if (chat.isDraft && chat.draftContent) {
                // Ensure draftContent is properly parsed/stored as an object
                draftContent = typeof chat.draftContent === 'string' ? 
                    JSON.parse(chat.draftContent) : 
                    chat.draftContent;
                    
                title = this.extractTitleFromContent(draftContent) || title;
            }

            return {
                ...chat,
                title,
                draftContent,
                lastUpdated: new Date(chat.lastUpdated),
                messages: chat.messages?.map(msg => ({
                    ...msg,
                    messageParts: [{ type: 'text', content: msg.content }],
                    timestamp: new Date(msg.timestamp)
                })) || []
            };
        });

        for (const chat of chats) {
            await this.addChat(chat);
        }
    }

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
            const request = store.put(chat);

            request.onsuccess = () => {
                console.log("[ChatDatabase] Chat added successfully:", chat.id);
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
            const request = store.index('lastUpdated').openCursor(null, 'prev');
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
}

export const chatDB = new ChatDatabase();
