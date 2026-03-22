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

import type { Chat, Message } from "../types/chat";

// ============================================================================
// TYPES
// ============================================================================

/**
 * Interface for demo embed data
 * Embeds are stored separately from messages for efficient retrieval
 */
export interface DemoEmbed {
  embed_id: string; // Unique embed identifier
  chat_id: string; // Associated demo chat ID
  type: string; // Embed type (e.g., 'web-website', 'app-skill-use')
  content: string; // Cleartext content (JSON string - already decrypted server-side)
  created_at: number; // Original creation timestamp
}

interface DemoChatRecord {
  chat_id: string;
  chat: Chat;
  messages: Message[];
  created_at: number; // When this was cached
  demo_id: string; // Original server demo_id
  content_hash: string; // SHA256 hash of content for change detection
}

// ============================================================================
// DEMO CHATS DATABASE CLASS
// ============================================================================

class DemoChatsDB {
  private db: IDBDatabase | null = null;
  private initializationPromise: Promise<void> | null = null;
  private readonly DB_NAME = "demo_chats_db";
  private readonly VERSION = 3; // v3: clear old numeric demo_id entries (demo-1, demo-2) after slug migration

  // Store names
  private readonly CHATS_STORE_NAME = "demo_chats";
  private readonly MESSAGES_STORE_NAME = "demo_messages";
  private readonly EMBEDS_STORE_NAME = "demo_embeds"; // New store for embeds

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
        const tx = (event.target as IDBOpenDBRequest).transaction!;
        const oldVersion = event.oldVersion;

        // Create object stores if they don't exist (initial creation)
        if (!db.objectStoreNames.contains(this.CHATS_STORE_NAME)) {
          const chatsStore = db.createObjectStore(this.CHATS_STORE_NAME, {
            keyPath: "chat_id",
          });
          chatsStore.createIndex("demo_id", "demo_id", { unique: true });
          chatsStore.createIndex("created_at", "created_at");
        }

        if (!db.objectStoreNames.contains(this.MESSAGES_STORE_NAME)) {
          const messagesStore = db.createObjectStore(this.MESSAGES_STORE_NAME, {
            keyPath: "message_id",
          });
          messagesStore.createIndex("chat_id", "chat_id");
        }

        // Version 2: Add demo_embeds store for offline embed support
        if (!db.objectStoreNames.contains(this.EMBEDS_STORE_NAME)) {
          const embedsStore = db.createObjectStore(this.EMBEDS_STORE_NAME, {
            keyPath: "embed_id",
          });
          embedsStore.createIndex("chat_id", "chat_id");
          console.debug(
            "[DemoChatsDB] Created demo_embeds store for offline embed support",
          );
        }

        // Version 3: Clear all cached demo chats that used old numeric-suffix IDs
        // (demo-1, demo-2, demo-3, ...). The server migrated to word-based slugs
        // (demo-capital-of-spain, etc.) — old entries would show as duplicates
        // alongside the new slug-based entries. Clear everything so the server
        // provides fresh slug-based entries on next load.
        if (
          oldVersion < 3 &&
          db.objectStoreNames.contains(this.CHATS_STORE_NAME)
        ) {
          console.debug(
            "[DemoChatsDB] v3 migration: clearing old numeric demo_id entries",
          );
          const chatsStore = tx.objectStore(this.CHATS_STORE_NAME);
          const chatsReq = chatsStore.openCursor();
          chatsReq.onsuccess = (e) => {
            const cursor = (e.target as IDBRequest<IDBCursorWithValue>).result;
            if (!cursor) return;
            const record = cursor.value as DemoChatRecord;
            // Old format: demo-1, demo-2, demo-e0090311 (UUID fragment), etc.
            // New format: demo-capital-of-spain (multi-word slug)
            // Detect old format: demo_id has only one word after the dash,
            // or is a short hex string (UUID fragment from first migration pass)
            const demoId: string = record.demo_id || "";
            const suffix = demoId.startsWith("demo-") ? demoId.slice(5) : "";
            const isOldFormat =
              /^\d+$/.test(suffix) || /^[0-9a-f]{8}$/.test(suffix);
            if (isOldFormat) {
              console.debug(
                `[DemoChatsDB] v3 migration: removing old entry ${demoId}`,
              );
              cursor.delete();
              // Also clean up associated messages and embeds
              const chatId: string = record.chat_id;
              if (db.objectStoreNames.contains(this.MESSAGES_STORE_NAME)) {
                const msgStore = tx.objectStore(this.MESSAGES_STORE_NAME);
                const msgIdx = msgStore.index("chat_id");
                msgIdx.openCursor(IDBKeyRange.only(chatId)).onsuccess = (
                  me,
                ) => {
                  const msgCursor = (
                    me.target as IDBRequest<IDBCursorWithValue>
                  ).result;
                  if (msgCursor) {
                    msgCursor.delete();
                    msgCursor.continue();
                  }
                };
              }
              if (db.objectStoreNames.contains(this.EMBEDS_STORE_NAME)) {
                const embStore = tx.objectStore(this.EMBEDS_STORE_NAME);
                const embIdx = embStore.index("chat_id");
                embIdx.openCursor(IDBKeyRange.only(chatId)).onsuccess = (
                  ee,
                ) => {
                  const embCursor = (
                    ee.target as IDBRequest<IDBCursorWithValue>
                  ).result;
                  if (embCursor) {
                    embCursor.delete();
                    embCursor.continue();
                  }
                };
              }
            }
            cursor.continue();
          };
        }
      };

      request.onsuccess = () => {
        this.db = request.result;
        console.debug("[DemoChatsDB] Database opened successfully");
        resolve();
      };

      request.onerror = () => {
        console.error("[DemoChatsDB] Failed to open database:", request.error);
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
      console.debug("[DemoChatsDB] Database closed");
    }
  }

  // ============================================================================
  // TRANSACTION HELPERS
  // ============================================================================

  /**
   * Get a transaction for the specified stores
   */
  private async getTransaction(
    storeNames: string | string[],
    mode: IDBTransactionMode = "readonly",
  ): Promise<IDBTransaction> {
    if (!this.db) {
      await this.init();
    }
    if (!this.db) {
      throw new Error("DemoChatsDB not initialized");
    }
    return this.db.transaction(storeNames, mode);
  }

  // ============================================================================
  // CHAT CRUD OPERATIONS
  // ============================================================================

  /**
   * Store a demo chat, its messages, and embeds
   * @param demoId - The server demo ID (e.g., "demo-1")
   * @param chat - The Chat object
   * @param messages - Array of Message objects
   * @param contentHash - SHA256 hash of content for change detection
   * @param embeds - Optional array of DemoEmbed objects
   */
  async storeDemoChat(
    demoId: string,
    chat: Chat,
    messages: Message[],
    contentHash: string = "",
    embeds: DemoEmbed[] = [],
  ): Promise<void> {
    await this.init();

    const transaction = await this.getTransaction(
      [this.CHATS_STORE_NAME, this.MESSAGES_STORE_NAME, this.EMBEDS_STORE_NAME],
      "readwrite",
    );

    try {
      // Store chat record
      const chatRecord: DemoChatRecord = {
        chat_id: chat.chat_id,
        chat,
        messages: [], // We store messages separately
        created_at: Date.now(),
        demo_id: demoId,
        content_hash: contentHash,
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

      // Store embeds (if any)
      if (embeds.length > 0) {
        const embedStore = transaction.objectStore(this.EMBEDS_STORE_NAME);
        for (const embed of embeds) {
          await new Promise<void>((resolve, reject) => {
            const request = embedStore.put(embed);
            request.onsuccess = () => resolve();
            request.onerror = () => reject(request.error);
          });
        }
      }

      console.debug(
        `[DemoChatsDB] Stored demo chat ${demoId} (${chat.chat_id}) with ${messages.length} messages, ${embeds.length} embeds, hash: ${contentHash.slice(0, 16)}...`,
      );
    } catch (error) {
      console.error("[DemoChatsDB] Error storing demo chat:", error);
      throw error;
    }
  }

  /**
   * Get all content hashes for cached demo chats
   * Used for change detection when fetching demo list from server
   * @returns Map of demo_id to content_hash
   */
  async getAllContentHashes(): Promise<Map<string, string>> {
    await this.init();

    const transaction = await this.getTransaction(
      this.CHATS_STORE_NAME,
      "readonly",
    );
    const store = transaction.objectStore(this.CHATS_STORE_NAME);

    return new Promise<Map<string, string>>((resolve, reject) => {
      const request = store.getAll();
      request.onsuccess = () => {
        const records = request.result as DemoChatRecord[];
        const hashes = new Map<string, string>();
        for (const record of records) {
          if (record.content_hash) {
            hashes.set(record.demo_id, record.content_hash);
          }
        }
        console.debug(`[DemoChatsDB] Retrieved ${hashes.size} content hashes`);
        resolve(hashes);
      };
      request.onerror = () => reject(request.error);
    });
  }

  /**
   * Get the content hash for a specific demo chat
   * @param demoId - The demo ID to look up
   * @returns The content hash or null if not found
   */
  async getContentHash(demoId: string): Promise<string | null> {
    await this.init();

    const transaction = await this.getTransaction(
      this.CHATS_STORE_NAME,
      "readonly",
    );
    const store = transaction.objectStore(this.CHATS_STORE_NAME);
    const index = store.index("demo_id");

    return new Promise<string | null>((resolve, reject) => {
      const request = index.get(demoId);
      request.onsuccess = () => {
        const record = request.result as DemoChatRecord | undefined;
        resolve(record?.content_hash || null);
      };
      request.onerror = () => reject(request.error);
    });
  }

  /**
   * Get a demo chat by chat_id
   */
  async getDemoChat(chatId: string): Promise<Chat | null> {
    await this.init();

    const transaction = await this.getTransaction(
      this.CHATS_STORE_NAME,
      "readonly",
    );
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

    const transaction = await this.getTransaction(
      this.MESSAGES_STORE_NAME,
      "readonly",
    );
    const store = transaction.objectStore(this.MESSAGES_STORE_NAME);
    const index = store.index("chat_id");

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
   * Get embeds for a demo chat
   * Returns cleartext embed data for offline demo chat viewing
   */
  async getDemoEmbeds(chatId: string): Promise<DemoEmbed[]> {
    await this.init();

    const transaction = await this.getTransaction(
      this.EMBEDS_STORE_NAME,
      "readonly",
    );
    const store = transaction.objectStore(this.EMBEDS_STORE_NAME);
    const index = store.index("chat_id");

    return new Promise<DemoEmbed[]>((resolve, reject) => {
      const request = index.getAll(chatId);
      request.onsuccess = () => {
        const embeds = request.result as DemoEmbed[];
        console.debug(
          `[DemoChatsDB] Retrieved ${embeds.length} embeds for chat ${chatId}`,
        );
        resolve(embeds);
      };
      request.onerror = () => reject(request.error);
    });
  }

  /**
   * Get a specific embed by ID
   */
  async getDemoEmbed(embedId: string): Promise<DemoEmbed | null> {
    await this.init();

    const transaction = await this.getTransaction(
      this.EMBEDS_STORE_NAME,
      "readonly",
    );
    const store = transaction.objectStore(this.EMBEDS_STORE_NAME);

    return new Promise<DemoEmbed | null>((resolve, reject) => {
      const request = store.get(embedId);
      request.onsuccess = () => {
        const embed = request.result as DemoEmbed | undefined;
        resolve(embed || null);
      };
      request.onerror = () => reject(request.error);
    });
  }

  /**
   * Get all cached demo chats
   */
  async getAllDemoChats(): Promise<Chat[]> {
    await this.init();

    const transaction = await this.getTransaction(
      this.CHATS_STORE_NAME,
      "readonly",
    );
    const store = transaction.objectStore(this.CHATS_STORE_NAME);

    return new Promise<Chat[]>((resolve, reject) => {
      const request = store.getAll();
      request.onsuccess = () => {
        const records = request.result as DemoChatRecord[];
        const chats = records.map((record) => record.chat);
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

    const transaction = await this.getTransaction(
      this.CHATS_STORE_NAME,
      "readonly",
    );
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
   * Delete a demo chat, its messages, and embeds
   */
  async deleteDemoChat(chatId: string): Promise<void> {
    await this.init();

    const transaction = await this.getTransaction(
      [this.CHATS_STORE_NAME, this.MESSAGES_STORE_NAME, this.EMBEDS_STORE_NAME],
      "readwrite",
    );

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
      const messageIndex = messageStore.index("chat_id");
      const messagesToDelete = await new Promise<string[]>(
        (resolve, reject) => {
          const request = messageIndex.getAllKeys(chatId);
          request.onsuccess = () => resolve(request.result as string[]);
          request.onerror = () => reject(request.error);
        },
      );

      for (const messageId of messagesToDelete) {
        await new Promise<void>((resolve, reject) => {
          const request = messageStore.delete(messageId);
          request.onsuccess = () => resolve();
          request.onerror = () => reject(request.error);
        });
      }

      // Delete embeds
      const embedStore = transaction.objectStore(this.EMBEDS_STORE_NAME);
      const embedIndex = embedStore.index("chat_id");
      const embedsToDelete = await new Promise<string[]>((resolve, reject) => {
        const request = embedIndex.getAllKeys(chatId);
        request.onsuccess = () => resolve(request.result as string[]);
        request.onerror = () => reject(request.error);
      });

      for (const embedId of embedsToDelete) {
        await new Promise<void>((resolve, reject) => {
          const request = embedStore.delete(embedId);
          request.onsuccess = () => resolve();
          request.onerror = () => reject(request.error);
        });
      }

      console.debug(
        `[DemoChatsDB] Deleted demo chat ${chatId}, ${messagesToDelete.length} messages, and ${embedsToDelete.length} embeds`,
      );
    } catch (error) {
      console.error("[DemoChatsDB] Error deleting demo chat:", error);
      throw error;
    }
  }

  /**
   * Clear all demo chats, messages, and embeds (useful for testing or cache invalidation)
   */
  async clearAllDemoChats(): Promise<void> {
    await this.init();

    const transaction = await this.getTransaction(
      [this.CHATS_STORE_NAME, this.MESSAGES_STORE_NAME, this.EMBEDS_STORE_NAME],
      "readwrite",
    );

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

      // Clear embeds
      const embedStore = transaction.objectStore(this.EMBEDS_STORE_NAME);
      await new Promise<void>((resolve, reject) => {
        const request = embedStore.clear();
        request.onsuccess = () => resolve();
        request.onerror = () => reject(request.error);
      });

      console.debug(
        "[DemoChatsDB] Cleared all demo chats, messages, and embeds from cache",
      );
    } catch (error) {
      console.error("[DemoChatsDB] Error clearing demo chats:", error);
      throw error;
    }
  }

  /**
   * Get cache statistics
   */
  async getCacheStats(): Promise<{
    chatCount: number;
    messageCount: number;
    embedCount: number;
  }> {
    await this.init();

    const transaction = await this.getTransaction(
      [this.CHATS_STORE_NAME, this.MESSAGES_STORE_NAME, this.EMBEDS_STORE_NAME],
      "readonly",
    );

    const chatStore = transaction.objectStore(this.CHATS_STORE_NAME);
    const messageStore = transaction.objectStore(this.MESSAGES_STORE_NAME);
    const embedStore = transaction.objectStore(this.EMBEDS_STORE_NAME);

    const [chatCount, messageCount, embedCount] = await Promise.all([
      new Promise<number>((resolve, reject) => {
        const request = chatStore.count();
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      }),
      new Promise<number>((resolve, reject) => {
        const request = messageStore.count();
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      }),
      new Promise<number>((resolve, reject) => {
        const request = embedStore.count();
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      }),
    ]);

    return { chatCount, messageCount, embedCount };
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
