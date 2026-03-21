// frontend/packages/ui/src/services/db/decryptionFailureCache.ts
// In-memory cache of permanently failed decryption attempts.
// Prevents repeated crypto.subtle.decrypt() calls for messages with wrong keys
// (rotated, vault-encrypted, multi-tab auth disruption, etc.).
//
// Architecture: This is a standalone module to avoid circular dependencies
// between ChatKeyManager (which clears the cache on key changes) and
// chatKeyManagement (which reads/writes the cache during decryption).

/**
 * Keyed by chatId → Set of "messageId:fieldName" strings that permanently
 * failed decryption. Cleared when a new key is loaded for a chat or on logout.
 */
const decryptionFailureCache = new Map<string, Set<string>>();

/**
 * Clear the decryption failure cache for a specific chat or all chats.
 * Called when a new key is loaded (giving previously-failed messages a chance)
 * or on logout.
 */
export function clearDecryptionFailureCache(chatId?: string): void {
  if (chatId) {
    decryptionFailureCache.delete(chatId);
  } else {
    decryptionFailureCache.clear();
  }
}

/** Check if a message field is known to fail decryption. */
export function isKnownDecryptionFailure(
  chatId: string,
  messageId: string,
  fieldName: string,
): boolean {
  return (
    decryptionFailureCache.get(chatId)?.has(`${messageId}:${fieldName}`) ??
    false
  );
}

/** Record a permanent decryption failure for a message field. */
export function recordDecryptionFailure(
  chatId: string,
  messageId: string,
  fieldName: string,
): void {
  let chatFailures = decryptionFailureCache.get(chatId);
  if (!chatFailures) {
    chatFailures = new Set();
    decryptionFailureCache.set(chatId, chatFailures);
  }
  chatFailures.add(`${messageId}:${fieldName}`);
}
