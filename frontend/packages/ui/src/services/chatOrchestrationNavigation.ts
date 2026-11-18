/**
 * Shell helpers of chat orchestration UI: the decrypted local title of a linked
 * chat and navigation to it. Parsing and rules live in the Rust core
 * (rustCore/crypto/orchestrationOps.ts); this only reads local state.
 */
import { chatDB } from './db';
import { chatKeyManager } from './encryption/ChatKeyManager';
import { decryptWithChatKey } from './cryptoService';
import { openChatWhenAvailable } from './forkChatService';

/** Current decrypted title of a local chat, or null when unknown or not yet titled. */
export async function localChatTitle(chatId: string): Promise<string | null> {
  const chat = await chatDB.getChat(chatId);
  if (!chat?.encrypted_title) return null;
  const key = await chatKeyManager.getKey(chatId);
  if (!key) return null;
  const title = await decryptWithChatKey(chat.encrypted_title, key, { chatId, fieldName: 'encrypted_title' });
  return title?.trim() ? title : null;
}

/** Opens a linked chat (creator or spawned) once it exists locally. */
export function openLinkedChat(chatId: string): Promise<void> {
  return openChatWhenAvailable(chatId);
}
