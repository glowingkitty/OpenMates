// frontend/packages/ui/src/services/anonymousChatPromotionService.ts
// Promotes anonymous free-usage chats after signup without re-keying them.
// Anonymous chats already live in normal IndexedDB chat/message stores with
// normal per-chat keys. Promotion wraps those existing chat keys with the new
// account master key, uploads encrypted history via the normal WebSocket path,
// then clears local anonymous-only markers.

import { anonymousChatStorage } from "./anonymousChatStorage";
import { chatDB } from "./db";
import { chatKeyManager } from "./encryption/ChatKeyManager";
import { webSocketService } from "./websocketService";
import { encryptChatKeyWithMasterKey } from "./cryptoService";
import type { Chat, Message } from "../types/chat";

export interface AnonymousPromotionResult {
  promotedCount: number;
  promotedChatIds: string[];
}

type EncryptedHistoryMessage = Pick<
  Message,
  | "message_id"
  | "chat_id"
  | "role"
  | "created_at"
  | "encrypted_content"
  | "encrypted_sender_name"
  | "encrypted_category"
  | "encrypted_model_name"
  | "encrypted_pii_mappings"
>;

function isPromotableMessage(message: Message): boolean {
  return (
    message.status !== "failed" &&
    message.role !== "system" &&
    typeof message.content === "string" &&
    message.content.trim().length > 0
  );
}

async function buildEncryptedHistory(messages: Message[], chatId: string): Promise<EncryptedHistoryMessage[]> {
  const encryptedMessages: EncryptedHistoryMessage[] = [];
  for (const message of messages.filter(isPromotableMessage)) {
    const syncedMessage: Message = { ...message, status: "synced" };
    const encrypted = await chatDB.encryptMessageFields(syncedMessage, chatId);
    if (!encrypted.encrypted_content) continue;
    encryptedMessages.push({
      message_id: encrypted.message_id,
      chat_id: encrypted.chat_id,
      role: encrypted.role,
      created_at: encrypted.created_at,
      encrypted_content: encrypted.encrypted_content,
      encrypted_sender_name: encrypted.encrypted_sender_name,
      encrypted_category: encrypted.encrypted_category,
      encrypted_model_name: encrypted.encrypted_model_name,
      encrypted_pii_mappings: encrypted.encrypted_pii_mappings,
    });
  }
  return encryptedMessages;
}

async function dispatchPromotedChat(chat: Chat, encryptedHistory: EncryptedHistoryMessage[]): Promise<void> {
  await webSocketService.sendMessage("encrypted_chat_metadata", {
    chat_id: chat.chat_id,
    encrypted_title: chat.encrypted_title,
    encrypted_icon: chat.encrypted_icon,
    encrypted_chat_category: chat.encrypted_category,
    encrypted_chat_key: chat.encrypted_chat_key,
    created_at: chat.created_at,
    versions: {
      messages_v: chat.messages_v,
      title_v: chat.title_v,
      last_edited_overall_timestamp: chat.last_edited_overall_timestamp,
    },
    message_history: encryptedHistory,
  });
}

async function markChatPromoted(chat: Chat, encryptedChatKey: string, messages: Message[]): Promise<Chat> {
  const promotableMessages = messages.filter(isPromotableMessage);
  const firstCreatedAt = promotableMessages[0]?.created_at ?? chat.created_at;
  const lastEditedAt = promotableMessages[promotableMessages.length - 1]?.created_at ?? chat.updated_at;
  const promotedChat: Chat = {
    ...chat,
    encrypted_chat_key: encryptedChatKey,
    anonymous_encrypted_chat_key: null,
    is_anonymous: false,
    messages_v: promotableMessages.length,
    created_at: chat.created_at ?? firstCreatedAt,
    updated_at: lastEditedAt,
    last_edited_overall_timestamp: lastEditedAt,
    waiting_for_metadata: false,
    processing_metadata: false,
  };
  delete promotedChat.title;
  delete promotedChat.category;
  delete promotedChat.icon;
  await chatDB.updateChat(promotedChat);

  for (const message of messages) {
    if (message.role === "system") {
      await chatDB.deleteMessage(message.message_id);
    } else if (isPromotableMessage(message) && message.status !== "synced") {
      await chatDB.saveMessage({ ...message, status: "synced" });
    }
  }

  return promotedChat;
}

export async function promoteAnonymousChatsAfterSignup(): Promise<AnonymousPromotionResult> {
  const anonymousChats = await anonymousChatStorage.getAllChats();
  if (anonymousChats.length === 0) {
    return { promotedCount: 0, promotedChatIds: [] };
  }

  await chatDB.init();
  const promotedChatIds: string[] = [];

  for (const anonymousChat of anonymousChats) {
    const anonymousMessages = await anonymousChatStorage.getMessagesForChat(anonymousChat.chat_id);
    if (!anonymousMessages.some(isPromotableMessage)) continue;

    const chatKey = await chatKeyManager.getKey(anonymousChat.chat_id);
    if (!chatKey) {
      throw new Error(`[AnonymousChatPromotion] Missing chat key for ${anonymousChat.chat_id}`);
    }

    const encryptedChatKey = await encryptChatKeyWithMasterKey(chatKey);
    if (!encryptedChatKey) {
      throw new Error(`[AnonymousChatPromotion] Failed to wrap chat key for ${anonymousChat.chat_id}`);
    }

    const encryptedHistory = await buildEncryptedHistory(anonymousMessages, anonymousChat.chat_id);
    const uploadChat: Chat = {
      ...anonymousChat,
      encrypted_chat_key: encryptedChatKey,
      is_anonymous: false,
      anonymous_encrypted_chat_key: null,
      messages_v: encryptedHistory.length,
      waiting_for_metadata: false,
      processing_metadata: false,
    };
    delete uploadChat.title;
    delete uploadChat.category;
    delete uploadChat.icon;

    await dispatchPromotedChat(uploadChat, encryptedHistory);
    await markChatPromoted(anonymousChat, encryptedChatKey, anonymousMessages);
    promotedChatIds.push(anonymousChat.chat_id);
  }

  if (promotedChatIds.length > 0) {
    await anonymousChatStorage.clearAll();
    window.dispatchEvent(new CustomEvent("localChatListChanged", {
      detail: { chat_id: promotedChatIds[0], autoOpen: true },
    }));
  }

  return { promotedCount: promotedChatIds.length, promotedChatIds };
}
