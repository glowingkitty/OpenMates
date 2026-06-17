/**
 * Anonymous free chat storage facade.
 *
 * Anonymous chats use the normal IndexedDB chat/message stores and normal
 * per-chat encryption keys. While logged out, each chat key is wrapped with a
 * tab/session anonymous key; signup re-wraps the same chat key with the account
 * master key before normal sync uploads encrypted chat/message records.
 */

import { get } from "svelte/store";

import { getApiEndpoint } from "../config/api";
import { text } from "../i18n/translations";
import type { Chat, Message } from "../types/chat";
import { chatDB } from "./db";
import { chatKeyManager } from "./encryption/ChatKeyManager";
import { decryptWithChatKey, encryptWithChatKey } from "./cryptoService";
import {
  clearAnonymousSessionKey,
  ensureAnonymousSessionKey,
  hasAnonymousSessionKey,
  unwrapAnonymousChatKey,
  wrapAnonymousChatKey,
} from "./anonymousChatKeyWrapping";

const LEGACY_ANONYMOUS_PAYLOAD_STORAGE = "openmates_anonymous_chats_v1";
const ANONYMOUS_ID_STORAGE = "openmates_anonymous_id";
const ANONYMOUS_CHAT_PREFIX = "anonymous-";
const ANONYMOUS_FEATURE_NOTICE_KEY = "chat.anonymous_free_usage.feature_notice";
const DEFAULT_ANONYMOUS_CATEGORY = "ai";
const DEFAULT_ANONYMOUS_ICON = "sparkles";

interface AnonymousChatResponse {
  status?: string;
  chatId?: string;
  messageId?: string;
  assistant?: string;
  category?: string | null;
  modelName?: string | null;
  detail?: { code?: string; message?: string } | string;
}

export interface AnonymousSendResult {
  chat: Chat;
  userMessage: Message;
  assistantMessage: Message;
  isNewChat: boolean;
}

function createMessageId(chatId: string): string {
  return `${chatId.slice(-10)}-${crypto.randomUUID()}`;
}

function titleFromMarkdown(markdown: string): string {
  const firstLine = markdown
    .replace(/```json[\s\S]*?```/g, "")
    .split("\n")
    .map((line) => line.trim())
    .find(Boolean);
  if (!firstLine) return "Anonymous chat";
  return firstLine.length > 50 ? `${firstLine.slice(0, 50)}...` : firstLine;
}

function anonymousFeatureNoticeContent(): string {
  return get(text)(ANONYMOUS_FEATURE_NOTICE_KEY);
}

function createFeatureNoticeMessage(chatId: string, createdAt: number): Message {
  return {
    message_id: createMessageId(chatId),
    chat_id: chatId,
    role: "system",
    content: anonymousFeatureNoticeContent(),
    status: "synced",
    created_at: createdAt,
    sender_name: "system",
  };
}

function isConversationMessage(message: Message): boolean {
  return (
    message.status !== "failed" &&
    (message.role === "user" || message.role === "assistant") &&
    typeof message.content === "string" &&
    message.content.trim().length > 0
  );
}

function stripPlainChatFields(chat: Chat): Chat {
  const chatToStore = { ...chat };
  delete chatToStore.title;
  delete chatToStore.category;
  delete chatToStore.icon;
  return chatToStore;
}

class AnonymousChatStorage {
  private initialized = false;
  private dbReady = false;

  async init(): Promise<void> {
    if (this.initialized || typeof window === "undefined") return;
    this.clearLegacyPayload();
    this.initialized = true;
  }

  async getAllChats(): Promise<Chat[]> {
    await this.init();
    if (!hasAnonymousSessionKey()) {
      await this.purgeAnonymousChatsWithoutSession();
      return [];
    }

    await this.ensureDatabaseReady();
    const chats = await chatDB.getAllChats();
    const anonymousChats = chats.filter((chat) => chat.is_anonymous);
    return Promise.all(anonymousChats.map((chat) => this.hydrateAnonymousChat(chat)));
  }

  async getChat(chatId: string): Promise<Chat | null> {
    await this.init();
    if (!hasAnonymousSessionKey()) {
      await this.purgeAnonymousChatsWithoutSession();
      return null;
    }

    await this.ensureDatabaseReady();
    const chat = await chatDB.getChat(chatId);
    if (!chat?.is_anonymous) return null;
    return this.hydrateAnonymousChat(chat);
  }

  async getMessagesForChat(chatId: string): Promise<Message[]> {
    await this.init();
    if (!hasAnonymousSessionKey()) {
      await this.purgeAnonymousChatsWithoutSession();
      return [];
    }

    await this.ensureDatabaseReady();
    const chat = await chatDB.getChat(chatId);
    if (!chat?.is_anonymous) return [];
    await this.ensureAnonymousChatKey(chat);
    return chatDB.getMessagesForChat(chatId);
  }

  async storeMessages(chatId: string, messages: Message[]): Promise<void> {
    await this.init();
    await this.ensureAnonymousSession();
    await this.ensureDatabaseReady();
    const chat = await chatDB.getChat(chatId);
    if (!chat?.is_anonymous) return;
    await this.ensureAnonymousChatKey(chat);
    for (const message of messages) {
      await chatDB.saveMessage(message);
    }
    window.dispatchEvent(new CustomEvent("anonymousChatsUpdated"));
  }

  async deleteChat(chatId: string): Promise<void> {
    await this.init();
    await this.ensureDatabaseReady();
    await chatDB.deleteChat(chatId);
    window.dispatchEvent(new CustomEvent("anonymousChatsUpdated"));
  }

  async clearAll(): Promise<void> {
    await this.init();
    await this.ensureDatabaseReady();
    const chats = await chatDB.getAllChats();
    for (const chat of chats.filter((candidate) => candidate.is_anonymous)) {
      await chatDB.deleteChat(chat.chat_id);
    }
    try {
      localStorage.removeItem(ANONYMOUS_ID_STORAGE);
      clearAnonymousSessionKey();
      this.clearLegacyPayload();
      chatDB.disableSkipOrphanDetection();
    } catch (error) {
      console.error("[AnonymousChatStorage] Failed to clear anonymous identifiers", error);
    }
    window.dispatchEvent(new CustomEvent("anonymousChatsUpdated"));
  }

  async sendTextMessage(params: {
    markdown: string;
    currentChatId?: string;
    sourceDemoId?: string | null;
  }): Promise<AnonymousSendResult> {
    await this.init();
    await this.ensureAnonymousSession();
    await this.ensureDatabaseReady();

    const now = Math.floor(Date.now() / 1000);
    const existingChat = params.currentChatId?.startsWith(ANONYMOUS_CHAT_PREFIX)
      ? await chatDB.getChat(params.currentChatId)
      : null;
    const isNewChat = !existingChat?.is_anonymous;
    const chatId = existingChat?.is_anonymous
      ? existingChat.chat_id
      : `${ANONYMOUS_CHAT_PREFIX}${crypto.randomUUID()}`;
    const previousMessages = existingChat?.is_anonymous
      ? await this.getMessagesForChat(chatId)
      : [];
    const featureNoticeMessage = isNewChat ? createFeatureNoticeMessage(chatId, now) : null;
    const userMessage: Message = {
      message_id: createMessageId(chatId),
      chat_id: chatId,
      role: "user",
      content: params.markdown,
      status: "sending",
      created_at: now,
      sender_name: "user",
    };

    const chat = isNewChat
      ? await this.createAnonymousChat(chatId, params.markdown, now, params.sourceDemoId ?? null)
      : await this.updateAnonymousChat(existingChat, {
          messages_v: (existingChat.messages_v ?? previousMessages.length) + 1,
          last_edited_overall_timestamp: userMessage.created_at,
          updated_at: now,
        });

    await chatDB.addChat(stripPlainChatFields(chat));
    const pendingMessages = featureNoticeMessage
      ? [featureNoticeMessage, userMessage]
      : [...previousMessages, userMessage];
    for (const message of featureNoticeMessage ? [featureNoticeMessage, userMessage] : [userMessage]) {
      await chatDB.saveMessage(message);
    }
    window.dispatchEvent(new CustomEvent("anonymousChatsUpdated"));

    let response: AnonymousChatResponse;
    try {
      response = await this.postAnonymousChat(chatId, userMessage.message_id, params.markdown, previousMessages);
    } catch (error) {
      const failedUserMessage = { ...userMessage, status: "failed" as const };
      await chatDB.saveMessage(failedUserMessage);
      window.dispatchEvent(new CustomEvent("anonymousChatsUpdated"));
      throw error;
    }

    const assistantMessage: Message = {
      message_id: response.messageId ?? createMessageId(chatId),
      chat_id: chatId,
      role: "assistant",
      content: response.assistant ?? "",
      status: "synced",
      created_at: Math.floor(Date.now() / 1000),
      user_message_id: userMessage.message_id,
      category: response.category ?? undefined,
      model_name: response.modelName ?? undefined,
      sender_name: "assistant",
    };
    const syncedUserMessage = { ...userMessage, status: "synced" as const };
    const updatedChat = await this.updateAnonymousChat(chat, {
      messages_v: pendingMessages.length + 1,
      last_edited_overall_timestamp: assistantMessage.created_at,
      updated_at: assistantMessage.created_at,
      waiting_for_metadata: false,
      category: response.category ?? chat.category ?? DEFAULT_ANONYMOUS_CATEGORY,
      icon: chat.icon ?? DEFAULT_ANONYMOUS_ICON,
    });

    await chatDB.saveMessage(syncedUserMessage);
    await chatDB.saveMessage(assistantMessage);
    await chatDB.addChat(stripPlainChatFields(updatedChat));
    window.dispatchEvent(new CustomEvent("anonymousChatsUpdated"));

    return {
      chat: await this.hydrateAnonymousChat(updatedChat),
      userMessage: syncedUserMessage,
      assistantMessage,
      isNewChat,
    };
  }

  private async ensureDatabaseReady(): Promise<void> {
    if (this.dbReady) return;
    chatDB.enableSkipOrphanDetection();
    await chatDB.init({ skipOrphanDetection: true });
    this.dbReady = true;
  }

  private async ensureAnonymousSession(): Promise<void> {
    await ensureAnonymousSessionKey();
  }

  private async createAnonymousChat(
    chatId: string,
    markdown: string,
    createdAt: number,
    sourceDemoId: string | null,
  ): Promise<Chat> {
    const chatKey = chatKeyManager.createKeyForNewChat(chatId);
    const title = titleFromMarkdown(markdown);
    const encryptedTitle = await encryptWithChatKey(title, chatKey);
    return {
      chat_id: chatId,
      encrypted_title: encryptedTitle,
      anonymous_encrypted_chat_key: await wrapAnonymousChatKey(chatKey),
      messages_v: 2,
      title_v: 1,
      draft_v: 0,
      encrypted_draft_md: null,
      encrypted_draft_preview: null,
      last_edited_overall_timestamp: createdAt,
      unread_count: 0,
      created_at: createdAt,
      updated_at: createdAt,
      processing_metadata: false,
      waiting_for_metadata: true,
      is_anonymous: true,
      source_demo_id: sourceDemoId,
      title,
    };
  }

  private async updateAnonymousChat(chat: Chat, updates: Partial<Chat>): Promise<Chat> {
    const chatKey = await this.ensureAnonymousChatKey(chat);
    const updatedChat: Chat = { ...chat, ...updates, is_anonymous: true };
    const category = updates.category ?? chat.category;
    const icon = updates.icon ?? chat.icon;
    if (category) {
      updatedChat.encrypted_category = await encryptWithChatKey(category, chatKey);
      updatedChat.category = category;
    }
    if (icon) {
      updatedChat.encrypted_icon = await encryptWithChatKey(icon, chatKey);
      updatedChat.icon = icon;
    }
    return updatedChat;
  }

  private async hydrateAnonymousChat(chat: Chat): Promise<Chat> {
    const chatKey = await this.ensureAnonymousChatKey(chat);
    const hydrated = { ...chat, is_anonymous: true };
    if (chat.encrypted_title && !hydrated.title) {
      hydrated.title = await decryptWithChatKey(chat.encrypted_title, chatKey) ?? undefined;
    }
    if (chat.encrypted_category && !hydrated.category) {
      hydrated.category = await decryptWithChatKey(chat.encrypted_category, chatKey) ?? undefined;
    }
    if (chat.encrypted_icon && !hydrated.icon) {
      hydrated.icon = await decryptWithChatKey(chat.encrypted_icon, chatKey) ?? undefined;
    }
    return hydrated;
  }

  private async ensureAnonymousChatKey(chat: Chat): Promise<Uint8Array> {
    const existing = chatKeyManager.getKeySync(chat.chat_id) ?? await chatKeyManager.getKey(chat.chat_id);
    if (existing) return existing;

    const anonymousKey = await unwrapAnonymousChatKey(chat.anonymous_encrypted_chat_key);
    if (anonymousKey) {
      chatKeyManager.injectKey(chat.chat_id, anonymousKey, "anonymous_session");
      return anonymousKey;
    }

    throw new Error(`[AnonymousChatStorage] Anonymous chat key unavailable for ${chat.chat_id}`);
  }

  private async purgeAnonymousChatsWithoutSession(): Promise<void> {
    if (hasAnonymousSessionKey()) return;
    await this.ensureDatabaseReady();
    const chats = await chatDB.getAllChats();
    for (const chat of chats.filter((candidate) => candidate.is_anonymous)) {
      await chatDB.deleteChat(chat.chat_id);
    }
    this.clearLegacyPayload();
    window.dispatchEvent(new CustomEvent("anonymousChatsUpdated"));
  }

  private async postAnonymousChat(
    chatId: string,
    messageId: string,
    markdown: string,
    previousMessages: Message[],
  ): Promise<AnonymousChatResponse> {
    const response = await fetch(getApiEndpoint("/v1/anonymous/chat/stream"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        anonymous_id: this.getAnonymousId(),
        client_chat_id: chatId,
        client_message_id: messageId,
        plaintext_message: markdown,
        message_history: previousMessages.filter(isConversationMessage).map((message) => ({
          role: message.role,
          content: message.content ?? "",
          created_at: message.created_at,
          sender_name: message.sender_name ?? message.role,
        })),
      }),
    });
    const data = (await response.json().catch(() => ({}))) as AnonymousChatResponse;
    if (!response.ok) {
      const detail = data.detail;
      const message = typeof detail === "object" && detail?.message
        ? detail.message
        : typeof detail === "string"
          ? detail
          : `Anonymous chat failed with HTTP ${response.status}`;
      throw new Error(message);
    }
    return data;
  }

  private getAnonymousId(): string {
    let anonymousId = localStorage.getItem(ANONYMOUS_ID_STORAGE);
    if (!anonymousId) {
      anonymousId = crypto.randomUUID();
      localStorage.setItem(ANONYMOUS_ID_STORAGE, anonymousId);
    }
    return anonymousId;
  }

  private clearLegacyPayload(): void {
    try {
      localStorage.removeItem(LEGACY_ANONYMOUS_PAYLOAD_STORAGE);
    } catch (error) {
      console.error("[AnonymousChatStorage] Failed to clear legacy localStorage payload", error);
    }
  }
}

export const anonymousChatStorage = new AnonymousChatStorage();
