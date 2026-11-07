/**
 * Cryptographic service for OpenMates (Web Crypto API Implementation)
 *
 * This service handles:
 * - Master key generation and storage (extractable CryptoKey in IndexedDB)
 * - Email encryption key generation and storage (for server use only)
 * - Email encryption with master key (for client storage)
 * - General-purpose encryption/decryption using master key
 * - Key wrapping for server storage
 *
 * Security Architecture:
 * - Master key: Generated as extractable CryptoKey, stored in IndexedDB
 *   (Extractable keys allow wrapping for recovery keys while still using Web Crypto API)
 * - Email encryption key: SHA256(email + user_email_salt), stored temporarily in sessionStorage
 * - Email storage: Encrypted with master key on client, encrypted with email encryption key on server
 * - Encryption: AES-GCM 256-bit with random IVs
 * - Key Derivation: PBKDF2 with 100,000 iterations
 *
 * Web Crypto API Benefits:
 * - Keys stored in IndexedDB (better isolation than localStorage/sessionStorage)
 * - Browser-native cryptography (faster and more secure)
 * - Hardware-backed operations when available
 * - Keys require Web Crypto API to use (not plain Base64 strings in storage)
 */

import {
  saveMasterKey,
  getMasterKey,
  clearMasterKey,
  clearMasterKeyFromIndexedDB,
  deleteCryptoDatabase,
} from "./cryptoKeyStorage";
import {
  encryptWithMasterKey,
  decryptWithMasterKey,
} from "./encryption/MetadataEncryptor";
import { requireSubtleCrypto } from "./authKeyDerivation";

export { UnsupportedClientCryptoError } from "./authKeyDerivation";

// Email encryption key storage constants (for server communication)
const EMAIL_ENCRYPTION_KEY = "openmates_email_encryption_key";

// Email salt storage constant
const EMAIL_SALT_KEY = "openmates_email_salt";

// Email storage constants (encrypted with master key for client use)
const EMAIL_ENCRYPTED_WITH_MASTER_KEY = "openmates_email_encrypted_master";

// Constants for AES-GCM
const AES_KEY_LENGTH = 256; // 256-bit keys
const AES_IV_LENGTH = 12; // 12 bytes for GCM mode

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

/**
 * Converts Uint8Array to Base64 string
 */
export function uint8ArrayToBase64(bytes: Uint8Array): string {
  let binary = "";
  const len = bytes.byteLength;
  for (let i = 0; i < len; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return window.btoa(binary);
}

/**
 * Converts Uint8Array to URL-safe Base64 string (no padding)
 */
function _uint8ArrayToUrlSafeBase64(bytes: Uint8Array): string {
  const base64 = uint8ArrayToBase64(bytes);
  return base64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/**
 * Converts Base64 string to Uint8Array
 * Handles both standard base64 and URL-safe base64 (with - and _)
 */
export function base64ToUint8Array(base64: string): Uint8Array {
  if (!base64 || typeof base64 !== "string") {
    throw new Error("Invalid base64 string: must be a non-empty string");
  }

  // Convert URL-safe base64 to standard base64 if needed
  let standardBase64 = base64.replace(/-/g, "+").replace(/_/g, "/");

  // Add padding if needed (base64 strings must be multiple of 4)
  const missingPadding = standardBase64.length % 4;
  if (missingPadding) {
    standardBase64 += "=".repeat(4 - missingPadding);
  }

  try {
    const binary_string = window.atob(standardBase64);
    const len = binary_string.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i++) {
      bytes[i] = binary_string.charCodeAt(i);
    }
    return bytes;
  } catch (error) {
    throw new Error(
      `Invalid base64 string: ${error instanceof Error ? error.message : String(error)}`,
    );
  }
}

/**
 * Generates a cryptographically secure random salt
 */
export function generateSalt(length = 16): Uint8Array {
  return crypto.getRandomValues(new Uint8Array(length));
}

// ============================================================================
// MASTER KEY GENERATION AND STORAGE
// ============================================================================

/**
 * Generates a new master encryption key as a non-extractable CryptoKey
 * This key is used for all user data encryption and is stored in IndexedDB
 * @returns Promise<CryptoKey> - Non-extractable AES-GCM key
 */
async function _generateUserMasterKey(): Promise<CryptoKey> {
  return await crypto.subtle.generateKey(
    { name: "AES-GCM", length: AES_KEY_LENGTH },
    false, // non-extractable - cannot be exported as raw bytes
    ["encrypt", "decrypt"],
  );
}

/**
 * Generates an extractable master key for wrapping/server sync
 * Used during signup to create a key that can be wrapped for server storage
 * @returns Promise<CryptoKey> - Extractable AES-GCM key
 */
export async function generateExtractableMasterKey(): Promise<CryptoKey> {
  return await crypto.subtle.generateKey(
    { name: "AES-GCM", length: AES_KEY_LENGTH },
    true, // extractable - can be exported for wrapping
    ["encrypt", "decrypt"],
  );
}

/**
 * Saves a CryptoKey with stayLoggedIn preference
 *
 * Hybrid Storage Strategy:
 * - stayLoggedIn=false: Key stored in memory only (automatically cleared on page close)
 * - stayLoggedIn=true: Key stored in IndexedDB (persists across sessions)
 *
 * This approach ensures keys don't persist when user doesn't want to stay logged in,
 * without relying on unreliable unload handlers. Memory keys are automatically cleared
 * when the page closes, providing reliable cleanup.
 *
 * @param key - The CryptoKey to store
 * @param stayLoggedIn - If false, key stored in memory only; if true, persisted to IndexedDB (default: true for backward compatibility)
 */
export async function saveKeyToSession(
  key: CryptoKey,
  stayLoggedIn: boolean = true,
): Promise<void> {
  await saveMasterKey(key, stayLoggedIn);

  // Set up unload handler for defense in depth (only needed for IndexedDB case)
  // Memory keys auto-clear, but we still validate IndexedDB on unload
  if (typeof window !== "undefined") {
    setupMasterKeyUnloadHandler();
    // Start periodic validation for extra safety
    startMasterKeyValidation();
  }
}

/**
 * Sets up a page unload handler to validate IndexedDB storage
 * This is defense in depth - memory keys auto-clear, but we validate IndexedDB on unload
 *
 * This function is idempotent - it can be called multiple times safely.
 */
let unloadHandlerSetup = false;
export function setupMasterKeyUnloadHandler(): void {
  if (typeof window === "undefined" || unloadHandlerSetup) {
    return;
  }

  unloadHandlerSetup = true;

  /**
   * Validate IndexedDB on page unload if stayLoggedIn was false
   * Uses visibilitychange and pagehide events for better reliability
   * Note: This is defense in depth - memory keys auto-clear, but we validate IndexedDB
   */
  const handlePageUnload = () => {
    const shouldClear =
      sessionStorage.getItem("clear_master_key_on_unload") === "true";
    if (shouldClear) {
      console.debug(
        "[cryptoService] Validating IndexedDB on page unload (stayLoggedIn was false)",
      );
      // Use non-blocking approach - initiate deletion (may not complete if page closes immediately)
      // This is OK because memory keys already auto-cleared, and page load check will handle it
      clearMasterKeyFromIndexedDB()
        .then(() => {
          sessionStorage.removeItem("clear_master_key_on_unload");
          console.debug(
            "[cryptoService] IndexedDB validated and cleared on page unload",
          );
        })
        .catch((_error) => {
          // Ignore errors - page load check will handle cleanup
          console.debug(
            "[cryptoService] IndexedDB validation on unload incomplete (will be handled on next page load)",
          );
        });
    }
  };

  // Use visibilitychange to detect when page becomes hidden (more reliable than beforeunload)
  // This fires when tab is switched, minimized, or closed
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      handlePageUnload();
    }
  });

  // Use pagehide for better mobile browser support (fires on tab close, browser close, navigation)
  window.addEventListener("pagehide", handlePageUnload);

  // Also use beforeunload as fallback for desktop browsers
  window.addEventListener("beforeunload", handlePageUnload);

  console.debug(
    "[cryptoService] Master key unload handler set up (defense in depth)",
  );
}

/**
 * Periodic validation to ensure IndexedDB is cleared if stayLoggedIn was false
 * This provides extra safety in case unload handlers don't complete
 *
 * Checks every 5 minutes if IndexedDB key should be cleared based on the flag
 */
let validationInterval: ReturnType<typeof setInterval> | null = null;

export function startMasterKeyValidation(): void {
  if (validationInterval || typeof window === "undefined") {
    return;
  }

  // Check every 5 minutes if IndexedDB key should be cleared
  validationInterval = setInterval(
    async () => {
      const shouldClear =
        sessionStorage.getItem("clear_master_key_on_unload") === "true";
      if (shouldClear) {
        try {
          await clearMasterKeyFromIndexedDB();
          console.debug(
            "[cryptoService] Periodic validation: Cleared IndexedDB key (stayLoggedIn was false)",
          );
        } catch (_error) {
          // Ignore errors - might already be cleared
          console.debug(
            "[cryptoService] Periodic validation: IndexedDB already cleared or error (ignored)",
          );
        }
      }
    },
    5 * 60 * 1000,
  ); // 5 minutes

  console.debug(
    "[cryptoService] Master key periodic validation started (every 5 minutes)",
  );
}

export function stopMasterKeyValidation(): void {
  if (validationInterval) {
    clearInterval(validationInterval);
    validationInterval = null;
    console.debug("[cryptoService] Master key periodic validation stopped");
  }
}

/**
 * Checks on page load if the master key should be cleared (if stayLoggedIn was false)
 * This handles cases where the page was reloaded or navigated away while stayLoggedIn was false
 *
 * Note: This is defense in depth - getMasterKey() also validates on every access,
 * but this explicit check on page load ensures cleanup happens early.
 *
 * This should be called early in the app initialization (e.g., in +page.svelte onMount)
 */
export async function checkAndClearMasterKeyOnLoad(): Promise<void> {
  if (typeof window === "undefined") {
    return;
  }

  const shouldClear =
    sessionStorage.getItem("clear_master_key_on_unload") === "true";
  if (shouldClear) {
    console.debug(
      "[cryptoService] stayLoggedIn was false - clearing master key on page load",
    );
    try {
      // Clear from both memory and IndexedDB (comprehensive cleanup)
      await clearMasterKey();
      console.debug(
        "[cryptoService] Master key cleared successfully on page load",
      );
    } catch (error) {
      console.error(
        "[cryptoService] Error clearing master key on page load:",
        error,
      );
    }
  }
}

/**
 * Gets the master CryptoKey from memory (if stayLoggedIn=false) or IndexedDB (if stayLoggedIn=true)
 * Also validates that IndexedDB key should exist based on stayLoggedIn flag
 *
 * @returns Promise<CryptoKey | null> - The master key or null if not found
 */
export async function getKeyFromStorage(): Promise<CryptoKey | null> {
  return await getMasterKey();
}

/**
 * Clears the master key from both memory and IndexedDB
 * Also stops periodic validation since key is being cleared
 */
export async function clearKeyFromStorage(): Promise<void> {
  stopMasterKeyValidation();
  await clearMasterKey();
}

/**
 * Deletes the entire crypto database (used during logout)
 */
async function _deleteCryptoStorage(): Promise<void> {
  await deleteCryptoDatabase();
}

// Legacy compatibility functions (deprecated, use async versions)
export function getKeyFromSession(): null {
  console.warn(
    "getKeyFromSession is deprecated, use getKeyFromStorage() instead",
  );
  return null;
}

export function clearKeyFromSession(): void {
  console.warn(
    "clearKeyFromSession is deprecated, use clearKeyFromStorage() instead",
  );
  clearKeyFromStorage();
}

// ============================================================================
// KEY DERIVATION AND WRAPPING
// ============================================================================

/**
 * Wraps (encrypts) a master key with a password-derived key for server storage
 * Uses Web Crypto API wrapKey() for secure key wrapping
 * @param masterKey - The master CryptoKey to wrap
 * @param wrappingKeyBytes - Password-derived key bytes
 * @returns Promise<{wrapped: string, iv: string}> - Base64 encoded wrapped key and IV
 */
export async function encryptKey(
  masterKey: CryptoKey,
  wrappingKeyBytes: Uint8Array,
): Promise<{ wrapped: string; iv: string }> {
  // Import the wrapping key bytes as a CryptoKey
  // Ensure wrappingKeyBytes is a proper BufferSource
  const wrappingKeyBuffer = new Uint8Array(wrappingKeyBytes);
  const wrappingKey = await crypto.subtle.importKey(
    "raw",
    wrappingKeyBuffer,
    { name: "AES-GCM" },
    false,
    ["wrapKey"],
  );

  // Generate random IV
  const iv = crypto.getRandomValues(new Uint8Array(AES_IV_LENGTH));

  // Wrap the master key
  const wrappedKey = await crypto.subtle.wrapKey(
    "raw",
    masterKey,
    wrappingKey,
    { name: "AES-GCM", iv },
  );

  return {
    wrapped: uint8ArrayToBase64(new Uint8Array(wrappedKey)),
    iv: uint8ArrayToBase64(iv),
  };
}

/**
 * Decrypts a wrapped master key and imports it as extractable
 * Extractable keys are needed for recovery key creation (wrapping with recovery key)
 * @param wrappedKeyBase64 - Base64 encoded wrapped key
 * @param iv - Base64 encoded IV
 * @param wrappingKeyBytes - Password-derived key bytes
 * @returns Promise<CryptoKey | null> - Unwrapped extractable CryptoKey
 */
export async function decryptKey(
  wrappedKeyBase64: string,
  iv: string,
  wrappingKeyBytes: Uint8Array,
): Promise<CryptoKey | null> {
  try {
    // Import the unwrapping key bytes as a CryptoKey
    // Ensure wrappingKeyBytes is a proper BufferSource
    const unwrappingKeyBuffer = new Uint8Array(wrappingKeyBytes);
    const unwrappingKey = await crypto.subtle.importKey(
      "raw",
      unwrappingKeyBuffer,
      { name: "AES-GCM" },
      false,
      ["decrypt"],
    );

    // AES-GCM wrapKey("raw", ...) is equivalent to encrypting the raw key bytes.
    // Safari can leave unwrapKey() unresolved after passkey login, so decrypt the
    // raw bytes explicitly and import them instead.
    // Extractable keys allow wrapping for recovery keys while still using Web Crypto API
    // XSS can use keys anyway if they have access, so extractability is a marginal security trade-off
    // Ensure wrapped key and IV are proper BufferSource
    const wrappedKeyBuffer = new Uint8Array(
      base64ToUint8Array(wrappedKeyBase64),
    );
    const ivBuffer = new Uint8Array(base64ToUint8Array(iv));
    const rawMasterKey = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: ivBuffer },
      unwrappingKey,
      wrappedKeyBuffer,
    );
    const masterKey = await crypto.subtle.importKey(
      "raw",
      rawMasterKey,
      { name: "AES-GCM" },
      true, // extractable - needed for recovery key wrapping
      ["encrypt", "decrypt"],
    );

    return masterKey;
  } catch (error) {
    console.error("Failed to unwrap key:", error);
    return null;
  }
}

// ============================================================================
// GENERAL-PURPOSE ENCRYPTION/DECRYPTION USING MASTER KEY
// (Implementation moved to encryption/MetadataEncryptor.ts — see re-exports below)
// ============================================================================

// ============================================================================
// EMAIL ENCRYPTION KEY MANAGEMENT (FOR SERVER COMMUNICATION)
// ============================================================================

/**
 * Generates a random salt for email encryption
 * @returns Uint8Array - Random salt
 */
export function generateEmailSalt(): Uint8Array {
  return generateSalt(16);
}

/**
 * Derives an encryption key from email and salt using SHA-256
 * @param email - The email address
 * @param salt - The salt
 * @returns Promise<Uint8Array> - The derived key
 */
export async function deriveEmailEncryptionKey(
  email: string,
  salt: Uint8Array,
): Promise<Uint8Array> {
  const subtle = requireSubtleCrypto("Email key derivation");
  const encoder = new TextEncoder();
  const emailBytes = encoder.encode(email);

  const combined = new Uint8Array(emailBytes.length + salt.length);
  combined.set(emailBytes);
  combined.set(salt, emailBytes.length);

  const hashBuffer = await subtle.digest("SHA-256", combined);
  return new Uint8Array(hashBuffer);
}

/**
 * Encrypts an email address using the derived key (TweetNaCl XSalsa20-Poly1305)
 * Note: Uses TweetNaCl format to match backend expectations (PyNaCl compatible)
 * @param email - The email address to encrypt
 * @param key - The encryption key (32 bytes for XSalsa20)
 * @returns Promise<string> - Base64 encoded encrypted email with nonce (24 bytes + ciphertext)
 */
export async function encryptEmail(
  email: string,
  key: Uint8Array,
): Promise<string> {
  // Dynamic import to avoid bundling issues if tweetnacl isn't always needed
  const nacl = await import("tweetnacl");

  // Ensure key is exactly 32 bytes for TweetNaCl SecretBox
  if (key.length !== 32) {
    throw new Error(
      `Email encryption key must be 32 bytes, got ${key.length} bytes`,
    );
  }

  // Convert email to Uint8Array
  const encoder = new TextEncoder();
  const emailBytes = encoder.encode(email);

  // Generate random 24-byte nonce
  const nonce = nacl.randomBytes(24);

  // Encrypt using SecretBox (XSalsa20-Poly1305)
  // secretbox(message, nonce, key) returns ciphertext only (doesn't include nonce)
  const ciphertext = nacl.secretbox(emailBytes, nonce, key);

  // Combine nonce (24 bytes) + ciphertext
  // Format: nonce || ciphertext (matching backend PyNaCl expectations)
  const combined = new Uint8Array(24 + ciphertext.length);
  combined.set(nonce);
  combined.set(ciphertext, 24);

  return uint8ArrayToBase64(combined);
}

/**
 * Decrypts an encrypted email address (TweetNaCl XSalsa20-Poly1305)
 * Note: Uses TweetNaCl format to match backend expectations (PyNaCl compatible)
 * @param encryptedEmailWithNonce - Base64 encoded encrypted email with nonce (24 bytes + ciphertext)
 * @param key - The decryption key (32 bytes for XSalsa20)
 * @returns Promise<string | null> - Decrypted email or null if decryption fails
 */
async function _decryptEmail(
  encryptedEmailWithNonce: string,
  key: Uint8Array,
): Promise<string | null> {
  try {
    // Dynamic import to avoid bundling issues
    const nacl = await import("tweetnacl");

    // Ensure key is exactly 32 bytes for TweetNaCl SecretBox
    if (key.length !== 32) {
      console.error(
        `Email decryption key must be 32 bytes, got ${key.length} bytes`,
      );
      return null;
    }

    const combined = base64ToUint8Array(encryptedEmailWithNonce);

    // Extract nonce (first 24 bytes) and ciphertext (rest)
    const NACL_NONCE_SIZE = 24;
    if (combined.length <= NACL_NONCE_SIZE) {
      console.error(
        `Invalid encrypted email format. Too short: ${combined.length} bytes`,
      );
      return null;
    }

    const nonce = combined.slice(0, NACL_NONCE_SIZE);
    const ciphertext = combined.slice(NACL_NONCE_SIZE);

    // Decrypt using SecretBox (XSalsa20-Poly1305)
    const decrypted = nacl.secretbox.open(ciphertext, nonce, key);

    if (!decrypted) {
      console.error("Email decryption failed - invalid key or corrupted data");
      return null;
    }

    const decoder = new TextDecoder();
    return decoder.decode(decrypted);
  } catch (error) {
    console.error("Email decryption failed:", error);
    return null;
  }
}

/**
 * Creates a SHA-256 hash of an email for lookup purposes
 * @param email - The email address to hash
 * @returns Promise<string> - Base64 encoded hash
 */
export async function hashEmail(email: string): Promise<string> {
  const encoder = new TextEncoder();
  const emailBytes = encoder.encode(email);

  const hashBuffer = await crypto.subtle.digest("SHA-256", emailBytes);
  const hashArray = new Uint8Array(hashBuffer);

  return uint8ArrayToBase64(hashArray);
}

/**
 * Stores the email encryption key in sessionStorage or localStorage based on user preference
 * @param emailEncryptionKey - The email encryption key
 * @param useLocalStorage - If true, stores in localStorage (for "Stay logged in"), otherwise sessionStorage
 */
export function saveEmailEncryptionKey(
  emailEncryptionKey: Uint8Array,
  useLocalStorage: boolean = false,
): void {
  if (typeof window !== "undefined") {
    const keyBase64 = uint8ArrayToBase64(emailEncryptionKey);
    // Clear from the other storage type to avoid conflicts
    if (useLocalStorage) {
      sessionStorage.removeItem(EMAIL_ENCRYPTION_KEY);
      localStorage.setItem(EMAIL_ENCRYPTION_KEY, keyBase64);
    } else {
      localStorage.removeItem(EMAIL_ENCRYPTION_KEY);
      sessionStorage.setItem(EMAIL_ENCRYPTION_KEY, keyBase64);
    }
  }
}

/**
 * Retrieves the email encryption key from sessionStorage or localStorage
 * Checks both storages to handle cases where user preference changed
 * @returns Uint8Array | null - The email encryption key or null if not found
 */
export function getEmailEncryptionKey(): Uint8Array | null {
  if (typeof window !== "undefined") {
    // Check sessionStorage first (for backward compatibility), then localStorage
    let keyBase64 = sessionStorage.getItem(EMAIL_ENCRYPTION_KEY);
    if (!keyBase64) {
      keyBase64 = localStorage.getItem(EMAIL_ENCRYPTION_KEY);
    }
    if (keyBase64) {
      return base64ToUint8Array(keyBase64);
    }
  }
  return null;
}

/**
 * Gets the email encryption key as base64 for API use
 * @returns string | null - Base64 encoded email encryption key or null if not found
 */
export function getEmailEncryptionKeyForApi(): string | null {
  const key = getEmailEncryptionKey();
  return key ? uint8ArrayToBase64(key) : null;
}

/**
 * Clears the email encryption key from both sessionStorage and localStorage
 */
export function clearEmailEncryptionKey(): void {
  if (typeof window !== "undefined") {
    sessionStorage.removeItem(EMAIL_ENCRYPTION_KEY);
    localStorage.removeItem(EMAIL_ENCRYPTION_KEY);
  }
}

// ============================================================================
// EMAIL STORAGE (ENCRYPTED WITH MASTER KEY FOR CLIENT USE)
// ============================================================================

/**
 * Stores the email encrypted with the master key
 * @param email - The plaintext email
 * @param useLocalStorage - If true, stores in localStorage (for "Stay logged in"), otherwise sessionStorage
 * @returns Promise<boolean> - True if successful, false if master key not available
 */
export async function saveEmailEncryptedWithMasterKey(
  email: string,
  useLocalStorage: boolean = false,
): Promise<boolean> {
  const encryptedEmail = await encryptWithMasterKey(email);
  if (!encryptedEmail) {
    return false;
  }

  if (typeof window !== "undefined") {
    // Clear from the other storage type to avoid conflicts
    if (useLocalStorage) {
      sessionStorage.removeItem(EMAIL_ENCRYPTED_WITH_MASTER_KEY);
      localStorage.setItem(EMAIL_ENCRYPTED_WITH_MASTER_KEY, encryptedEmail);
    } else {
      localStorage.removeItem(EMAIL_ENCRYPTED_WITH_MASTER_KEY);
      sessionStorage.setItem(EMAIL_ENCRYPTED_WITH_MASTER_KEY, encryptedEmail);
    }
  }

  return true;
}

/**
 * Gets the plaintext email by decrypting it with the master key
 * Checks both sessionStorage and localStorage to support "Stay logged in" functionality
 * @returns Promise<string | null> - Decrypted email or null if not found or decryption fails
 */
export async function getEmailDecryptedWithMasterKey(): Promise<string | null> {
  if (typeof window !== "undefined") {
    // Check sessionStorage first (for regular sessions)
    let encryptedEmail = sessionStorage.getItem(
      EMAIL_ENCRYPTED_WITH_MASTER_KEY,
    );

    // If not found in sessionStorage, check localStorage (for "Stay logged in" sessions)
    if (!encryptedEmail) {
      encryptedEmail = localStorage.getItem(EMAIL_ENCRYPTED_WITH_MASTER_KEY);
    }

    if (encryptedEmail) {
      return await decryptWithMasterKey(encryptedEmail);
    }
  }
  return null;
}

/**
 * Clears the encrypted email from storage (both sessionStorage and localStorage)
 */
export function clearEmailEncryptedWithMasterKey(): void {
  if (typeof window !== "undefined") {
    sessionStorage.removeItem(EMAIL_ENCRYPTED_WITH_MASTER_KEY);
    localStorage.removeItem(EMAIL_ENCRYPTED_WITH_MASTER_KEY);
  }
}

/**
 * Clears all email-related data from storage
 */
export function clearAllEmailData(): void {
  clearEmailEncryptionKey();
  clearEmailEncryptedWithMasterKey();
  clearEmailSalt();
  // Clear pair login credentials stored during password login (used by SettingsSessionsConfirmPair)
  if (typeof window !== "undefined") {
    sessionStorage.removeItem("openmates_pair_lookup_hash");
    sessionStorage.removeItem("openmates_pair_encrypted_key");
    sessionStorage.removeItem("openmates_pair_salt");
  }
}

// ============================================================================
// EMAIL SALT MANAGEMENT
// ============================================================================

/**
 * Stores the email salt in sessionStorage or localStorage based on user preference
 * @param emailSalt - The email salt
 * @param useLocalStorage - If true, stores in localStorage (for "Stay logged in"), otherwise sessionStorage
 */
export function saveEmailSalt(
  emailSalt: Uint8Array,
  useLocalStorage: boolean = false,
): void {
  if (typeof window !== "undefined") {
    const saltBase64 = uint8ArrayToBase64(emailSalt);
    // Clear from the other storage type to avoid conflicts
    if (useLocalStorage) {
      sessionStorage.removeItem(EMAIL_SALT_KEY);
      localStorage.setItem(EMAIL_SALT_KEY, saltBase64);
    } else {
      localStorage.removeItem(EMAIL_SALT_KEY);
      sessionStorage.setItem(EMAIL_SALT_KEY, saltBase64);
    }
  }
}

/**
 * Retrieves the email salt from sessionStorage or localStorage
 * Checks both storages to handle cases where user preference changed
 * @returns Uint8Array | null - The email salt or null if not found
 */
export function getEmailSalt(): Uint8Array | null {
  if (typeof window !== "undefined") {
    // Check sessionStorage first (for backward compatibility), then localStorage
    let saltBase64 = sessionStorage.getItem(EMAIL_SALT_KEY);
    if (!saltBase64) {
      saltBase64 = localStorage.getItem(EMAIL_SALT_KEY);
    }
    if (saltBase64) {
      return base64ToUint8Array(saltBase64);
    }
  }
  return null;
}

/**
 * Clears the email salt from both sessionStorage and localStorage
 */
export function clearEmailSalt(): void {
  if (typeof window !== "undefined") {
    sessionStorage.removeItem(EMAIL_SALT_KEY);
    localStorage.removeItem(EMAIL_SALT_KEY);
  }
}

// ============================================================================
// RE-EXPORTS: Message encryption (implementation in encryption/MessageEncryptor.ts)
// These re-exports preserve the 30+ dynamic import("./cryptoService") call sites
// across sync handlers, export services, and debug utilities.
// ============================================================================
export {
  encryptWithChatKey,
  decryptWithChatKey,
  encryptArrayWithChatKey,
  decryptArrayWithChatKey,
  computeKeyFingerprint4Bytes,
  clearCryptoKeyCache,
  _generateChatKeyInternal,
  generateChatKey,
} from "./encryption/MessageEncryptor";

// ============================================================================
// RE-EXPORTS: Metadata encryption (implementation in encryption/MetadataEncryptor.ts)
// ============================================================================
export {
  encryptWithMasterKey,
  decryptWithMasterKey,
  encryptWithMasterKeyDirect,
  encryptChatKeyWithMasterKey,
  decryptChatKeyWithMasterKey,
  generateEmbedKey,
  deriveEmbedKeyFromChatKey,
  wrapEmbedKeyWithMasterKey,
  unwrapEmbedKeyWithMasterKey,
  wrapEmbedKeyWithChatKey,
  unwrapEmbedKeyWithChatKey,
  encryptWithEmbedKey,
  decryptWithEmbedKey,
  unwrapEmbedKeyWithEmbedKey,
} from "./encryption/MetadataEncryptor";

// ============================================================================
// RE-EXPORTS: key derivation, recovery key and passkey PRF
// (implementation in authKeyDerivation.ts)
// ============================================================================
export {
  deriveKeyFromPassword,
  deriveKeyFromApiKey,
  generateSecureRecoveryKey,
  hashKey,
  getPRFSignatureForPasskeyRegistration,
  hkdf,
  deriveWrappingKeyFromPRF,
  hashKeyFromPRF,
} from "./authKeyDerivation";
