/**
 * Anonymous free chat local storage.
 *
 * Purpose: keep logged-out free-usage chats local to this browser only.
 * Storage: ciphertext in localStorage, AES-GCM key in sessionStorage.
 * Privacy: if the session key is gone, stored anonymous ciphertext is purged.
 * Server contract: only text/history is sent to /v1/anonymous/chat/stream.
 */

import { get } from "svelte/store";

import { getApiEndpoint } from "../config/api";
import { text } from "../i18n/translations";
import type { Chat, Message } from "../types/chat";

const ANONYMOUS_SESSION_KEY_STORAGE = "openmates_anonymous_chat_key";
const ANONYMOUS_PAYLOAD_STORAGE = "openmates_anonymous_chats_v1";
const ANONYMOUS_ID_STORAGE = "openmates_anonymous_id";
const ANONYMOUS_CHAT_PREFIX = "anonymous-";
const ANONYMOUS_FEATURE_NOTICE_KEY = "chat.anonymous_free_usage.feature_notice";

interface EncryptedAnonymousPayload {
  iv: string;
  data: string;
}

interface AnonymousStoragePayload {
  chats: Chat[];
  messages: Record<string, Message[]>;
}

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

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return btoa(binary);
}

function base64ToBytes(value: string): Uint8Array {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

function bytesToArrayBuffer(bytes: Uint8Array): ArrayBuffer {
  const copy = new Uint8Array(bytes.byteLength);
  copy.set(bytes);
  return copy.buffer as ArrayBuffer;
}

function isBrowserCryptoAvailable(): boolean {
  return typeof window !== "undefined" && !!globalThis.crypto?.subtle;
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
  return message.status !== "failed" && (message.role === "user" || message.role === "assistant");
}

class AnonymousChatStorage {
  private chats = new Map<string, Chat>();
  private messages = new Map<string, Message[]>();
  private initialized = false;
  private cryptoKey: CryptoKey | null = null;

  async init(): Promise<void> {
    if (this.initialized || typeof window === "undefined") return;

    if (!isBrowserCryptoAvailable()) {
      this.clearStorage();
      this.initialized = true;
      return;
    }

    const rawKey = sessionStorage.getItem(ANONYMOUS_SESSION_KEY_STORAGE);
    if (!rawKey) {
      this.clearStorage();
      this.initialized = true;
      return;
    }

    try {
      this.cryptoKey = await this.importKey(rawKey);
      const encrypted = localStorage.getItem(ANONYMOUS_PAYLOAD_STORAGE);
      if (!encrypted) {
        this.initialized = true;
        return;
      }
      const payload = await this.decryptPayload(JSON.parse(encrypted) as EncryptedAnonymousPayload);
      payload.chats.forEach((chat) => this.chats.set(chat.chat_id, { ...chat, is_anonymous: true }));
      Object.entries(payload.messages).forEach(([chatId, messages]) => {
        this.messages.set(chatId, messages);
      });
    } catch (error) {
      console.error("[AnonymousChatStorage] Failed to decrypt anonymous chats; clearing local payload", error);
      this.clearStorage();
    } finally {
      this.initialized = true;
    }
  }

  async getAllChats(): Promise<Chat[]> {
    await this.init();
    return Array.from(this.chats.values());
  }

  async getChat(chatId: string): Promise<Chat | null> {
    await this.init();
    return this.chats.get(chatId) ?? null;
  }

  async getMessagesForChat(chatId: string): Promise<Message[]> {
    await this.init();
    return this.messages.get(chatId) ?? [];
  }

  async storeMessages(chatId: string, messages: Message[]): Promise<void> {
    await this.init();
    this.messages.set(chatId, messages);
    await this.persist();
  }

  async deleteChat(chatId: string): Promise<void> {
    await this.init();
    this.chats.delete(chatId);
    this.messages.delete(chatId);
    await this.persist();
    window.dispatchEvent(new CustomEvent("anonymousChatsUpdated"));
  }

  async clearAll(): Promise<void> {
    await this.init();
    this.clearStorage();
    try {
      localStorage.removeItem(ANONYMOUS_ID_STORAGE);
      sessionStorage.removeItem(ANONYMOUS_SESSION_KEY_STORAGE);
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
    await this.ensureKey();

    const now = Math.floor(Date.now() / 1000);
    const existingChat = params.currentChatId?.startsWith(ANONYMOUS_CHAT_PREFIX)
      ? this.chats.get(params.currentChatId)
      : null;
    const chatId = existingChat?.chat_id ?? `${ANONYMOUS_CHAT_PREFIX}${crypto.randomUUID()}`;
    const previousMessages = this.messages.get(chatId) ?? [];
    const isNewChat = !existingChat;
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

    const chat: Chat = existingChat
      ? {
          ...existingChat,
          messages_v: (existingChat.messages_v ?? previousMessages.length) + 1,
          last_edited_overall_timestamp: userMessage.created_at,
          updated_at: now,
        }
      : {
          chat_id: chatId,
          encrypted_title: null,
          title: titleFromMarkdown(params.markdown),
          messages_v: featureNoticeMessage ? 2 : 1,
          title_v: 1,
          draft_v: 0,
          encrypted_draft_md: null,
          encrypted_draft_preview: null,
          last_edited_overall_timestamp: userMessage.created_at,
          unread_count: 0,
          created_at: now,
          updated_at: now,
          processing_metadata: false,
          waiting_for_metadata: true,
          is_anonymous: true,
          source_demo_id: params.sourceDemoId ?? null,
        };

    this.chats.set(chatId, chat);
    const pendingMessages = featureNoticeMessage
      ? [featureNoticeMessage, userMessage]
      : [...previousMessages, userMessage];
    this.messages.set(chatId, pendingMessages);
    await this.persist();
    window.dispatchEvent(new CustomEvent("anonymousChatsUpdated"));

    let response: AnonymousChatResponse;
    try {
      response = await this.postAnonymousChat(chatId, userMessage.message_id, params.markdown, previousMessages);
    } catch (error) {
      const failedUserMessage = { ...userMessage, status: "failed" as const };
      this.messages.set(chatId, featureNoticeMessage
        ? [featureNoticeMessage, failedUserMessage]
        : [...previousMessages, failedUserMessage]);
      await this.persist();
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
    const updatedChat: Chat = {
      ...chat,
      category: response.category ?? chat.category ?? null,
      icon: chat.icon ?? null,
      waiting_for_metadata: false,
      messages_v: pendingMessages.length + 1,
      last_edited_overall_timestamp: assistantMessage.created_at,
      updated_at: assistantMessage.created_at,
    };
    this.chats.set(chatId, updatedChat);
    this.messages.set(chatId, [...pendingMessages.slice(0, -1), syncedUserMessage, assistantMessage]);
    await this.persist();
    window.dispatchEvent(new CustomEvent("anonymousChatsUpdated"));

    return {
      chat: updatedChat,
      userMessage: syncedUserMessage,
      assistantMessage,
      isNewChat,
    };
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

  private async ensureKey(): Promise<CryptoKey> {
    if (this.cryptoKey) return this.cryptoKey;
    const generatedKey = await crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, true, ["encrypt", "decrypt"]);
    const rawKey = new Uint8Array(await crypto.subtle.exportKey("raw", generatedKey));
    sessionStorage.setItem(ANONYMOUS_SESSION_KEY_STORAGE, bytesToBase64(rawKey));
    this.cryptoKey = generatedKey;
    return generatedKey;
  }

  private async importKey(rawKey: string): Promise<CryptoKey> {
    return crypto.subtle.importKey("raw", bytesToArrayBuffer(base64ToBytes(rawKey)), { name: "AES-GCM" }, true, ["encrypt", "decrypt"]);
  }

  private async persist(): Promise<void> {
    if (typeof window === "undefined") return;
    const key = await this.ensureKey();
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const payload: AnonymousStoragePayload = {
      chats: Array.from(this.chats.values()),
      messages: Object.fromEntries(this.messages.entries()),
    };
    const encoded = new TextEncoder().encode(JSON.stringify(payload));
    const encrypted = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, encoded));
    localStorage.setItem(ANONYMOUS_PAYLOAD_STORAGE, JSON.stringify({
      iv: bytesToBase64(iv),
      data: bytesToBase64(encrypted),
    } satisfies EncryptedAnonymousPayload));
  }

  private async decryptPayload(encrypted: EncryptedAnonymousPayload): Promise<AnonymousStoragePayload> {
    if (!this.cryptoKey) throw new Error("Anonymous chat key is missing");
    const decrypted = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: bytesToArrayBuffer(base64ToBytes(encrypted.iv)) },
      this.cryptoKey,
      bytesToArrayBuffer(base64ToBytes(encrypted.data)),
    );
    return JSON.parse(new TextDecoder().decode(decrypted)) as AnonymousStoragePayload;
  }

  private clearStorage(): void {
    this.chats.clear();
    this.messages.clear();
    this.cryptoKey = null;
    try {
      localStorage.removeItem(ANONYMOUS_PAYLOAD_STORAGE);
    } catch (error) {
      console.error("[AnonymousChatStorage] Failed to clear localStorage payload", error);
    }
  }
}

export const anonymousChatStorage = new AnonymousChatStorage();
