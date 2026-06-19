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
import type { AIMessageUpdatePayload, AITaskInitiatedPayload, AITypingStartedPayload, Chat, Message } from "../types/chat";
import { aiTypingStore } from "../stores/aiTypingStore";
import { chatDB } from "./db";
import { chatKeyManager } from "./encryption/ChatKeyManager";
import { decryptWithChatKey, encryptArrayWithChatKey, encryptWithChatKey } from "./cryptoService";
import { chatSyncService } from "./chatSyncService";
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
const DEFAULT_ANONYMOUS_CATEGORY = "general_knowledge";
const DEFAULT_ANONYMOUS_ICON = "sparkles";
const ANONYMOUS_STREAM_ADAPTER_MAX_CHUNKS = 18;
const MESSAGE_ROLE_ORDER: Record<string, number> = {
  system: 0,
  user: 1,
  assistant: 2,
};

interface AnonymousChatResponse {
  status?: string;
  chatId?: string;
  messageId?: string;
  assistant?: string;
  category?: string | null;
  modelName?: string | null;
  streamed?: boolean;
  chat?: Chat;
  detail?: { code?: string; message?: string } | string;
}

type AnonymousStreamPayload = Record<string, unknown> & { type?: string };

function buildAnonymousTaskId(userMessageId: string): string {
  return `anonymous-task-${userMessageId}`;
}

function splitAnonymousResponseForAdapter(content: string): string[] {
  if (!content) return [""];
  const chunkCount = Math.min(ANONYMOUS_STREAM_ADAPTER_MAX_CHUNKS, Math.max(1, Math.ceil(content.length / 48)));
  const chunkSize = Math.ceil(content.length / chunkCount);
  const chunks: string[] = [];
  for (let end = chunkSize; end < content.length; end += chunkSize) {
    chunks.push(content.slice(0, end));
  }
  chunks.push(content);
  return chunks;
}

export interface AnonymousSendResult {
  chat: Chat;
  userMessage: Message;
  assistantMessage: Message;
  isNewChat: boolean;
}

export interface AnonymousPendingSendResult {
  chat: Chat;
  userMessage: Message;
  isNewChat: boolean;
}

function createMessageId(chatId: string): string {
  return `${chatId.slice(-10)}-${crypto.randomUUID()}`;
}

function assistantMessageIdFromResponse(
  response: AnonymousChatResponse,
  chatId: string,
  userMessageId: string,
): string {
  return response.messageId && response.messageId !== userMessageId
    ? response.messageId
    : createMessageId(chatId);
}

function isEventStreamResponse(response: Response): boolean {
  return (response.headers.get("content-type") || "").toLowerCase().includes("text/event-stream");
}

function normalizeStreamPayload(raw: AnonymousStreamPayload): AnonymousStreamPayload | null {
  if (!raw || typeof raw !== "object") return null;
  const type = typeof raw.type === "string" ? raw.type : typeof raw.event === "string" ? raw.event : null;
  if (!type) return raw;
  return { ...raw, type };
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

function sortAnonymousMessages(messages: Message[]): Message[] {
  return [...messages].sort((a, b) => {
    if (a.message_id === b.user_message_id) return -1;
    if (a.user_message_id === b.message_id) return 1;
    const createdDiff = (a.created_at ?? 0) - (b.created_at ?? 0);
    if (createdDiff !== 0) return createdDiff;
    const roleDiff = (MESSAGE_ROLE_ORDER[a.role] ?? 99) - (MESSAGE_ROLE_ORDER[b.role] ?? 99);
    if (roleDiff !== 0) return roleDiff;
    return a.message_id.localeCompare(b.message_id);
  });
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
    return sortAnonymousMessages(await chatDB.getMessagesForChat(chatId));
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
    onPending?: (pending: AnonymousPendingSendResult) => void | Promise<void>;
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
    await params.onPending?.({
      chat: await this.hydrateAnonymousChat(chat),
      userMessage,
      isNewChat,
    });

    this.dispatchAnonymousTaskInitiated(chatId, userMessage.message_id);

    let response: AnonymousChatResponse;
    try {
      response = await this.postAnonymousChat(chat, userMessage.message_id, params.markdown, previousMessages);
    } catch (error) {
      const failedUserMessage = { ...userMessage, status: "failed" as const };
      await chatDB.saveMessage(failedUserMessage);
      window.dispatchEvent(new CustomEvent("anonymousChatsUpdated"));
      throw error;
    }

    const assistantMessage: Message = {
      message_id: assistantMessageIdFromResponse(response, chatId, userMessage.message_id),
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
    const chatForFinalUpdate = response.chat ?? chat;
    const updatedChat = await this.updateAnonymousChat(chatForFinalUpdate, {
      messages_v: pendingMessages.length + 1,
      last_edited_overall_timestamp: assistantMessage.created_at,
      updated_at: assistantMessage.created_at,
      waiting_for_metadata: false,
      category: response.category ?? chatForFinalUpdate.category ?? DEFAULT_ANONYMOUS_CATEGORY,
      icon: chatForFinalUpdate.icon ?? DEFAULT_ANONYMOUS_ICON,
    });

    await chatDB.saveMessage(syncedUserMessage);
    await chatDB.addChat(stripPlainChatFields(updatedChat));
    window.dispatchEvent(new CustomEvent("anonymousChatsUpdated"));

    const hydratedUpdatedChat = await this.hydrateAnonymousChat(updatedChat);
    chatSyncService.dispatchEvent(new CustomEvent("chatUpdated", {
      detail: { chat_id: chatId, chat: hydratedUpdatedChat, type: "metadata_updated" },
    }));
    if (!response.streamed) {
      await this.dispatchAnonymousAssistantLifecycle({
        chat: hydratedUpdatedChat,
        userMessage: syncedUserMessage,
        assistantMessage,
        category: response.category ?? chat.category ?? DEFAULT_ANONYMOUS_CATEGORY,
        modelName: response.modelName ?? null,
      });
    }

    await chatDB.saveMessage(assistantMessage);

    return {
      chat: hydratedUpdatedChat,
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
      title_v: 0,
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
    const title = updates.title ?? chat.title;
    const category = updates.category ?? chat.category;
    const icon = updates.icon ?? chat.icon;
    if (title) {
      updatedChat.encrypted_title = await encryptWithChatKey(title, chatKey);
      updatedChat.title = title;
      updatedChat.title_v = Math.max(1, updates.title_v ?? chat.title_v ?? 0);
    }
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
    chat: Chat,
    messageId: string,
    markdown: string,
    previousMessages: Message[],
  ): Promise<AnonymousChatResponse> {
    let activeChat = chat;
    const response = await fetch(getApiEndpoint("/v1/anonymous/chat/stream"), {
      method: "POST",
      headers: { "Accept": "text/event-stream", "Content-Type": "application/json" },
      body: JSON.stringify({
        anonymous_id: this.getAnonymousId(),
        client_chat_id: chat.chat_id,
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
    if (response.ok && isEventStreamResponse(response)) {
      return this.consumeAnonymousEventStream(response, activeChat, messageId, (updatedChat) => {
        activeChat = updatedChat;
      });
    }
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

  private async consumeAnonymousEventStream(
    response: Response,
    chat: Chat,
    userMessageId: string,
    onChatUpdated: (chat: Chat) => void,
  ): Promise<AnonymousChatResponse> {
    if (!response.body) {
      throw new Error("Anonymous chat stream response did not include a readable body");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let activeChat = chat;
    let assistant = "";
    let messageId = createMessageId(chat.chat_id);
    let category: string | null = chat.category ?? DEFAULT_ANONYMOUS_CATEGORY;
    let modelName: string | null = null;

    const handlePayload = async (rawPayload: AnonymousStreamPayload) => {
      const payload = normalizeStreamPayload(rawPayload);
      if (!payload) return;
      switch (payload.type) {
        case "ai_task_initiated":
        case "aiTaskInitiated":
          this.dispatchAnonymousTaskInitiated(chat.chat_id, userMessageId, typeof payload.ai_task_id === "string" ? payload.ai_task_id : undefined);
          break;
        case "ai_typing_started":
        case "aiTypingStarted": {
          const typingPayload = this.toTypingStartedPayload(payload, chat.chat_id, userMessageId, messageId);
          messageId = typingPayload.message_id;
          category = typingPayload.category;
          modelName = typingPayload.model_name ?? null;
          activeChat = await this.applyAnonymousStreamMetadata(activeChat, typingPayload);
          onChatUpdated(activeChat);
          this.dispatchAnonymousTypingStarted(typingPayload);
          break;
        }
        case "ai_message_chunk":
        case "aiMessageChunk": {
          const chunkPayload = this.toMessageChunkPayload(payload, chat.chat_id, userMessageId, messageId, modelName);
          messageId = chunkPayload.message_id;
          assistant = chunkPayload.full_content_so_far;
          modelName = chunkPayload.model_name ?? modelName;
          chatSyncService.dispatchEvent(new CustomEvent("aiMessageChunk", { detail: chunkPayload }));
          break;
        }
        case "ai_task_ended":
        case "aiTaskEnded":
          aiTypingStore.clearTyping(chat.chat_id, messageId);
          chatSyncService.activeAITasks.delete(chat.chat_id);
          chatSyncService.dispatchEvent(new CustomEvent("aiTaskEnded", {
            detail: {
              chatId: typeof payload.chatId === "string" ? payload.chatId : chat.chat_id,
              taskId: typeof payload.taskId === "string" ? payload.taskId : buildAnonymousTaskId(userMessageId),
              status: typeof payload.status === "string" ? payload.status : "completed",
            },
          }));
          break;
        case "post_processing_completed":
        case "postProcessingCompleted":
          activeChat = await this.applyAnonymousPostProcessing(activeChat, payload, userMessageId);
          onChatUpdated(activeChat);
          break;
        case "completed":
          if (typeof payload.assistant === "string") assistant = payload.assistant;
          if (typeof payload.messageId === "string") messageId = payload.messageId;
          if (typeof payload.category === "string") category = payload.category;
          if (typeof payload.modelName === "string") modelName = payload.modelName;
          break;
        default:
          break;
      }
    };

    const drainBuffer = async (final = false) => {
      let separatorIndex = buffer.indexOf("\n\n");
      while (separatorIndex !== -1) {
        const frame = buffer.slice(0, separatorIndex).trim();
        buffer = buffer.slice(separatorIndex + 2);
        await this.parseAnonymousStreamFrame(frame, handlePayload);
        separatorIndex = buffer.indexOf("\n\n");
      }
      if (final && buffer.trim()) {
        await this.parseAnonymousStreamFrame(buffer.trim(), handlePayload);
        buffer = "";
      }
    };

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      await drainBuffer();
    }
    buffer += decoder.decode();
    await drainBuffer(true);

    return {
      status: "completed",
      chatId: activeChat.chat_id,
      messageId,
      assistant,
      category,
      modelName,
      streamed: true,
      chat: activeChat,
    };
  }

  private async parseAnonymousStreamFrame(
    frame: string,
    handlePayload: (payload: AnonymousStreamPayload) => Promise<void>,
  ): Promise<void> {
    const dataLines = frame
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trim());
    const payloadText = dataLines.length > 0 ? dataLines.join("\n") : frame.trim();
    if (!payloadText || payloadText === "[DONE]") return;
    try {
      await handlePayload(JSON.parse(payloadText) as AnonymousStreamPayload);
    } catch (error) {
      console.warn("[AnonymousChatStorage] Ignoring malformed stream frame", { payloadText, error });
    }
  }

  private async applyAnonymousStreamMetadata(chat: Chat, payload: AITypingStartedPayload): Promise<Chat> {
    const title = typeof payload.title === "string" && payload.title.trim() ? payload.title.trim() : chat.title;
    const icon = payload.icon_names?.find(Boolean) ?? chat.icon ?? DEFAULT_ANONYMOUS_ICON;
    const updatedChat = await this.updateAnonymousChat(chat, {
      title,
      title_v: title ? 1 : chat.title_v,
      category: payload.category ?? chat.category ?? DEFAULT_ANONYMOUS_CATEGORY,
      icon,
      waiting_for_metadata: false,
      processing_metadata: false,
      updated_at: Math.floor(Date.now() / 1000),
    });
    await chatDB.addChat(stripPlainChatFields(updatedChat));
    const hydratedChat = await this.hydrateAnonymousChat(updatedChat);
    chatSyncService.dispatchEvent(new CustomEvent("chatUpdated", {
      detail: { chat_id: hydratedChat.chat_id, chat: hydratedChat, type: "metadata_updated" },
    }));
    window.dispatchEvent(new CustomEvent("anonymousChatsUpdated"));
    return hydratedChat;
  }

  private async applyAnonymousPostProcessing(
    chat: Chat,
    payload: AnonymousStreamPayload,
    userMessageId: string,
  ): Promise<Chat> {
    const followUpSuggestions = Array.isArray(payload.follow_up_request_suggestions)
      ? payload.follow_up_request_suggestions.filter((item): item is string => typeof item === "string" && item.trim().length > 0)
      : [];
    const quickTipSlugs = Array.isArray(payload.quick_tip_slugs)
      ? payload.quick_tip_slugs.filter((item): item is string => typeof item === "string" && item.trim().length > 0)
      : [];
    const chatSummary = typeof payload.chat_summary === "string" && payload.chat_summary.trim()
      ? payload.chat_summary.trim()
      : null;
    const updatedTitle = typeof payload.updated_chat_title === "string" && payload.updated_chat_title.trim()
      ? payload.updated_chat_title.trim()
      : null;

    const chatKey = await this.ensureAnonymousChatKey(chat);
    const encryptedSummary = chatSummary ? await encryptWithChatKey(chatSummary, chatKey) : null;
    const encryptedFollowUps = followUpSuggestions.length > 0
      ? await encryptArrayWithChatKey(followUpSuggestions.slice(0, 18), chatKey)
      : null;
    const encryptedUpdatedTitle = updatedTitle ? await encryptWithChatKey(updatedTitle, chatKey) : null;

    const updatedChat = await this.updateAnonymousChat(chat, {
      ...(encryptedUpdatedTitle ? { encrypted_title: encryptedUpdatedTitle, title: updatedTitle ?? undefined, title_v: (chat.title_v ?? 0) + 1 } : {}),
      ...(encryptedSummary ? { encrypted_chat_summary: encryptedSummary } : {}),
      ...(encryptedFollowUps ? { encrypted_follow_up_request_suggestions: encryptedFollowUps } : {}),
      updated_at: Math.floor(Date.now() / 1000),
    });
    await chatDB.addChat(stripPlainChatFields(updatedChat));
    const hydratedChat = await this.hydrateAnonymousChat(updatedChat);
    chatSyncService.dispatchEvent(new CustomEvent("chatUpdated", {
      detail: { chat_id: hydratedChat.chat_id, chat: hydratedChat, type: "post_processing_metadata" },
    }));
    chatSyncService.dispatchEvent(new CustomEvent("postProcessingCompleted", {
      detail: {
        chatId: hydratedChat.chat_id,
        taskId: typeof payload.task_id === "string" ? payload.task_id : buildAnonymousTaskId(userMessageId),
        followUpSuggestions,
        quickTipSlugs,
        harmfulResponse: typeof payload.harmful_response === "number" ? payload.harmful_response : 0,
      },
    }));
    window.dispatchEvent(new CustomEvent("anonymousChatsUpdated"));
    return hydratedChat;
  }

  private toTypingStartedPayload(
    payload: AnonymousStreamPayload,
    chatId: string,
    userMessageId: string,
    fallbackMessageId: string,
  ): AITypingStartedPayload {
    const taskId = typeof payload.task_id === "string" ? payload.task_id : buildAnonymousTaskId(userMessageId);
    return {
      chat_id: typeof payload.chat_id === "string" ? payload.chat_id : chatId,
      message_id: typeof payload.message_id === "string" ? payload.message_id : fallbackMessageId,
      user_message_id: typeof payload.user_message_id === "string" ? payload.user_message_id : userMessageId,
      category: typeof payload.category === "string" ? payload.category : DEFAULT_ANONYMOUS_CATEGORY,
      model_name: typeof payload.model_name === "string" ? payload.model_name : null,
      provider_name: typeof payload.provider_name === "string" ? payload.provider_name : null,
      server_region: typeof payload.server_region === "string" ? payload.server_region : null,
      title: typeof payload.title === "string" ? payload.title : null,
      icon_names: Array.isArray(payload.icon_names) ? payload.icon_names.filter((icon): icon is string => typeof icon === "string") : [DEFAULT_ANONYMOUS_ICON],
      task_id: taskId,
    };
  }

  private toMessageChunkPayload(
    payload: AnonymousStreamPayload,
    chatId: string,
    userMessageId: string,
    fallbackMessageId: string,
    fallbackModelName: string | null,
  ): AIMessageUpdatePayload {
    const sequence = typeof payload.sequence === "number" ? payload.sequence : 1;
    return {
      type: "ai_message_chunk",
      task_id: typeof payload.task_id === "string" ? payload.task_id : buildAnonymousTaskId(userMessageId),
      chat_id: typeof payload.chat_id === "string" ? payload.chat_id : chatId,
      message_id: typeof payload.message_id === "string" ? payload.message_id : fallbackMessageId,
      user_message_id: typeof payload.user_message_id === "string" ? payload.user_message_id : userMessageId,
      full_content_so_far: typeof payload.full_content_so_far === "string" ? payload.full_content_so_far : "",
      sequence,
      is_final_chunk: payload.is_final_chunk === true,
      model_name: typeof payload.model_name === "string" ? payload.model_name : fallbackModelName,
    };
  }

  private dispatchAnonymousTaskInitiated(chatId: string, userMessageId: string, taskId = buildAnonymousTaskId(userMessageId)): void {
    const payload: AITaskInitiatedPayload = {
      chat_id: chatId,
      user_message_id: userMessageId,
      ai_task_id: taskId,
      status: "processing_started",
    };
    chatSyncService.activeAITasks.set(chatId, {
      taskId: payload.ai_task_id,
      userMessageId,
    });
    chatSyncService.dispatchEvent(new CustomEvent("aiTaskInitiated", { detail: payload }));
  }

  private dispatchAnonymousTypingStarted(payload: AITypingStartedPayload): void {
    aiTypingStore.setTyping(
      payload.chat_id,
      payload.user_message_id,
      payload.message_id,
      payload.category,
      payload.model_name,
      payload.provider_name,
      payload.server_region,
      payload.icon_names,
    );
    chatSyncService.dispatchEvent(new CustomEvent("aiTypingStarted", { detail: payload }));
  }

  private async dispatchAnonymousAssistantLifecycle(params: {
    chat: Chat;
    userMessage: Message;
    assistantMessage: Message;
    category: string;
    modelName: string | null;
  }): Promise<void> {
    const taskId = buildAnonymousTaskId(params.userMessage.message_id);
    const iconNames = params.chat.icon
      ? params.chat.icon.split(",").map((icon) => icon.trim()).filter(Boolean)
      : [DEFAULT_ANONYMOUS_ICON];
    const typingPayload: AITypingStartedPayload = {
      chat_id: params.chat.chat_id,
      message_id: params.assistantMessage.message_id,
      user_message_id: params.userMessage.message_id,
      category: params.category,
      model_name: params.modelName,
      provider_name: null,
      server_region: null,
      title: typeof params.chat.title === "string" ? params.chat.title : null,
      icon_names: iconNames.length > 0 ? iconNames : [DEFAULT_ANONYMOUS_ICON],
      task_id: taskId,
    };

    this.dispatchAnonymousTypingStarted(typingPayload);

    const chunks = splitAnonymousResponseForAdapter(params.assistantMessage.content ?? "");
    for (let index = 0; index < chunks.length; index += 1) {
      const isFinal = index === chunks.length - 1;
      const payload: AIMessageUpdatePayload = {
        type: "ai_message_chunk",
        task_id: taskId,
        chat_id: params.chat.chat_id,
        message_id: params.assistantMessage.message_id,
        user_message_id: params.userMessage.message_id,
        full_content_so_far: chunks[index],
        sequence: index + 1,
        is_final_chunk: isFinal,
        model_name: params.modelName,
      };
      chatSyncService.dispatchEvent(new CustomEvent("aiMessageChunk", { detail: payload }));
      await Promise.resolve();
    }

    aiTypingStore.clearTyping(params.chat.chat_id, params.assistantMessage.message_id);
    chatSyncService.activeAITasks.delete(params.chat.chat_id);
    chatSyncService.dispatchEvent(new CustomEvent("aiTaskEnded", {
      detail: { chatId: params.chat.chat_id, taskId, status: "completed" },
    }));
  }

  getAnonymousId(): string {
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
