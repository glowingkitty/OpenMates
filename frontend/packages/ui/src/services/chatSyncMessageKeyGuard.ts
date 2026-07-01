// frontend/packages/ui/src/services/chatSyncMessageKeyGuard.ts
// Guards server-synced encrypted messages before IndexedDB persistence.
// Sync may legitimately see old chats whose encrypted_chat_key can no longer
// be unwrapped on this device. Persisting those encrypted messages causes later
// render paths to emit CLIENT_DECRYPT errors repeatedly. Keep the chat metadata
// recoverable, but defer message storage until a usable key is available.

import type { Message } from "../types/chat";
import { chatDB } from "./db";
import { chatKeyManager } from "./encryption/ChatKeyManager";
import { decryptWithChatKey } from "./encryption/MessageEncryptor";

const ENCRYPTED_MESSAGE_FIELDS = [
  "encrypted_content",
  "encrypted_sender_name",
  "encrypted_category",
  "encrypted_model_name",
  "encrypted_thinking_content",
  "encrypted_thinking_signature",
  "encrypted_pii_mappings",
] as const;

type EncryptedMessageField = (typeof ENCRYPTED_MESSAGE_FIELDS)[number];

export interface SyncedMessageFilterResult {
  messages: Message[];
  skippedChatIds: Set<string>;
}

function messageNeedsChatKey(message: Message): boolean {
  return ENCRYPTED_MESSAGE_FIELDS.some((field: EncryptedMessageField) => {
    const value = message[field];
    return typeof value === "string" && value.length > 0;
  });
}

function getSampleEncryptedValue(messages: Message[]): string | null {
  for (const message of messages) {
    for (const field of ENCRYPTED_MESSAGE_FIELDS) {
      const value = message[field];
      if (typeof value === "string" && value.length > 0) {
        return value;
      }
    }
  }
  return null;
}

async function canDecryptSampleMessage(
  messages: Message[],
  chatKey: Uint8Array,
): Promise<boolean> {
  const sample = getSampleEncryptedValue(messages);
  if (!sample) {
    return true;
  }
  return (await decryptWithChatKey(sample, chatKey)) !== null;
}

async function canPersistEncryptedMessagesForChat(
  chatId: string,
  messages: Message[],
  encryptedChatKey: string | null | undefined,
  context: string,
): Promise<boolean> {
  if (!messages.some(messageNeedsChatKey)) {
    return true;
  }

  let chatKey: Uint8Array | null = null;

  if (encryptedChatKey) {
    chatKey = await chatKeyManager.receiveKeyFromServer(
      chatId,
      encryptedChatKey,
    );
  }

  if (!chatKey) {
    chatKey = chatKeyManager.getKeySync(chatId);
  }

  if (!chatKey) {
    chatKey = await chatKeyManager.getKey(chatId);
  }

  if (!chatKey) {
    const storedChat = await chatDB.getChat(chatId);
    const storedEncryptedChatKey = storedChat?.encrypted_chat_key;
    if (storedEncryptedChatKey && storedEncryptedChatKey !== encryptedChatKey) {
      chatKey = await chatKeyManager.receiveKeyFromServer(
        chatId,
        storedEncryptedChatKey,
      );
    }
  }

  if (chatKey && (await canDecryptSampleMessage(messages, chatKey))) {
    return true;
  }

  console.warn(
    `[ChatSyncService] ${context}: Skipping ${messages.length} encrypted message(s) for chat ${chatId} because no usable chat key is available.`,
  );
  return false;
}

export async function filterPersistableSyncedMessagesWithSkipped(
  messages: Message[],
  encryptedChatKeysByChatId: Map<string, string | null | undefined>,
  context: string,
): Promise<SyncedMessageFilterResult> {
  const messagesByChatId = new Map<string, Message[]>();

  for (const message of messages) {
    const chatMessages = messagesByChatId.get(message.chat_id) ?? [];
    chatMessages.push(message);
    messagesByChatId.set(message.chat_id, chatMessages);
  }

  const persistableMessages: Message[] = [];
  const skippedChatIds = new Set<string>();
  for (const [chatId, chatMessages] of Array.from(messagesByChatId.entries())) {
    const canPersist = await canPersistEncryptedMessagesForChat(
      chatId,
      chatMessages,
      encryptedChatKeysByChatId.get(chatId),
      context,
    );
    if (canPersist) {
      persistableMessages.push(...chatMessages);
    } else {
      skippedChatIds.add(chatId);
    }
  }

  return { messages: persistableMessages, skippedChatIds };
}

export async function markSyncedMessagesDeferred(
  chatId: string,
  context: string,
): Promise<void> {
  const chat = await chatDB.getChat(chatId);
  if (!chat || chat.messages_v === 0) {
    return;
  }
  await chatDB.updateChat({ ...chat, messages_v: 0 });
  console.warn(
    `[ChatSyncService] ${context}: Reset messages_v for chat ${chatId} so deferred encrypted messages can be retried.`,
  );
}

export async function filterPersistableSyncedMessages(
  messages: Message[],
  encryptedChatKeysByChatId: Map<string, string | null | undefined>,
  context: string,
): Promise<Message[]> {
  const result = await filterPersistableSyncedMessagesWithSkipped(
    messages,
    encryptedChatKeysByChatId,
    context,
  );
  return result.messages;
}
