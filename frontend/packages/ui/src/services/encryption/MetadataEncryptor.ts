/**
 * MetadataEncryptor - Stateless master-key and embed-key encryption
 *
 * Handles encryption of non-message fields: chat titles, drafts, embed data,
 * chat key wrapping/unwrapping, and embed key management. Uses master CryptoKey
 * from IndexedDB for Format C (wrapped chat keys) and Format D (arbitrary data).
 * Extracted from cryptoService.ts as part of ARCH-02.
 */

import {
  uint8ArrayToBase64,
  base64ToUint8Array,
  getKeyFromStorage,
} from "../cryptoService";

const AES_IV_LENGTH = 12;

// ── Master-key encrypt/decrypt (Format D) ──────────────────────────────────

/**
 * Encrypts data using the master key from IndexedDB
 * @param data - The data string to encrypt
 * @returns Promise<string | null> - Base64 encoded encrypted data with IV, or null if key not found
 */
export async function encryptWithMasterKey(
  data: string,
): Promise<string | null> {
  const masterKey = await getKeyFromStorage();
  if (!masterKey) {
    console.error("Master key not found in storage");
    return null;
  }

  return await encryptWithMasterKeyDirect(data, masterKey);
}

/**
 * Encrypts data using a provided master key (for use during signup/login before key is stored)
 * @param data - The data string to encrypt
 * @param masterKey - The master key CryptoKey to use for encryption
 * @returns Promise<string | null> - Base64 encoded encrypted data with IV, or null if encryption fails
 */
export async function encryptWithMasterKeyDirect(
  data: string,
  masterKey: CryptoKey,
): Promise<string | null> {
  try {
    const encoder = new TextEncoder();
    const dataBytes = encoder.encode(data);
    const iv = crypto.getRandomValues(new Uint8Array(AES_IV_LENGTH));

    const encrypted = await crypto.subtle.encrypt(
      { name: "AES-GCM", iv },
      masterKey,
      dataBytes,
    );

    // Combine IV + ciphertext
    const combined = new Uint8Array(iv.length + encrypted.byteLength);
    combined.set(iv);
    combined.set(new Uint8Array(encrypted), iv.length);

    return uint8ArrayToBase64(combined);
  } catch (error) {
    console.error("Encryption failed:", error);
    return null;
  }
}

/**
 * Decrypts data using the master key from IndexedDB
 * @param encryptedDataWithIV - Base64 encoded encrypted data with IV
 * @returns Promise<string | null> - Decrypted data string, or null if decryption fails
 */
export async function decryptWithMasterKey(
  encryptedDataWithIV: string,
): Promise<string | null> {
  const masterKey = await getKeyFromStorage();
  if (!masterKey) {
    console.error("Master key not found in storage");
    return null;
  }

  try {
    const combined = base64ToUint8Array(encryptedDataWithIV);
    const iv = combined.slice(0, AES_IV_LENGTH);
    const ciphertext = combined.slice(AES_IV_LENGTH);

    const decrypted = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv },
      masterKey,
      ciphertext,
    );

    const decoder = new TextDecoder();
    return decoder.decode(decrypted);
  } catch (error) {
    // OperationError is expected when data was encrypted with a different master key
    // (e.g. stale suggestions from a previous login session with a different key).
    // Callers receive null and filter it out — this is not an application error.
    console.debug(
      "Decryption failed (likely stale data from a different key):",
      error,
    );
    return null;
  }
}

// ── Chat key wrapping/unwrapping (Format C) ────────────────────────────────

/**
 * Encrypts a chat key with the user's master key for device sync
 * @param chatKey - The chat-specific key to encrypt
 * @returns Promise<string | null> - Base64 encoded encrypted chat key or null if master key not found
 */
export async function encryptChatKeyWithMasterKey(
  chatKey: Uint8Array,
): Promise<string | null> {
  const masterKey = await getKeyFromStorage();
  if (!masterKey) {
    return null;
  }

  try {
    const iv = crypto.getRandomValues(new Uint8Array(AES_IV_LENGTH));
    // Ensure chatKey is a proper BufferSource
    const chatKeyBuffer = new Uint8Array(chatKey);
    const encrypted = await crypto.subtle.encrypt(
      { name: "AES-GCM", iv },
      masterKey,
      chatKeyBuffer,
    );

    // Combine IV + ciphertext
    const combined = new Uint8Array(iv.length + encrypted.byteLength);
    combined.set(iv);
    combined.set(new Uint8Array(encrypted), iv.length);

    return uint8ArrayToBase64(combined);
  } catch (error) {
    console.error("Failed to encrypt chat key:", error);
    return null;
  }
}

/**
 * Decrypts a chat key using the user's master key
 * @param encryptedChatKeyWithIV - Base64 encoded encrypted chat key with IV
 * @returns Promise<Uint8Array | null> - Decrypted chat key or null if decryption fails
 */
export async function decryptChatKeyWithMasterKey(
  encryptedChatKeyWithIV: string,
  prefetchedMasterKey?: CryptoKey,
): Promise<Uint8Array | null> {
  const masterKey = prefetchedMasterKey ?? await getKeyFromStorage();
  if (!masterKey) {
    return null;
  }

  try {
    const combined = base64ToUint8Array(encryptedChatKeyWithIV);
    const iv = combined.slice(0, AES_IV_LENGTH);
    const ciphertext = combined.slice(AES_IV_LENGTH);

    const decrypted = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv },
      masterKey,
      ciphertext,
    );

    return new Uint8Array(decrypted);
  } catch (error) {
    // Decryption failure is expected for hidden chats (they use a different key)
    // Only log at debug level to avoid noise in console
    console.debug(
      "Failed to decrypt chat key with master key (may be a hidden chat):",
      error,
    );
    return null;
  }
}

// ── Embed key management ────────────────────────────────────────────────────

/** Generates an embed-specific AES key (32 bytes for AES-256) */
export function generateEmbedKey(): Uint8Array {
  return crypto.getRandomValues(new Uint8Array(32));
}

/**
 * Derives an embed-specific AES key deterministically from the chat key and embed ID.
 * Uses HKDF-SHA256 so that every tab/device with the same chat key produces the
 * identical embed key for a given embed -- eliminating the multi-tab race condition
 * where two tabs would generate different random keys for the same embed.
 */
export async function deriveEmbedKeyFromChatKey(
  chatKey: Uint8Array,
  embedId: string,
): Promise<Uint8Array> {
  // Import chatKey as HKDF key material.
  // Wrap in a new Uint8Array to guarantee a plain ArrayBuffer backing store
  // (avoids TS strict-mode BufferSource incompatibility with SharedArrayBuffer).
  const hkdfKey = await crypto.subtle.importKey(
    "raw",
    new Uint8Array(chatKey) as unknown as ArrayBuffer,
    "HKDF",
    false,
    ["deriveBits"],
  );

  // Fixed salt scoped to this derivation context (prevents cross-protocol collisions)
  const salt = new TextEncoder().encode("openmates-embed-key-v1");
  const info = new TextEncoder().encode(embedId);

  const derivedBits = await crypto.subtle.deriveBits(
    { name: "HKDF", hash: "SHA-256", salt, info },
    hkdfKey,
    256, // 32 bytes for AES-256
  );

  return new Uint8Array(derivedBits);
}

/** Wraps an embed key with the user's master key for owner cross-chat access */
export async function wrapEmbedKeyWithMasterKey(
  embedKey: Uint8Array,
): Promise<string | null> {
  const masterKey = await getKeyFromStorage();
  if (!masterKey) {
    return null;
  }

  try {
    const iv = crypto.getRandomValues(new Uint8Array(AES_IV_LENGTH));
    const embedKeyBuffer = new Uint8Array(embedKey);
    const encrypted = await crypto.subtle.encrypt(
      { name: "AES-GCM", iv },
      masterKey,
      embedKeyBuffer,
    );

    // Combine IV + ciphertext
    const combined = new Uint8Array(iv.length + encrypted.byteLength);
    combined.set(iv);
    combined.set(new Uint8Array(encrypted), iv.length);

    return uint8ArrayToBase64(combined);
  } catch (error) {
    console.error("Failed to wrap embed key with master key:", error);
    return null;
  }
}

/** Unwraps an embed key using the user's master key */
export async function unwrapEmbedKeyWithMasterKey(
  wrappedEmbedKey: string,
  embedId?: string,
): Promise<Uint8Array | null> {
  const masterKey = await getKeyFromStorage();
  if (!masterKey) {
    console.warn(
      `[CryptoService] unwrapEmbedKeyWithMasterKey: No master key in storage! embed_id=${embedId ?? "unknown"}`,
    );
    return null;
  }

  try {
    const combined = base64ToUint8Array(wrappedEmbedKey);
    const iv = combined.slice(0, AES_IV_LENGTH);
    const ciphertext = combined.slice(AES_IV_LENGTH);

    const decrypted = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv },
      masterKey,
      ciphertext,
    );

    console.debug(
      "[CryptoService] Successfully unwrapped embed key with master key, length:",
      decrypted.byteLength,
    );
    return new Uint8Array(decrypted);
  } catch (error) {
    console.warn(
      `[CryptoService] Failed to unwrap embed key with master key (key mismatch?): embed_id=${embedId ?? "unknown"}`,
      error,
    );
    return null;
  }
}

/** Wraps an embed key with a chat key for shared chat access */
export async function wrapEmbedKeyWithChatKey(
  embedKey: Uint8Array,
  chatKey: Uint8Array,
): Promise<string> {
  const chatKeyBuffer = new Uint8Array(chatKey);
  const cryptoKey = await crypto.subtle.importKey(
    "raw",
    chatKeyBuffer,
    { name: "AES-GCM" },
    false,
    ["encrypt"],
  );

  const iv = crypto.getRandomValues(new Uint8Array(AES_IV_LENGTH));
  const embedKeyBuffer = new Uint8Array(embedKey);
  const encrypted = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv },
    cryptoKey,
    embedKeyBuffer,
  );

  // Combine IV + ciphertext
  const combined = new Uint8Array(iv.length + encrypted.byteLength);
  combined.set(iv);
  combined.set(new Uint8Array(encrypted), iv.length);

  return uint8ArrayToBase64(combined);
}

/** Unwraps an embed key using a chat key (for shared chat access) */
export async function unwrapEmbedKeyWithChatKey(
  wrappedEmbedKey: string,
  chatKey: Uint8Array,
  context?: { embedId?: string; chatId?: string },
): Promise<Uint8Array | null> {
  try {
    const chatKeyBuffer = new Uint8Array(chatKey);
    const cryptoKey = await crypto.subtle.importKey(
      "raw",
      chatKeyBuffer,
      { name: "AES-GCM" },
      false,
      ["decrypt"],
    );

    const combined = base64ToUint8Array(wrappedEmbedKey);
    const iv = combined.slice(0, AES_IV_LENGTH);
    const ciphertext = combined.slice(AES_IV_LENGTH);

    const decrypted = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv },
      cryptoKey,
      ciphertext,
    );

    console.debug(
      "[CryptoService] Successfully unwrapped embed key with chat key, length:",
      decrypted.byteLength,
    );
    return new Uint8Array(decrypted);
  } catch (error) {
    const embedId = context?.embedId ?? "unknown";
    const chatId = context?.chatId ?? "unknown";
    console.warn(
      `[CryptoService] Failed to unwrap embed key with chat key: embed_id=${embedId} chat_id=${chatId}`,
      error,
    );
    return null;
  }
}

/** Encrypts data using an embed-specific key (AES-GCM) */
export async function encryptWithEmbedKey(
  data: string,
  embedKey: Uint8Array,
): Promise<string> {
  const encoder = new TextEncoder();
  const dataBytes = encoder.encode(data);

  const embedKeyBuffer = new Uint8Array(embedKey);
  const cryptoKey = await crypto.subtle.importKey(
    "raw",
    embedKeyBuffer,
    { name: "AES-GCM" },
    false,
    ["encrypt"],
  );

  const iv = crypto.getRandomValues(new Uint8Array(AES_IV_LENGTH));
  const encrypted = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv },
    cryptoKey,
    dataBytes,
  );

  // Combine IV + ciphertext
  const combined = new Uint8Array(iv.length + encrypted.byteLength);
  combined.set(iv);
  combined.set(new Uint8Array(encrypted), iv.length);

  return uint8ArrayToBase64(combined);
}

/** Decrypts data using an embed-specific key (AES-GCM) */
export async function decryptWithEmbedKey(
  encryptedDataWithIV: string,
  embedKey: Uint8Array,
  context?: { embedId?: string; chatId?: string; fieldName?: string },
): Promise<string | null> {
  try {
    const combined = base64ToUint8Array(encryptedDataWithIV);
    const iv = combined.slice(0, AES_IV_LENGTH);
    const ciphertext = combined.slice(AES_IV_LENGTH);

    const embedKeyBuffer = new Uint8Array(embedKey);
    const cryptoKey = await crypto.subtle.importKey(
      "raw",
      embedKeyBuffer,
      { name: "AES-GCM" },
      false,
      ["decrypt"],
    );

    const decrypted = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv },
      cryptoKey,
      ciphertext,
    );

    const decoder = new TextDecoder();
    return decoder.decode(decrypted);
  } catch (error) {
    const embedId = context?.embedId ?? "unknown";
    const chatId = context?.chatId ?? "unknown";
    const fieldName = context?.fieldName ?? "unknown";
    // Embed decryption can fail transiently during the chat-key race window
    // (key not yet in cache → wrong key used, or embed stored without key wrapper).
    // The renderer's _decryptionFailed recovery path re-requests from the server,
    // so this is a warning, not an error.
    console.warn(
      `[CryptoService] Embed decryption failed: embed_id=${embedId} chat_id=${chatId} field=${fieldName}`,
      error,
    );
    return null;
  }
}

/** Unwraps a child embed key using a parent embed key (for shared embed access) */
export async function unwrapEmbedKeyWithEmbedKey(
  wrappedEmbedKey: string,
  parentEmbedKey: Uint8Array,
): Promise<Uint8Array | null> {
  try {
    const parentEmbedKeyBuffer = new Uint8Array(parentEmbedKey);
    const cryptoKey = await crypto.subtle.importKey(
      "raw",
      parentEmbedKeyBuffer,
      { name: "AES-GCM" },
      false,
      ["decrypt"],
    );

    const combined = base64ToUint8Array(wrappedEmbedKey);
    const iv = combined.slice(0, AES_IV_LENGTH);
    const ciphertext = combined.slice(AES_IV_LENGTH);

    const decrypted = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv },
      cryptoKey,
      ciphertext,
    );

    console.debug(
      "[CryptoService] Successfully unwrapped child embed key with parent embed key, length:",
      decrypted.byteLength,
    );
    return new Uint8Array(decrypted);
  } catch (error) {
    console.warn(
      "[CryptoService] Failed to unwrap child embed key with parent embed key:",
      error,
    );
    return null;
  }
}
