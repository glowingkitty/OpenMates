// frontend/packages/ui/src/services/db/decryptionFailureCache.ts
// In-memory cache of permanently failed decryption attempts.
// Prevents repeated crypto.subtle.decrypt() calls for messages with wrong keys
// (rotated, vault-encrypted, multi-tab auth disruption, etc.).
//
// Architecture: This is a standalone module to avoid circular dependencies
// between ChatKeyManager (which clears the cache on key changes) and
// chatKeyManagement (which reads/writes the cache during decryption).
//
// Cache keys include the key fingerprint so that a failure recorded with key K2
// does not prevent a retry with a different key K1 (e.g. after key rotation or
// correction). The cache is still cleared entirely when setKeyWithProvenance fires.

/**
 * Keyed by chatId → Set of "messageId:fieldName:keyFingerprint" strings that
 * permanently failed decryption. Cleared when a new key is loaded for a chat
 * or on logout.
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

/** Check if a message field is known to fail decryption with the given key. */
export function isKnownDecryptionFailure(
  chatId: string,
  messageId: string,
  fieldName: string,
  keyFingerprint?: string,
): boolean {
  const chatFailures = decryptionFailureCache.get(chatId);
  if (!chatFailures) return false;
  // If fingerprint provided, check specific key. Otherwise check without fingerprint (legacy).
  if (keyFingerprint) {
    return chatFailures.has(`${messageId}:${fieldName}:${keyFingerprint}`);
  }
  // Fallback: check if any entry starts with messageId:fieldName (backwards compat)
  const prefix = `${messageId}:${fieldName}`;
  const entries = Array.from(chatFailures);
  for (let i = 0; i < entries.length; i++) {
    if (entries[i] === prefix || entries[i].startsWith(`${prefix}:`)) return true;
  }
  return false;
}

/** Record a permanent decryption failure for a message field with a specific key. */
export function recordDecryptionFailure(
  chatId: string,
  messageId: string,
  fieldName: string,
  keyFingerprint?: string,
): void {
  let chatFailures = decryptionFailureCache.get(chatId);
  if (!chatFailures) {
    chatFailures = new Set();
    decryptionFailureCache.set(chatId, chatFailures);
  }
  const cacheKey = keyFingerprint
    ? `${messageId}:${fieldName}:${keyFingerprint}`
    : `${messageId}:${fieldName}`;
  chatFailures.add(cacheKey);
}
