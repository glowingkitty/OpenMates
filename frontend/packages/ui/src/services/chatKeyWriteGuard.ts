// frontend/packages/ui/src/services/chatKeyWriteGuard.ts
// Shared guard for client-side writes that persist chat-key-encrypted data.
// It prevents storing ciphertext produced with a raw key that does not match
// the chat's persisted key metadata.

import { notificationStore } from "../stores/notificationStore";
import { encryptedChatKeyMatchesRawKey } from "./chatKeyConsistency";
import { chatDB } from "./db";
import { addCandidateKey } from "./db/chatCrudOperations";
import { decryptChatKeyWithMasterKey } from "./encryption/MetadataEncryptor";
import { computeKeyFingerprint } from "./encryption/ChatKeyManager";

interface ChatKeyWriteGuardOptions {
  allowMissingEncryptedChatKey?: boolean;
}

export async function ensureChatKeySafeForWrite(
  chatId: string,
  rawChatKey: Uint8Array,
  context: string,
  options: ChatKeyWriteGuardOptions = {},
): Promise<boolean> {
  const chat = await chatDB.getChat(chatId);
  const encryptedChatKey =
    chat?.encrypted_chat_key ?? (await chatDB.getEncryptedChatKey(chatId));
  const rawFingerprint = computeKeyFingerprint(rawChatKey);

  if (chat?.key_fingerprint && chat.key_fingerprint !== rawFingerprint) {
    if (encryptedChatKey) addCandidateKey(chatDB, chatId, encryptedChatKey).catch(() => {});
    console.error(
      `[ChatKeyWriteGuard] Refusing ${context} for ${chatId}: raw key fp=${rawFingerprint} ` +
        `does not match stored chat key fp=${chat.key_fingerprint}`,
    );
    notificationStore.error(
      "We could not safely store this update because this chat has conflicting encryption keys. Please reload and try again.",
    );
    return false;
  }

  if (!encryptedChatKey) {
    if (options.allowMissingEncryptedChatKey) return true;
    console.error(
      `[ChatKeyWriteGuard] Refusing ${context} for ${chatId}: no persisted encrypted_chat_key to validate against`,
    );
    return false;
  }

  const keyMatches = await encryptedChatKeyMatchesRawKey(
    encryptedChatKey,
    rawChatKey,
    decryptChatKeyWithMasterKey,
  );

  if (keyMatches === false) {
    addCandidateKey(chatDB, chatId, encryptedChatKey).catch(() => {});
    console.error(
      `[ChatKeyWriteGuard] Refusing ${context} for ${chatId}: raw key does not match persisted encrypted_chat_key`,
    );
    notificationStore.error(
      "We could not safely store this update because this chat has conflicting encryption keys. Please reload and try again.",
    );
    return false;
  }

  if (keyMatches === null) {
    console.warn(
      `[ChatKeyWriteGuard] Could not decrypt encrypted_chat_key while validating ${context} for ${chatId}; ` +
        `allowing write because hidden-chat/master-key fallback may own this wrapper.`,
    );
  }

  return true;
}
