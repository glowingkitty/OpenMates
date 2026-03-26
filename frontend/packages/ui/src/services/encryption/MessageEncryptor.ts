/**
 * MessageEncryptor - Stateless chat-key encryption/decryption
 *
 * Pure functions for encrypting and decrypting chat message content using
 * per-chat AES-256-GCM keys. No state, no side effects, no IDB access.
 * Key is always received as an explicit parameter (key-as-parameter pattern).
 *
 * Handles both Format A (OM-header with fingerprint) and Format B (legacy).
 * See docs/architecture/core/encryption-formats.md for byte-level details.
 *
 * Extracted from cryptoService.ts as part of ARCH-01.
 */

import { uint8ArrayToBase64, base64ToUint8Array } from "../cryptoService";

// AES-GCM constants (redeclared locally — not exported from cryptoService)
const AES_KEY_LENGTH = 256;
const AES_IV_LENGTH = 12;

// ============================================================================
// CRYPTOKEY CACHE
// ============================================================================

/**
 * Cache for imported CryptoKey objects, keyed by key fingerprint.
 * Avoids redundant crypto.subtle.importKey() calls when encrypting/decrypting
 * multiple fields with the same chat key (e.g., 7 fields per message).
 *
 * Two separate caches for encrypt vs decrypt usage flags since importKey
 * requires specifying the allowed operations upfront.
 */
const cryptoKeyCache = {
  encrypt: new Map<string, CryptoKey>(),
  decrypt: new Map<string, CryptoKey>(),
};

// Simple FNV-1a fingerprint for cache keying (matches ChatKeyManager's approach)
function chatKeyFingerprint(key: Uint8Array): string {
  let hash = 0x811c9dc5;
  for (let i = 0; i < key.length; i++) {
    hash ^= key[i];
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

/**
 * Get or import a CryptoKey for the given raw key bytes, using cache.
 */
async function getOrImportCryptoKey(
  rawKey: Uint8Array,
  usage: "encrypt" | "decrypt",
): Promise<CryptoKey> {
  const fp = chatKeyFingerprint(rawKey);
  const cache = cryptoKeyCache[usage];
  const cached = cache.get(fp);
  if (cached) return cached;

  const cryptoKey = await crypto.subtle.importKey(
    "raw",
    new Uint8Array(rawKey),
    { name: "AES-GCM" },
    false,
    [usage],
  );
  cache.set(fp, cryptoKey);
  return cryptoKey;
}

// ============================================================================
// PUBLIC API
// ============================================================================

/**
 * Clear cached CryptoKeys for a specific key fingerprint or all keys.
 * Call when a chat key is removed to prevent stale cache entries.
 */
export function clearCryptoKeyCache(fingerprint?: string): void {
  if (fingerprint) {
    cryptoKeyCache.encrypt.delete(fingerprint);
    cryptoKeyCache.decrypt.delete(fingerprint);
  } else {
    cryptoKeyCache.encrypt.clear();
    cryptoKeyCache.decrypt.clear();
  }
}

/**
 * Generates a chat-specific AES key (32 bytes for AES-256).
 *
 * INTERNAL — only ChatKeyManager.createKeyForNewChat() should call this.
 * All other code must go through ChatKeyManager to ensure key provenance
 * tracking and the immutability guard.
 *
 * @returns Uint8Array - The generated chat key
 * @internal
 */
export function _generateChatKeyInternal(): Uint8Array {
  return crypto.getRandomValues(new Uint8Array(32));
}

/**
 * @deprecated Use chatKeyManager.createKeyForNewChat() instead.
 * This export is kept temporarily for compile-time migration safety.
 * It logs a deprecation warning and delegates to the internal function.
 */
export function generateChatKey(): Uint8Array {
  console.warn(
    "[CryptoService] generateChatKey() called directly — this bypasses ChatKeyManager provenance tracking. " +
      "Use chatKeyManager.createKeyForNewChat() instead.",
  );
  return _generateChatKeyInternal();
}

// ─── Key Fingerprint Constants ──────────────────────────────────────────────
// New ciphertext format embeds a 4-byte key fingerprint so decryption can
// instantly detect "wrong key" without attempting AES-GCM (which is slow and
// gives an opaque OperationError).
//
// Format:  [0x4F 0x4D] [4-byte fingerprint] [12-byte IV] [ciphertext]
// Legacy:  [12-byte IV] [ciphertext]                (no magic header)
//
// The magic bytes "OM" (0x4F, 0x4D) distinguish the two formats.
const CIPHERTEXT_MAGIC = new Uint8Array([0x4f, 0x4d]); // "OM"
const FINGERPRINT_LENGTH = 4;
const CIPHERTEXT_HEADER_LENGTH =
  CIPHERTEXT_MAGIC.length + FINGERPRINT_LENGTH; // 6 bytes

/**
 * Compute a 4-byte FNV-1a fingerprint of a chat key.
 * This is embedded in the ciphertext header so that decryption can detect
 * "wrong key" before even attempting AES-GCM.
 *
 * Exported so ChatKeyManager and diagnostics can use the same algorithm.
 */
export function computeKeyFingerprint4Bytes(key: Uint8Array): Uint8Array {
  let h = 0x811c9dc5; // FNV-1a offset basis
  for (let i = 0; i < key.length; i++) {
    h ^= key[i];
    h = Math.imul(h, 0x01000193);
  }
  const fp = new Uint8Array(4);
  fp[0] = (h >>> 24) & 0xff;
  fp[1] = (h >>> 16) & 0xff;
  fp[2] = (h >>> 8) & 0xff;
  fp[3] = h & 0xff;
  return fp;
}

/**
 * Encrypts data using a chat-specific key (AES-GCM).
 * New format: [OM magic][4-byte key fingerprint][IV][ciphertext] → base64.
 * The fingerprint enables fast "wrong key" detection on decryption.
 *
 * @param data - The data to encrypt
 * @param chatKey - The chat-specific encryption key
 * @returns Promise<string> - Base64 encoded encrypted data with fingerprint + IV
 */
export async function encryptWithChatKey(
  data: string,
  chatKey: Uint8Array,
): Promise<string> {
  const encoder = new TextEncoder();
  const dataBytes = encoder.encode(data);

  // Use cached CryptoKey to avoid redundant importKey calls
  const cryptoKey = await getOrImportCryptoKey(chatKey, "encrypt");

  const iv = crypto.getRandomValues(new Uint8Array(AES_IV_LENGTH));
  const encrypted = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv },
    cryptoKey,
    dataBytes,
  );

  // New format: [magic 2B][fingerprint 4B][IV 12B][ciphertext]
  const fingerprint = computeKeyFingerprint4Bytes(chatKey);
  const combined = new Uint8Array(
    CIPHERTEXT_HEADER_LENGTH + iv.length + encrypted.byteLength,
  );
  combined.set(CIPHERTEXT_MAGIC, 0);
  combined.set(fingerprint, CIPHERTEXT_MAGIC.length);
  combined.set(iv, CIPHERTEXT_HEADER_LENGTH);
  combined.set(new Uint8Array(encrypted), CIPHERTEXT_HEADER_LENGTH + iv.length);

  return uint8ArrayToBase64(combined);
}

/**
 * Decrypts data using a chat-specific key (AES-GCM).
 * Handles both new format (with OM magic + fingerprint) and legacy format.
 *
 * New format: [0x4F 0x4D][4-byte fingerprint][12-byte IV][ciphertext]
 * Legacy:     [12-byte IV][ciphertext]
 *
 * If the new format is detected, the fingerprint is validated FIRST — a mismatch
 * returns null immediately without attempting AES-GCM, which is faster and gives
 * a clear diagnostic ("wrong key") instead of an opaque OperationError.
 *
 * @param encryptedDataWithIV - Base64 encoded encrypted data with IV
 * @param chatKey - The chat-specific decryption key
 * @param context - Optional debug context (chatId, fieldName) included in error logs
 * @returns Promise<string | null> - Decrypted data or null if decryption fails
 */
export async function decryptWithChatKey(
  encryptedDataWithIV: string,
  chatKey: Uint8Array,
  context?: { chatId?: string; fieldName?: string },
): Promise<string | null> {
  try {
    const combined = base64ToUint8Array(encryptedDataWithIV);

    let iv: Uint8Array;
    let ciphertext: Uint8Array;

    // Check for new format: magic bytes "OM" (0x4F, 0x4D)
    if (
      combined.length > CIPHERTEXT_HEADER_LENGTH + AES_IV_LENGTH &&
      combined[0] === 0x4f &&
      combined[1] === 0x4d
    ) {
      // New format — validate key fingerprint before attempting decryption
      const storedFp = combined.slice(
        CIPHERTEXT_MAGIC.length,
        CIPHERTEXT_HEADER_LENGTH,
      );
      const actualFp = computeKeyFingerprint4Bytes(chatKey);

      if (
        storedFp[0] !== actualFp[0] ||
        storedFp[1] !== actualFp[1] ||
        storedFp[2] !== actualFp[2] ||
        storedFp[3] !== actualFp[3]
      ) {
        // Key fingerprint mismatch — fast fail with clear diagnostic
        const chatId = context?.chatId ?? "unknown";
        const fieldName = context?.fieldName ?? "unknown";
        const storedHex = Array.from(storedFp)
          .map((b) => b.toString(16).padStart(2, "0"))
          .join("");
        const actualHex = Array.from(actualFp)
          .map((b) => b.toString(16).padStart(2, "0"))
          .join("");
        console.error(
          `[CryptoService] Key fingerprint mismatch: data encrypted with key fp=${storedHex}, ` +
            `but attempting decryption with key fp=${actualHex}. ` +
            `chat_id=${chatId} field=${fieldName}. ` +
            `This means the data was encrypted with a DIFFERENT key than the one currently loaded.`,
        );
        return null;
      }

      iv = combined.slice(
        CIPHERTEXT_HEADER_LENGTH,
        CIPHERTEXT_HEADER_LENGTH + AES_IV_LENGTH,
      );
      ciphertext = combined.slice(CIPHERTEXT_HEADER_LENGTH + AES_IV_LENGTH);
    } else {
      // Legacy format — no fingerprint header
      iv = combined.slice(0, AES_IV_LENGTH);
      ciphertext = combined.slice(AES_IV_LENGTH);
    }

    // Use cached CryptoKey to avoid redundant importKey calls
    const cryptoKey = await getOrImportCryptoKey(chatKey, "decrypt");

    const decrypted = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: new Uint8Array(iv) },
      cryptoKey,
      new Uint8Array(ciphertext),
    );

    const decoder = new TextDecoder();
    return decoder.decode(decrypted);
  } catch (error) {
    // Enhanced logging with key provenance to help diagnose decryption failures.
    // Import ChatKeyManager lazily to get provenance info without circular deps.
    const chatId = context?.chatId ?? "unknown";
    const fieldName = context?.fieldName ?? "unknown";
    let provenanceInfo = "";
    try {
      const { chatKeyManager } = await import("./ChatKeyManager");
      const prov =
        chatId !== "unknown" ? chatKeyManager.getProvenance(chatId) : null;
      if (prov) {
        provenanceInfo =
          ` Key provenance: source=${prov.source}, fingerprint=${prov.keyFingerprint}, ` +
          `loaded_at=${new Date(prov.timestamp).toISOString()}.`;
      }
    } catch {
      // Provenance lookup is best-effort
    }
    console.error(
      `[CryptoService] Chat decryption failed: ${error instanceof Error ? error.message : String(error)}. ` +
        `chat_id=${chatId} field=${fieldName}. ` +
        `Error type: ${error instanceof Error ? error.constructor.name : typeof error}. ` +
        `Encrypted data length: ${encryptedDataWithIV.length} chars. ` +
        `Chat key length: ${chatKey.length} bytes.${provenanceInfo} ` +
        `This usually indicates: wrong chat key, malformed encrypted content, or content encrypted with different key.`,
    );
    return null;
  }
}

/**
 * Encrypts a JSON array (like mates) using a chat-specific key
 * @param array - The array to encrypt
 * @param chatKey - The chat-specific encryption key
 * @returns Promise<string> - Base64 encoded encrypted array
 */
export async function encryptArrayWithChatKey(
  array: any[],
  chatKey: Uint8Array,
): Promise<string> {
  const jsonString = JSON.stringify(array);
  return await encryptWithChatKey(jsonString, chatKey);
}

/**
 * Decrypts a JSON array using a chat-specific key
 * @param encryptedArrayWithIV - Base64 encoded encrypted array with IV
 * @param chatKey - The chat-specific decryption key
 * @returns Promise<any[] | null> - Decrypted array or null if decryption fails
 */
export async function decryptArrayWithChatKey(
  encryptedArrayWithIV: string,
  chatKey: Uint8Array,
): Promise<any[] | null> {
  const decryptedJson = await decryptWithChatKey(encryptedArrayWithIV, chatKey);
  if (!decryptedJson) return null;

  try {
    return JSON.parse(decryptedJson);
  } catch (error) {
    console.error("Error parsing decrypted array:", error);
    return null;
  }
}
