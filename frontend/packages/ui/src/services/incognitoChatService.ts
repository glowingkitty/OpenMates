/**
 * Incognito Chat Service
 *
 * Manages storage and retrieval of incognito chats.
 * Incognito chats are stored in sessionStorage (not IndexedDB) and are
 * automatically cleared when the tab closes.
 */

import type { Chat, Message } from "../types/chat";
import { decideShareState, directShareState, shareStateClient } from "./shareState/decide";
import { incognitoMetadata } from "./shareState/incognitoChatPolicy";

class IncognitoChatService {
  private chats: Map<string, Chat> = new Map(); // In-memory cache
  private messages: Map<string, Message[]> = new Map(); // In-memory message cache
  private readonly STORAGE_KEY = "incognito_chats";
  private readonly MESSAGES_STORAGE_KEY = "incognito_chat_messages";
  private initialized = false;
  /** Bumped by every persist and by deleteAllChats so a slower Worker answer never overwrites newer state. */
  private persistGeneration = 0;
  /** Flag on only: the in-flight init shared by concurrent callers. */
  private loading: Promise<void> | null = null;

  /**
   * Initialize the service by loading chats from sessionStorage
   * Should be called on app startup
   */
  async init(): Promise<void> {
    if (this.initialized || typeof window === "undefined") {
      return;
    }
    // Flag on: concurrent callers share one load (the Worker answer is awaited).
    // Flag off: the load below has no await, so it stays atomic exactly as before.
    if (!shareStateClient()) return this.load();
    this.loading ??= this.load().finally(() => {
      this.loading = null;
    });
    return this.loading;
  }

  private async load(): Promise<void> {
    try {
      // Load chat metadata from sessionStorage
      const stored = sessionStorage.getItem(this.STORAGE_KEY);
      if (stored) {
        // Ensure group_key is always set to 'incognito' even for chats stored before this field was added
        const normalizeInput = { chats: JSON.parse(stored) as Record<string, unknown>[] };
        const chatsArray = (shareStateClient()
          ? await decideShareState("incognitoNormalize", normalizeInput)
          : directShareState("incognitoNormalize", normalizeInput)) as unknown as Chat[];
        chatsArray.forEach((chat: Chat) => {
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

  /** Update one volatile row by stable ID without appending a duplicate message. */
  async updateMessage(
    chatId: string,
    messageId: string,
    update: (current: Readonly<Message>) => Message | null,
  ): Promise<boolean> {
    await this.init();
    if (!this.chats.has(chatId)) return false;
    const messages = this.messages.get(chatId);
    const index = messages?.findIndex((message) => message.message_id === messageId) ?? -1;
    if (!messages || index < 0) return false;
    const next = update(messages[index]);
    const acceptInput = {
      message_id: messageId,
      chat_id: chatId,
      next: next ? { message_id: next.message_id, chat_id: next.chat_id } : null,
    };
    // Flag off: no await, so the row is replaced in the same tick as it was read (as before).
    const accepted = shareStateClient()
      ? await decideShareState("incognitoUpdateAccepted", acceptInput)
      : directShareState("incognitoUpdateAccepted", acceptInput);
    if (!accepted || !next) return false;
    // After the Worker answer another update may have moved or removed the row: find it again.
    const target = this.messages.get(chatId);
    const targetIndex = target?.findIndex((message) => message.message_id === messageId) ?? -1;
    if (!target || targetIndex < 0) return false;
    target[targetIndex] = next;
    this.persistMessagesToSessionStorage();
    return true;
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
   * Delete all incognito chats (called when incognito mode is disabled).
   *
   * Order matters: clear in-memory maps FIRST, then clear sessionStorage.
   * This prevents any concurrent persistToSessionStorage call (triggered by a
   * racing WebSocket event) from re-persisting the now-deleted chats — because
   * persistToSessionStorage reads from this.chats, which is already empty.
   *
   * NOTE: The caller (incognitoModeStore.setMethod) is responsible for dispatching
   * 'incognitoChatsDeleted' after this completes. Do NOT dispatch it here to avoid
   * double-firing the event.
   */
  async deleteAllChats(): Promise<void> {
    this.persistGeneration += 1;
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

    const chats = Array.from(this.chats.values()) as unknown as Record<string, unknown>[];
    if (shareStateClient()) {
      void this.persistThroughWorker(chats);
      return;
    }
    this.writeChatMetadata(incognitoMetadata({ chats }));
  }

  /** Rust core (flag on) projects the metadata in the Worker; a stale answer is dropped. */
  private async persistThroughWorker(chats: Record<string, unknown>[]): Promise<void> {
    this.persistGeneration += 1;
    const generation = this.persistGeneration;
    let metadata: Record<string, unknown>[];
    try {
      metadata = await decideShareState("incognitoMetadata", { chats });
    } catch (error) {
      console.error("[IncognitoChatService] Error persisting chats to sessionStorage:", error);
      return;
    }
    if (generation !== this.persistGeneration) return;
    this.writeChatMetadata(metadata);
  }

  private writeChatMetadata(metadata: Record<string, unknown>[]): void {
    try {
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
