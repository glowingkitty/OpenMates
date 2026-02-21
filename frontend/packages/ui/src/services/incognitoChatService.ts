/**
 * Incognito Chat Service
 *
 * Manages storage and retrieval of incognito chats.
 * Incognito chats are stored in sessionStorage (not IndexedDB) and are
 * automatically cleared when the tab closes.
 */

import type { Chat, Message } from "../types/chat";

class IncognitoChatService {
  private chats: Map<string, Chat> = new Map(); // In-memory cache
  private messages: Map<string, Message[]> = new Map(); // In-memory message cache
  private readonly STORAGE_KEY = "incognito_chats";
  private readonly MESSAGES_STORAGE_KEY = "incognito_chat_messages";
  private initialized = false;

  /**
   * Initialize the service by loading chats from sessionStorage
   * Should be called on app startup
   */
  async init(): Promise<void> {
    if (this.initialized || typeof window === "undefined") {
      return;
    }

    try {
      // Load chat metadata from sessionStorage
      const stored = sessionStorage.getItem(this.STORAGE_KEY);
      if (stored) {
        const chatsArray = JSON.parse(stored) as Chat[];
        chatsArray.forEach((chat: Chat) => {
          // Ensure group_key is always set to 'incognito' even for chats stored before this field was added
          chat.is_incognito = true;
          chat.group_key = "incognito";
          this.chats.set(chat.chat_id, chat);
        });
        console.debug(
          `[IncognitoChatService] Loaded ${chatsArray.length} incognito chats from sessionStorage`,
        );
      }

      // Load messages from sessionStorage
      const storedMessages = sessionStorage.getItem(this.MESSAGES_STORAGE_KEY);
      if (storedMessages) {
        const messagesMap = JSON.parse(storedMessages) as Record<
          string,
          Message[]
        >;
        Object.entries(messagesMap).forEach(([chatId, messages]) => {
          this.messages.set(chatId, messages);
        });
        console.debug(
          `[IncognitoChatService] Loaded messages for ${Object.keys(messagesMap).length} incognito chats`,
        );
      }

      this.initialized = true;
    } catch (error) {
      console.error("[IncognitoChatService] Error initializing:", error);
      // Clear corrupted data
      this.clearStorage();
    }
  }

  /**
   * Store a chat in memory and sessionStorage
   * Only stores metadata, not full message content (messages stored separately)
   */
  async storeChat(chat: Chat): Promise<void> {
    if (typeof window === "undefined") {
      return;
    }

    // Ensure chat is marked as incognito and grouped under the dedicated incognito sidebar section.
    // group_key='incognito' causes chatGroupUtils.groupChats() to bucket it there instead of into
    // time-based groups (today/yesterday/…). The sidebar then renders it under its own header.
    chat.is_incognito = true;
    chat.group_key = "incognito";

    // Store in memory
    this.chats.set(chat.chat_id, chat);

    // Persist metadata to sessionStorage
    this.persistToSessionStorage();
  }

  /**
   * Store messages for a chat
   */
  async storeMessages(chatId: string, messages: Message[]): Promise<void> {
    if (typeof window === "undefined") {
      return;
    }

    // Store in memory
    this.messages.set(chatId, messages);

    // Persist to sessionStorage
    this.persistMessagesToSessionStorage();
  }

  /**
   * Get all incognito chats
   */
  async getAllChats(): Promise<Chat[]> {
    await this.init();
    return Array.from(this.chats.values());
  }

  /**
   * Get a specific chat by ID
   */
  async getChat(chatId: string): Promise<Chat | null> {
    await this.init();
    return this.chats.get(chatId) || null;
  }

  /**
   * Get all messages for a chat
   */
  async getMessagesForChat(chatId: string): Promise<Message[]> {
    await this.init();
    return this.messages.get(chatId) || [];
  }

  /**
   * Add a message to a chat
   */
  async addMessage(chatId: string, message: Message): Promise<void> {
    await this.init();
    const messages = this.messages.get(chatId) || [];
    messages.push(message);
    this.messages.set(chatId, messages);
    this.persistMessagesToSessionStorage();
  }

  /**
   * Update a chat
   */
  async updateChat(chatId: string, updates: Partial<Chat>): Promise<void> {
    await this.init();
    const existingChat = this.chats.get(chatId);
    if (existingChat) {
      const updatedChat = { ...existingChat, ...updates };
      this.chats.set(chatId, updatedChat);
      this.persistToSessionStorage();
    }
  }

  /**
   * Delete a specific chat and its messages
   */
  async deleteChat(chatId: string): Promise<void> {
    await this.init();
    this.chats.delete(chatId);
    this.messages.delete(chatId);
    this.persistToSessionStorage();
    this.persistMessagesToSessionStorage();
  }

  /**
   * Delete all incognito chats (called when incognito mode is disabled)
   */
  async deleteAllChats(): Promise<void> {
    this.chats.clear();
    this.messages.clear();
    this.clearStorage();
    console.debug("[IncognitoChatService] Deleted all incognito chats");
  }

  /**
   * Persist chat metadata to sessionStorage and notify the sidebar.
   *
   * Dispatches 'incognitoChatsUpdated' so that Chats.svelte can reload its
   * incognito chat list without requiring a page refresh.
   */
  private persistToSessionStorage(): void {
    if (typeof window === "undefined") {
      return;
    }

    try {
      const chatsArray = Array.from(this.chats.values());
      // Only store essential metadata, not full message content
      const metadata = chatsArray.map((chat) => ({
        chat_id: chat.chat_id,
        is_incognito: true,
        group_key: "incognito",
        encrypted_title: chat.encrypted_title,
        title: chat.title,
        created_at: chat.created_at,
        updated_at: chat.updated_at,
        last_edited_overall_timestamp: chat.last_edited_overall_timestamp,
        unread_count: chat.unread_count,
        messages_v: chat.messages_v,
        title_v: chat.title_v,
        draft_v: chat.draft_v,
        encrypted_draft_md: chat.encrypted_draft_md,
        encrypted_draft_preview: chat.encrypted_draft_preview,
        waiting_for_metadata: chat.waiting_for_metadata,
        // Don't store encrypted fields that are generated server-side
        // as incognito chats don't go through post-processing
      }));

      sessionStorage.setItem(this.STORAGE_KEY, JSON.stringify(metadata));

      // Notify Chats.svelte that incognito chats changed so the sidebar
      // updates without needing a page refresh.
      window.dispatchEvent(new CustomEvent("incognitoChatsUpdated"));
    } catch (error) {
      console.error(
        "[IncognitoChatService] Error persisting chats to sessionStorage:",
        error,
      );
      // If storage quota exceeded, clear old data
      if (
        error instanceof DOMException &&
        error.name === "QuotaExceededError"
      ) {
        console.warn(
          "[IncognitoChatService] SessionStorage quota exceeded, clearing old data",
        );
        this.clearStorage();
      }
    }
  }

  /**
   * Persist messages to sessionStorage
   */
  private persistMessagesToSessionStorage(): void {
    if (typeof window === "undefined") {
      return;
    }

    try {
      const messagesMap: Record<string, Message[]> = {};
      this.messages.forEach((messages, chatId) => {
        messagesMap[chatId] = messages;
      });

      sessionStorage.setItem(
        this.MESSAGES_STORAGE_KEY,
        JSON.stringify(messagesMap),
      );
    } catch (error) {
      console.error(
        "[IncognitoChatService] Error persisting messages to sessionStorage:",
        error,
      );
      // If storage quota exceeded, clear old data
      if (
        error instanceof DOMException &&
        error.name === "QuotaExceededError"
      ) {
        console.warn(
          "[IncognitoChatService] SessionStorage quota exceeded, clearing old messages",
        );
        this.clearStorage();
      }
    }
  }

  /**
   * Clear all data from sessionStorage
   */
  private clearStorage(): void {
    if (typeof window === "undefined") {
      return;
    }

    try {
      sessionStorage.removeItem(this.STORAGE_KEY);
      sessionStorage.removeItem(this.MESSAGES_STORAGE_KEY);
    } catch (error) {
      console.error("[IncognitoChatService] Error clearing storage:", error);
    }
  }
}

// Export singleton instance
export const incognitoChatService = new IncognitoChatService();
