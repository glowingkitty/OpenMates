// frontend/packages/ui/src/services/anonymousChatPromotionService.ts
// Promotes completed anonymous free-usage chats into normal authenticated chat
// storage after signup. The service intentionally uses the normal chat key,
// IndexedDB, and encrypted metadata WebSocket paths so promoted chats become
// regular zero-knowledge chats without adding a parallel server contract.

import { anonymousChatStorage } from "./anonymousChatStorage";
import { chatDB } from "./db";
import { chatKeyManager } from "./encryption/ChatKeyManager";
import { webSocketService } from "./websocketService";
import { encryptWithChatKey } from "./cryptoService";
import type { Chat, Message } from "../types/chat";

const DEFAULT_ANONYMOUS_CATEGORY = "ai";
const DEFAULT_ANONYMOUS_ICON = "sparkles";

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

function clonePlainMessageForPromotion(message: Message, chatId: string): Message | null {
  if (message.status === "failed") return null;
  if (message.role === "system") return null;
  if (typeof message.content !== "string" || !message.content.trim()) return null;
  return {
    message_id: `${chatId.slice(-10)}-${crypto.randomUUID()}`,
    chat_id: chatId,
    role: message.role,
    content: message.content,
    status: "synced",
    created_at: message.created_at,
    sender_name: message.sender_name ?? message.role,
    category: message.category ?? undefined,
    model_name: message.model_name ?? undefined,
    pii_mappings: message.pii_mappings,
  };
}

async function buildEncryptedHistory(messages: Message[], chatId: string): Promise<EncryptedHistoryMessage[]> {
  const encryptedMessages: EncryptedHistoryMessage[] = [];
  for (const message of messages) {
    const encrypted = await chatDB.encryptMessageFields(message, chatId);
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

export async function promoteAnonymousChatsAfterSignup(): Promise<AnonymousPromotionResult> {
  const anonymousChats = await anonymousChatStorage.getAllChats();
  if (anonymousChats.length === 0) {
    return { promotedCount: 0, promotedChatIds: [] };
  }

  await chatDB.init();
  const promotedChatIds: string[] = [];
  const locallySavedChatIds: string[] = [];
  try {
    for (const anonymousChat of anonymousChats) {
      const anonymousMessages = await anonymousChatStorage.getMessagesForChat(anonymousChat.chat_id);
      const chatId = crypto.randomUUID();
      const promotableMessages = anonymousMessages
        .map((message) => clonePlainMessageForPromotion(message, chatId))
        .filter((message): message is Message => message !== null);

      if (promotableMessages.length === 0) continue;

      const { chatKey, encryptedChatKey } = await chatKeyManager.createAndPersistKey(chatId);
      const firstCreatedAt = promotableMessages[0]?.created_at ?? Math.floor(Date.now() / 1000);
      const lastEditedAt = promotableMessages[promotableMessages.length - 1]?.created_at ?? firstCreatedAt;
      const title = typeof anonymousChat.title === "string" && anonymousChat.title.trim()
        ? anonymousChat.title.trim()
        : "Anonymous chat";
      const category = anonymousChat.category || DEFAULT_ANONYMOUS_CATEGORY;
      const icon = anonymousChat.icon || DEFAULT_ANONYMOUS_ICON;
      const promotedChat: Chat = {
        chat_id: chatId,
        encrypted_title: await encryptWithChatKey(title, chatKey),
        encrypted_category: await encryptWithChatKey(category, chatKey),
        encrypted_icon: await encryptWithChatKey(icon, chatKey),
        encrypted_chat_key: encryptedChatKey,
        messages_v: promotableMessages.length,
        title_v: 1,
        draft_v: 0,
        encrypted_draft_md: null,
        encrypted_draft_preview: null,
        last_edited_overall_timestamp: lastEditedAt,
        unread_count: 0,
        created_at: anonymousChat.created_at ?? firstCreatedAt,
        updated_at: lastEditedAt,
        processing_metadata: false,
        waiting_for_metadata: false,
        source_demo_id: anonymousChat.source_demo_id ?? null,
      };
      const encryptedHistory = await buildEncryptedHistory(promotableMessages, chatId);

      await chatDB.addChat(promotedChat);
      for (const message of promotableMessages) {
        await chatDB.saveMessage(message);
      }
      locallySavedChatIds.push(chatId);
      await dispatchPromotedChat(promotedChat, encryptedHistory);
      promotedChatIds.push(chatId);
    }

    if (promotedChatIds.length > 0) {
      await anonymousChatStorage.clearAll();
      window.dispatchEvent(new CustomEvent("localChatListChanged", {
        detail: { chat_id: promotedChatIds[0], autoOpen: true },
      }));
    }

    return { promotedCount: promotedChatIds.length, promotedChatIds };
  } catch (error) {
    for (const chatId of locallySavedChatIds) {
      try {
        await chatDB.deleteChat(chatId);
      } catch (rollbackError) {
        console.error("[AnonymousChatPromotion] Failed to roll back promoted chat", { chatId, rollbackError });
      }
    }
    throw error;
  }
}
