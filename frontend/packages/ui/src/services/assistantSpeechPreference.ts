// assistantSpeechPreference.ts
// Persists the chat-scoped assistant-response speech preference.
// The boolean is encrypted with the chat key before IndexedDB or WebSocket use.
// The server stores only ciphertext and allocates the authoritative metadata version.
// Incognito and public-chat gating remains the caller's responsibility.

import { chatDB } from "./db";
import { chatKeyManager } from "./encryption/ChatKeyManager";
import { decryptWithChatKey, encryptWithChatKey } from "./encryption/MessageEncryptor";
import { webSocketService } from "./websocketService";

const localPreferenceIntents = new Map<string, boolean>();
const METADATA_ACK_TIMEOUT_MS = 15_000;

type MetadataStoredPayload = {
  chat_id?: string;
  versions?: { metadata_v?: number };
};

function waitForMetadataStored(chatId: string, minimumMetadataVersion: number): {
  promise: Promise<void>;
  cancel: () => void;
} {
  let cancel = () => {};
  const promise = new Promise<void>((resolve, reject) => {
    const cleanup = () => {
      clearTimeout(timeout);
      webSocketService.off("encrypted_metadata_stored", handleStored);
    };
    const handleStored = (payload: MetadataStoredPayload) => {
      if (payload.chat_id !== chatId || (payload.versions?.metadata_v ?? 0) < minimumMetadataVersion) return;
      cleanup();
      resolve();
    };
    const timeout = setTimeout(() => {
      cleanup();
      reject(new Error(`Timed out persisting assistant speech preference: ${chatId}`));
    }, METADATA_ACK_TIMEOUT_MS);
    cancel = cleanup;
    webSocketService.on("encrypted_metadata_stored", handleStored);
  });
  return { promise, cancel };
}

export function markAssistantSpeechPreferenceIntent(chatId: string, enabled: boolean): void {
  localPreferenceIntents.set(chatId, enabled);
}

export function hasAssistantSpeechPreferenceIntent(chatId: string): boolean {
  return localPreferenceIntents.has(chatId);
}

export async function getAssistantSpeechPreference(chatId: string): Promise<boolean> {
  const chat = await chatDB.getChat(chatId);
  if (!chat?.encrypted_auto_speak_response) return localPreferenceIntents.get(chatId) ?? false;
  const key = await chatKeyManager.getKey(chatId);
  if (!key) throw new Error(`Chat key unavailable for assistant speech preference: ${chatId}`);
  const value = await decryptWithChatKey(chat.encrypted_auto_speak_response, key);
  return value === "true";
}

export async function setAssistantSpeechPreference(
  chatId: string,
  enabled: boolean,
): Promise<void> {
  markAssistantSpeechPreferenceIntent(chatId, enabled);
  const chat = await chatDB.getChat(chatId);
  if (!chat) return;
  if ((chat.messages_v ?? 0) === 0 && !chat.encrypted_chat_key) return;
  const key = await chatKeyManager.getKey(chatId);
  if (!key) throw new Error(`Chat key unavailable for assistant speech preference: ${chatId}`);
  const encryptedPreference = await encryptWithChatKey(String(enabled), key);
  const nextMetadataVersion = (chat.metadata_v ?? chat.title_v ?? 0) + 1;
  const stored = waitForMetadataStored(chatId, nextMetadataVersion);

  try {
    await webSocketService.sendMessage("encrypted_chat_metadata", {
      chat_id: chatId,
      ...(chat.team_id ? { team_id: chat.team_id } : {}),
      ...(chat.encrypted_chat_key ? { encrypted_chat_key: chat.encrypted_chat_key } : {}),
      encrypted_auto_speak_response: encryptedPreference,
      versions: {
        messages_v: chat.messages_v,
        title_v: chat.title_v,
        metadata_v: chat.metadata_v ?? chat.title_v,
        last_edited_overall_timestamp: chat.last_edited_overall_timestamp,
      },
    });
    await chatDB.updateChat({
      ...chat,
      encrypted_auto_speak_response: encryptedPreference,
      metadata_v: nextMetadataVersion,
      updated_at: Math.floor(Date.now() / 1000),
    });
    await stored.promise;
  } catch (error) {
    stored.cancel();
    throw error;
  }
}
