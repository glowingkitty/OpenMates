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
  saveMasterKeyToIndexedDB,
  getMasterKeyFromIndexedDB,
  clearMasterKeyFromIndexedDB,
  deleteCryptoDatabase
} from './cryptoKeyStorage';

// Email encryption key storage constants (for server communication)
const EMAIL_ENCRYPTION_KEY = 'openmates_email_encryption_key';

// Email salt storage constant
const EMAIL_SALT_KEY = 'openmates_email_salt';

// Email storage constants (encrypted with master key for client use)
const EMAIL_ENCRYPTED_WITH_MASTER_KEY = 'openmates_email_encrypted_master';

// Constants for AES-GCM
const AES_KEY_LENGTH = 256; // 256-bit keys
const AES_IV_LENGTH = 12; // 12 bytes for GCM mode
const PBKDF2_ITERATIONS = 100000;

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

/**
 * Converts Uint8Array to Base64 string
 */
export function uint8ArrayToBase64(bytes: Uint8Array): string {
  let binary = '';
  const len = bytes.byteLength;
  for (let i = 0; i < len; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return window.btoa(binary);
}

/**
 * Converts Base64 string to Uint8Array
 * Handles both standard base64 and URL-safe base64 (with - and _)
 */
export function base64ToUint8Array(base64: string): Uint8Array {
  if (!base64 || typeof base64 !== 'string') {
    throw new Error('Invalid base64 string: must be a non-empty string');
  }
  
  // Convert URL-safe base64 to standard base64 if needed
  let standardBase64 = base64.replace(/-/g, '+').replace(/_/g, '/');
  
  // Add padding if needed (base64 strings must be multiple of 4)
  const missingPadding = standardBase64.length % 4;
  if (missingPadding) {
    standardBase64 += '='.repeat(4 - missingPadding);
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
    throw new Error(`Invalid base64 string: ${error instanceof Error ? error.message : String(error)}`);
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
export async function generateUserMasterKey(): Promise<CryptoKey> {
  return await crypto.subtle.generateKey(
    { name: 'AES-GCM', length: AES_KEY_LENGTH },
    false, // non-extractable - cannot be exported as raw bytes
    ['encrypt', 'decrypt']
  );
}

/**
 * Generates an extractable master key for wrapping/server sync
 * Used during signup to create a key that can be wrapped for server storage
 * @returns Promise<CryptoKey> - Extractable AES-GCM key
 */
export async function generateExtractableMasterKey(): Promise<CryptoKey> {
  return await crypto.subtle.generateKey(
    { name: 'AES-GCM', length: AES_KEY_LENGTH },
    true, // extractable - can be exported for wrapping
    ['encrypt', 'decrypt']
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
export async function saveKeyToSession(key: CryptoKey, stayLoggedIn: boolean = true): Promise<void> {
  await saveMasterKey(key, stayLoggedIn);
  
  // Set up unload handler for defense in depth (only needed for IndexedDB case)
  // Memory keys auto-clear, but we still validate IndexedDB on unload
  if (typeof window !== 'undefined') {
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
  if (typeof window === 'undefined' || unloadHandlerSetup) {
    return;
  }
  
  unloadHandlerSetup = true;
  
  /**
   * Validate IndexedDB on page unload if stayLoggedIn was false
   * Uses visibilitychange and pagehide events for better reliability
   * Note: This is defense in depth - memory keys auto-clear, but we validate IndexedDB
   */
  const handlePageUnload = () => {
    const shouldClear = sessionStorage.getItem('clear_master_key_on_unload') === 'true';
    if (shouldClear) {
      console.debug('[cryptoService] Validating IndexedDB on page unload (stayLoggedIn was false)');
      // Use non-blocking approach - initiate deletion (may not complete if page closes immediately)
      // This is OK because memory keys already auto-cleared, and page load check will handle it
      clearMasterKeyFromIndexedDB().then(() => {
        sessionStorage.removeItem('clear_master_key_on_unload');
        console.debug('[cryptoService] IndexedDB validated and cleared on page unload');
      }).catch((error) => {
        // Ignore errors - page load check will handle cleanup
        console.debug('[cryptoService] IndexedDB validation on unload incomplete (will be handled on next page load)');
      });
    }
  };
  
  // Use visibilitychange to detect when page becomes hidden (more reliable than beforeunload)
  // This fires when tab is switched, minimized, or closed
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') {
      handlePageUnload();
    }
  });
  
  // Use pagehide for better mobile browser support (fires on tab close, browser close, navigation)
  window.addEventListener('pagehide', handlePageUnload);
  
  // Also use beforeunload as fallback for desktop browsers
  window.addEventListener('beforeunload', handlePageUnload);
  
  console.debug('[cryptoService] Master key unload handler set up (defense in depth)');
}

/**
 * Periodic validation to ensure IndexedDB is cleared if stayLoggedIn was false
 * This provides extra safety in case unload handlers don't complete
 * 
 * Checks every 5 minutes if IndexedDB key should be cleared based on the flag
 */
let validationInterval: ReturnType<typeof setInterval> | null = null;

export function startMasterKeyValidation(): void {
  if (validationInterval || typeof window === 'undefined') {
    return;
  }
  
  // Check every 5 minutes if IndexedDB key should be cleared
  validationInterval = setInterval(async () => {
    const shouldClear = sessionStorage.getItem('clear_master_key_on_unload') === 'true';
    if (shouldClear) {
      try {
        await clearMasterKeyFromIndexedDB();
        console.debug('[cryptoService] Periodic validation: Cleared IndexedDB key (stayLoggedIn was false)');
      } catch (error) {
        // Ignore errors - might already be cleared
        console.debug('[cryptoService] Periodic validation: IndexedDB already cleared or error (ignored)');
      }
    }
  }, 5 * 60 * 1000); // 5 minutes
  
  console.debug('[cryptoService] Master key periodic validation started (every 5 minutes)');
}

export function stopMasterKeyValidation(): void {
  if (validationInterval) {
    clearInterval(validationInterval);
    validationInterval = null;
    console.debug('[cryptoService] Master key periodic validation stopped');
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
  if (typeof window === 'undefined') {
    return;
  }
  
  const shouldClear = sessionStorage.getItem('clear_master_key_on_unload') === 'true';
  if (shouldClear) {
    console.debug('[cryptoService] stayLoggedIn was false - clearing master key on page load');
    try {
      // Clear from both memory and IndexedDB (comprehensive cleanup)
      await clearMasterKey();
      console.debug('[cryptoService] Master key cleared successfully on page load');
    } catch (error) {
      console.error('[cryptoService] Error clearing master key on page load:', error);
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
export async function deleteCryptoStorage(): Promise<void> {
  await deleteCryptoDatabase();
}

// Legacy compatibility functions (deprecated, use async versions)
export function getKeyFromSession(): null {
  console.warn('getKeyFromSession is deprecated, use getKeyFromStorage() instead');
  return null;
}

export function clearKeyFromSession(): void {
  console.warn('clearKeyFromSession is deprecated, use clearKeyFromStorage() instead');
  clearKeyFromStorage();
}

// ============================================================================
// KEY DERIVATION AND WRAPPING
// ============================================================================

/**
 * Derives a key from a password using PBKDF2
 * @param password - The password string
 * @param salt - Salt bytes
 * @returns Promise<Uint8Array> - Derived key bytes
 */
export async function deriveKeyFromPassword(password: string, salt: Uint8Array): Promise<Uint8Array> {
  if (typeof window !== 'undefined') {
    const encoder = new TextEncoder();
    const keyMaterial = await crypto.subtle.importKey(
      'raw',
      encoder.encode(password),
      'PBKDF2',
      false,
      ['deriveKey', 'deriveBits']
    );

    // Ensure salt is a proper BufferSource
    const saltBuffer = new Uint8Array(salt);
    const derivedBits = await crypto.subtle.deriveBits(
      {
        name: 'PBKDF2',
        salt: saltBuffer,
        iterations: PBKDF2_ITERATIONS,
        hash: 'SHA-256'
      },
      keyMaterial,
      256
    );

    return new Uint8Array(derivedBits);
  }
  return new Uint8Array(32);
}

/**
 * Derives a key from an API key using PBKDF2 (same as password derivation)
 * Used for encrypting the master key with the API key for CLI/npm/pip access
 * @param apiKey - The API key string
 * @param salt - Random salt (should be generated per API key)
 * @returns Promise<Uint8Array> - 256-bit derived key
 */
export async function deriveKeyFromApiKey(apiKey: string, salt: Uint8Array): Promise<Uint8Array> {
  // Use the same derivation as passwords for consistency
  return deriveKeyFromPassword(apiKey, salt);
}

/**
 * Wraps (encrypts) a master key with a password-derived key for server storage
 * Uses Web Crypto API wrapKey() for secure key wrapping
 * @param masterKey - The master CryptoKey to wrap
 * @param wrappingKeyBytes - Password-derived key bytes
 * @returns Promise<{wrapped: string, iv: string}> - Base64 encoded wrapped key and IV
 */
export async function encryptKey(masterKey: CryptoKey, wrappingKeyBytes: Uint8Array): Promise<{ wrapped: string; iv: string }> {
  // Import the wrapping key bytes as a CryptoKey
  // Ensure wrappingKeyBytes is a proper BufferSource
  const wrappingKeyBuffer = new Uint8Array(wrappingKeyBytes);
  const wrappingKey = await crypto.subtle.importKey(
    'raw',
    wrappingKeyBuffer,
    { name: 'AES-GCM' },
    false,
    ['wrapKey']
  );

  // Generate random IV
  const iv = crypto.getRandomValues(new Uint8Array(AES_IV_LENGTH));

  // Wrap the master key
  const wrappedKey = await crypto.subtle.wrapKey(
    'raw',
    masterKey,
    wrappingKey,
    { name: 'AES-GCM', iv }
  );

  return {
    wrapped: uint8ArrayToBase64(new Uint8Array(wrappedKey)),
    iv: uint8ArrayToBase64(iv)
  };
}

/**
 * Unwraps (decrypts) a master key and imports it as extractable
 * Extractable keys are needed for recovery key creation (wrapping with recovery key)
 * @param wrappedKeyBase64 - Base64 encoded wrapped key
 * @param iv - Base64 encoded IV
 * @param wrappingKeyBytes - Password-derived key bytes
 * @returns Promise<CryptoKey | null> - Unwrapped extractable CryptoKey
 */
export async function decryptKey(
  wrappedKeyBase64: string,
  iv: string,
  wrappingKeyBytes: Uint8Array
): Promise<CryptoKey | null> {
  try {
    // Import the unwrapping key bytes as a CryptoKey
    // Ensure wrappingKeyBytes is a proper BufferSource
    const unwrappingKeyBuffer = new Uint8Array(wrappingKeyBytes);
    const unwrappingKey = await crypto.subtle.importKey(
      'raw',
      unwrappingKeyBuffer,
      { name: 'AES-GCM' },
      false,
      ['unwrapKey']
    );

    // Unwrap the master key as extractable
    // Extractable keys allow wrapping for recovery keys while still using Web Crypto API
    // XSS can use keys anyway if they have access, so extractability is a marginal security trade-off
    // Ensure wrapped key and IV are proper BufferSource
    const wrappedKeyBuffer = new Uint8Array(base64ToUint8Array(wrappedKeyBase64));
    const ivBuffer = new Uint8Array(base64ToUint8Array(iv));
    const masterKey = await crypto.subtle.unwrapKey(
      'raw',
      wrappedKeyBuffer,
      unwrappingKey,
      { name: 'AES-GCM', iv: ivBuffer },
      { name: 'AES-GCM' },
      true, // extractable - needed for recovery key wrapping
      ['encrypt', 'decrypt']
    );

    return masterKey;
  } catch (error) {
    console.error('Failed to unwrap key:', error);
    return null;
  }
}

// ============================================================================
// GENERAL-PURPOSE ENCRYPTION/DECRYPTION USING MASTER KEY
// ============================================================================

/**
 * Encrypts data using the master key from IndexedDB
 * @param data - The data string to encrypt
 * @returns Promise<string | null> - Base64 encoded encrypted data with IV, or null if key not found
 */
export async function encryptWithMasterKey(data: string): Promise<string | null> {
  const masterKey = await getKeyFromStorage();
  if (!masterKey) {
    console.error('Master key not found in storage');
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
export async function encryptWithMasterKeyDirect(data: string, masterKey: CryptoKey): Promise<string | null> {
  try {
    const encoder = new TextEncoder();
    const dataBytes = encoder.encode(data);
    const iv = crypto.getRandomValues(new Uint8Array(AES_IV_LENGTH));

    const encrypted = await crypto.subtle.encrypt(
      { name: 'AES-GCM', iv },
      masterKey,
      dataBytes
    );

    // Combine IV + ciphertext
    const combined = new Uint8Array(iv.length + encrypted.byteLength);
    combined.set(iv);
    combined.set(new Uint8Array(encrypted), iv.length);

    return uint8ArrayToBase64(combined);
  } catch (error) {
    console.error('Encryption failed:', error);
    return null;
  }
}

/**
 * Decrypts data using the master key from IndexedDB
 * @param encryptedDataWithIV - Base64 encoded encrypted data with IV
 * @returns Promise<string | null> - Decrypted data string, or null if decryption fails
 */
export async function decryptWithMasterKey(encryptedDataWithIV: string): Promise<string | null> {
  const masterKey = await getKeyFromStorage();
  if (!masterKey) {
    console.error('Master key not found in storage');
    return null;
  }

  try {
    const combined = base64ToUint8Array(encryptedDataWithIV);
    const iv = combined.slice(0, AES_IV_LENGTH);
    const ciphertext = combined.slice(AES_IV_LENGTH);

    const decrypted = await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv },
      masterKey,
      ciphertext
    );

    const decoder = new TextDecoder();
    return decoder.decode(decrypted);
  } catch (error) {
    console.error('Decryption failed:', error);
    return null;
  }
}

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
export async function deriveEmailEncryptionKey(email: string, salt: Uint8Array): Promise<Uint8Array> {
  if (typeof window !== 'undefined') {
    const encoder = new TextEncoder();
    const emailBytes = encoder.encode(email);

    // Combine email and salt
    const combined = new Uint8Array(emailBytes.length + salt.length);
    combined.set(emailBytes);
    combined.set(salt, emailBytes.length);

    // Hash the combined value with SHA-256
    const hashBuffer = await crypto.subtle.digest('SHA-256', combined);
    return new Uint8Array(hashBuffer);
  }
  return new Uint8Array(32);
}

/**
 * Encrypts an email address using the derived key (TweetNaCl XSalsa20-Poly1305)
 * Note: Uses TweetNaCl format to match backend expectations (PyNaCl compatible)
 * @param email - The email address to encrypt
 * @param key - The encryption key (32 bytes for XSalsa20)
 * @returns Promise<string> - Base64 encoded encrypted email with nonce (24 bytes + ciphertext)
 */
export async function encryptEmail(email: string, key: Uint8Array): Promise<string> {
  // Dynamic import to avoid bundling issues if tweetnacl isn't always needed
  const nacl = await import('tweetnacl');
  
  // Ensure key is exactly 32 bytes for TweetNaCl SecretBox
  if (key.length !== 32) {
    throw new Error(`Email encryption key must be 32 bytes, got ${key.length} bytes`);
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
export async function decryptEmail(encryptedEmailWithNonce: string, key: Uint8Array): Promise<string | null> {
  try {
    // Dynamic import to avoid bundling issues
    const nacl = await import('tweetnacl');
    
    // Ensure key is exactly 32 bytes for TweetNaCl SecretBox
    if (key.length !== 32) {
      console.error(`Email decryption key must be 32 bytes, got ${key.length} bytes`);
      return null;
    }

    const combined = base64ToUint8Array(encryptedEmailWithNonce);
    
    // Extract nonce (first 24 bytes) and ciphertext (rest)
    const NACL_NONCE_SIZE = 24;
    if (combined.length <= NACL_NONCE_SIZE) {
      console.error(`Invalid encrypted email format. Too short: ${combined.length} bytes`);
      return null;
    }
    
    const nonce = combined.slice(0, NACL_NONCE_SIZE);
    const ciphertext = combined.slice(NACL_NONCE_SIZE);

    // Decrypt using SecretBox (XSalsa20-Poly1305)
    const decrypted = nacl.secretbox.open(ciphertext, nonce, key);
    
    if (!decrypted) {
      console.error('Email decryption failed - invalid key or corrupted data');
      return null;
    }

    const decoder = new TextDecoder();
    return decoder.decode(decrypted);
  } catch (error) {
    console.error('Email decryption failed:', error);
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

  const hashBuffer = await crypto.subtle.digest('SHA-256', emailBytes);
  const hashArray = new Uint8Array(hashBuffer);

  return uint8ArrayToBase64(hashArray);
}

/**
 * Stores the email encryption key in sessionStorage or localStorage based on user preference
 * @param emailEncryptionKey - The email encryption key
 * @param useLocalStorage - If true, stores in localStorage (for "Stay logged in"), otherwise sessionStorage
 */
export function saveEmailEncryptionKey(emailEncryptionKey: Uint8Array, useLocalStorage: boolean = false): void {
  if (typeof window !== 'undefined') {
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
  if (typeof window !== 'undefined') {
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
  if (typeof window !== 'undefined') {
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
export async function saveEmailEncryptedWithMasterKey(email: string, useLocalStorage: boolean = false): Promise<boolean> {
  const encryptedEmail = await encryptWithMasterKey(email);
  if (!encryptedEmail) {
    return false;
  }

  if (typeof window !== 'undefined') {
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
  if (typeof window !== 'undefined') {
    // Check sessionStorage first (for regular sessions)
    let encryptedEmail = sessionStorage.getItem(EMAIL_ENCRYPTED_WITH_MASTER_KEY);
    
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
  if (typeof window !== 'undefined') {
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
}

// ============================================================================
// EMAIL SALT MANAGEMENT
// ============================================================================

/**
 * Stores the email salt in sessionStorage or localStorage based on user preference
 * @param emailSalt - The email salt
 * @param useLocalStorage - If true, stores in localStorage (for "Stay logged in"), otherwise sessionStorage
 */
export function saveEmailSalt(emailSalt: Uint8Array, useLocalStorage: boolean = false): void {
  if (typeof window !== 'undefined') {
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
  if (typeof window !== 'undefined') {
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
  if (typeof window !== 'undefined') {
    sessionStorage.removeItem(EMAIL_SALT_KEY);
    localStorage.removeItem(EMAIL_SALT_KEY);
  }
}

// ============================================================================
// CHAT-SPECIFIC ENCRYPTION METHODS
// ============================================================================

/**
 * Generates a chat-specific AES key (32 bytes for AES-256)
 * @returns Uint8Array - The generated chat key
 */
export function generateChatKey(): Uint8Array {
  return crypto.getRandomValues(new Uint8Array(32));
}

/**
 * Encrypts data using a chat-specific key (AES-GCM)
 * @param data - The data to encrypt
 * @param chatKey - The chat-specific encryption key
 * @returns Promise<string> - Base64 encoded encrypted data with IV
 */
export async function encryptWithChatKey(data: string, chatKey: Uint8Array): Promise<string> {
  const encoder = new TextEncoder();
  const dataBytes = encoder.encode(data);

  // Import chat key for AES-GCM
  // Ensure chatKey is a proper BufferSource
  const chatKeyBuffer = new Uint8Array(chatKey);
  const cryptoKey = await crypto.subtle.importKey(
    'raw',
    chatKeyBuffer,
    { name: 'AES-GCM' },
    false,
    ['encrypt']
  );

  const iv = crypto.getRandomValues(new Uint8Array(AES_IV_LENGTH));
  const encrypted = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv },
    cryptoKey,
    dataBytes
  );

  // Combine IV + ciphertext
  const combined = new Uint8Array(iv.length + encrypted.byteLength);
  combined.set(iv);
  combined.set(new Uint8Array(encrypted), iv.length);

  return uint8ArrayToBase64(combined);
}

/**
 * Decrypts data using a chat-specific key (AES-GCM)
 * @param encryptedDataWithIV - Base64 encoded encrypted data with IV
 * @param chatKey - The chat-specific decryption key
 * @returns Promise<string | null> - Decrypted data or null if decryption fails
 */
export async function decryptWithChatKey(encryptedDataWithIV: string, chatKey: Uint8Array): Promise<string | null> {
  try {
    const combined = base64ToUint8Array(encryptedDataWithIV);
    const iv = combined.slice(0, AES_IV_LENGTH);
    const ciphertext = combined.slice(AES_IV_LENGTH);

    // Import chat key for AES-GCM
    // Ensure chatKey is a proper BufferSource
    const chatKeyBuffer = new Uint8Array(chatKey);
    const cryptoKey = await crypto.subtle.importKey(
      'raw',
      chatKeyBuffer,
      { name: 'AES-GCM' },
      false,
      ['decrypt']
    );

    const decrypted = await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv },
      cryptoKey,
      ciphertext
    );

    const decoder = new TextDecoder();
    return decoder.decode(decrypted);
  } catch (error) {
    // Enhanced logging to help diagnose decryption failures
    console.error(
      `[CryptoService] Chat decryption failed: ${error instanceof Error ? error.message : String(error)}. ` +
      `Error type: ${error instanceof Error ? error.constructor.name : typeof error}. ` +
      `Encrypted data length: ${encryptedDataWithIV.length} chars. ` +
      `Chat key length: ${chatKey.length} bytes. ` +
      `This usually indicates: wrong chat key, malformed encrypted content, or content encrypted with different key.`
    );
    return null;
  }
}

/**
 * Encrypts a chat key with the user's master key for device sync
 * @param chatKey - The chat-specific key to encrypt
 * @returns Promise<string | null> - Base64 encoded encrypted chat key or null if master key not found
 */
export async function encryptChatKeyWithMasterKey(chatKey: Uint8Array): Promise<string | null> {
  const masterKey = await getKeyFromStorage();
  if (!masterKey) {
    return null;
  }

  try {
    const iv = crypto.getRandomValues(new Uint8Array(AES_IV_LENGTH));
    // Ensure chatKey is a proper BufferSource
    const chatKeyBuffer = new Uint8Array(chatKey);
    const encrypted = await crypto.subtle.encrypt(
      { name: 'AES-GCM', iv },
      masterKey,
      chatKeyBuffer
    );

    // Combine IV + ciphertext
    const combined = new Uint8Array(iv.length + encrypted.byteLength);
    combined.set(iv);
    combined.set(new Uint8Array(encrypted), iv.length);

    return uint8ArrayToBase64(combined);
  } catch (error) {
    console.error('Failed to encrypt chat key:', error);
    return null;
  }
}

/**
 * Decrypts a chat key using the user's master key
 * @param encryptedChatKeyWithIV - Base64 encoded encrypted chat key with IV
 * @returns Promise<Uint8Array | null> - Decrypted chat key or null if decryption fails
 */
export async function decryptChatKeyWithMasterKey(encryptedChatKeyWithIV: string): Promise<Uint8Array | null> {
  const masterKey = await getKeyFromStorage();
  if (!masterKey) {
    return null;
  }

  try {
    const combined = base64ToUint8Array(encryptedChatKeyWithIV);
    const iv = combined.slice(0, AES_IV_LENGTH);
    const ciphertext = combined.slice(AES_IV_LENGTH);

    const decrypted = await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv },
      masterKey,
      ciphertext
    );

    return new Uint8Array(decrypted);
  } catch (error) {
    // Decryption failure is expected for hidden chats (they use a different key)
    // Only log at debug level to avoid noise in console
    console.debug('Failed to decrypt chat key with master key (may be a hidden chat):', error);
    return null;
  }
}

/**
 * Encrypts a JSON array (like mates) using a chat-specific key
 * @param array - The array to encrypt
 * @param chatKey - The chat-specific encryption key
 * @returns Promise<string> - Base64 encoded encrypted array
 */
export async function encryptArrayWithChatKey(array: any[], chatKey: Uint8Array): Promise<string> {
  const jsonString = JSON.stringify(array);
  return await encryptWithChatKey(jsonString, chatKey);
}

/**
 * Decrypts a JSON array using a chat-specific key
 * @param encryptedArrayWithIV - Base64 encoded encrypted array with IV
 * @param chatKey - The chat-specific decryption key
 * @returns Promise<any[] | null> - Decrypted array or null if decryption fails
 */
export async function decryptArrayWithChatKey(encryptedArrayWithIV: string, chatKey: Uint8Array): Promise<any[] | null> {
  const decryptedJson = await decryptWithChatKey(encryptedArrayWithIV, chatKey);
  if (!decryptedJson) return null;

  try {
    return JSON.parse(decryptedJson);
  } catch (error) {
    console.error('Error parsing decrypted array:', error);
    return null;
  }
}

// ============================================================================
// EMBED KEY MANAGEMENT
// ============================================================================

/**
 * Generates an embed-specific AES key (32 bytes for AES-256)
 * Each embed has its own unique encryption key
 * @returns Uint8Array - The generated embed key
 */
export function generateEmbedKey(): Uint8Array {
  return crypto.getRandomValues(new Uint8Array(32));
}

/**
 * Wraps an embed key with the user's master key for owner cross-chat access
 * @param embedKey - The embed-specific key to wrap
 * @returns Promise<string | null> - Base64 encoded wrapped key or null if master key not found
 */
export async function wrapEmbedKeyWithMasterKey(embedKey: Uint8Array): Promise<string | null> {
  const masterKey = await getKeyFromStorage();
  if (!masterKey) {
    return null;
  }

  try {
    const iv = crypto.getRandomValues(new Uint8Array(AES_IV_LENGTH));
    const embedKeyBuffer = new Uint8Array(embedKey);
    const encrypted = await crypto.subtle.encrypt(
      { name: 'AES-GCM', iv },
      masterKey,
      embedKeyBuffer
    );

    // Combine IV + ciphertext
    const combined = new Uint8Array(iv.length + encrypted.byteLength);
    combined.set(iv);
    combined.set(new Uint8Array(encrypted), iv.length);

    return uint8ArrayToBase64(combined);
  } catch (error) {
    console.error('Failed to wrap embed key with master key:', error);
    return null;
  }
}

/**
 * Unwraps an embed key using the user's master key
 * @param wrappedEmbedKey - Base64 encoded wrapped embed key with IV
 * @returns Promise<Uint8Array | null> - Unwrapped embed key or null if unwrapping fails
 */
export async function unwrapEmbedKeyWithMasterKey(wrappedEmbedKey: string): Promise<Uint8Array | null> {
  const masterKey = await getKeyFromStorage();
  if (!masterKey) {
    console.warn('[CryptoService] unwrapEmbedKeyWithMasterKey: No master key in storage!');
    return null;
  }

  try {
    const combined = base64ToUint8Array(wrappedEmbedKey);
    const iv = combined.slice(0, AES_IV_LENGTH);
    const ciphertext = combined.slice(AES_IV_LENGTH);

    const decrypted = await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv },
      masterKey,
      ciphertext
    );

    console.debug('[CryptoService] Successfully unwrapped embed key with master key, length:', decrypted.byteLength);
    return new Uint8Array(decrypted);
  } catch (error) {
    console.warn('[CryptoService] Failed to unwrap embed key with master key (key mismatch?):', error);
    return null;
  }
}

/**
 * Wraps an embed key with a chat key for shared chat access
 * @param embedKey - The embed-specific key to wrap
 * @param chatKey - The chat-specific key to use for wrapping
 * @returns Promise<string> - Base64 encoded wrapped key
 */
export async function wrapEmbedKeyWithChatKey(embedKey: Uint8Array, chatKey: Uint8Array): Promise<string> {
  const chatKeyBuffer = new Uint8Array(chatKey);
  const cryptoKey = await crypto.subtle.importKey(
    'raw',
    chatKeyBuffer,
    { name: 'AES-GCM' },
    false,
    ['encrypt']
  );

  const iv = crypto.getRandomValues(new Uint8Array(AES_IV_LENGTH));
  const embedKeyBuffer = new Uint8Array(embedKey);
  const encrypted = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv },
    cryptoKey,
    embedKeyBuffer
  );

  // Combine IV + ciphertext
  const combined = new Uint8Array(iv.length + encrypted.byteLength);
  combined.set(iv);
  combined.set(new Uint8Array(encrypted), iv.length);

  return uint8ArrayToBase64(combined);
}

/**
 * Unwraps an embed key using a chat key (for shared chat access)
 * @param wrappedEmbedKey - Base64 encoded wrapped embed key with IV
 * @param chatKey - The chat-specific key to use for unwrapping
 * @returns Promise<Uint8Array | null> - Unwrapped embed key or null if unwrapping fails
 */
export async function unwrapEmbedKeyWithChatKey(wrappedEmbedKey: string, chatKey: Uint8Array): Promise<Uint8Array | null> {
  try {
    const chatKeyBuffer = new Uint8Array(chatKey);
    const cryptoKey = await crypto.subtle.importKey(
      'raw',
      chatKeyBuffer,
      { name: 'AES-GCM' },
      false,
      ['decrypt']
    );

    const combined = base64ToUint8Array(wrappedEmbedKey);
    const iv = combined.slice(0, AES_IV_LENGTH);
    const ciphertext = combined.slice(AES_IV_LENGTH);

    const decrypted = await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv },
      cryptoKey,
      ciphertext
    );

    console.debug('[CryptoService] Successfully unwrapped embed key with chat key, length:', decrypted.byteLength);
    return new Uint8Array(decrypted);
  } catch (error) {
    console.warn('[CryptoService] Failed to unwrap embed key with chat key:', error);
    return null;
  }
}

/**
 * Encrypts data using an embed-specific key (AES-GCM)
 * @param data - The data to encrypt
 * @param embedKey - The embed-specific encryption key
 * @returns Promise<string> - Base64 encoded encrypted data with IV
 */
export async function encryptWithEmbedKey(data: string, embedKey: Uint8Array): Promise<string> {
  const encoder = new TextEncoder();
  const dataBytes = encoder.encode(data);

  const embedKeyBuffer = new Uint8Array(embedKey);
  const cryptoKey = await crypto.subtle.importKey(
    'raw',
    embedKeyBuffer,
    { name: 'AES-GCM' },
    false,
    ['encrypt']
  );

  const iv = crypto.getRandomValues(new Uint8Array(AES_IV_LENGTH));
  const encrypted = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv },
    cryptoKey,
    dataBytes
  );

  // Combine IV + ciphertext
  const combined = new Uint8Array(iv.length + encrypted.byteLength);
  combined.set(iv);
  combined.set(new Uint8Array(encrypted), iv.length);

  return uint8ArrayToBase64(combined);
}

/**
 * Decrypts data using an embed-specific key (AES-GCM)
 * @param encryptedDataWithIV - Base64 encoded encrypted data with IV
 * @param embedKey - The embed-specific decryption key
 * @returns Promise<string | null> - Decrypted data or null if decryption fails
 */
export async function decryptWithEmbedKey(encryptedDataWithIV: string, embedKey: Uint8Array): Promise<string | null> {
  try {
    const combined = base64ToUint8Array(encryptedDataWithIV);
    const iv = combined.slice(0, AES_IV_LENGTH);
    const ciphertext = combined.slice(AES_IV_LENGTH);

    const embedKeyBuffer = new Uint8Array(embedKey);
    const cryptoKey = await crypto.subtle.importKey(
      'raw',
      embedKeyBuffer,
      { name: 'AES-GCM' },
      false,
      ['decrypt']
    );

    const decrypted = await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv },
      cryptoKey,
      ciphertext
    );

    const decoder = new TextDecoder();
    return decoder.decode(decrypted);
  } catch (error) {
    console.error('Embed decryption failed:', error);
    return null;
  }
}

// ============================================================================
// RECOVERY KEY MANAGEMENT
// ============================================================================

/**
 * Generates a secure recovery key with good entropy and readability
 * @param length - The length of the recovery key
 * @returns string - The generated recovery key
 */
export function generateSecureRecoveryKey(length = 24): string {
  // Define character sets for the recovery key
  const uppercaseChars = 'ABCDEFGHJKLMNPQRSTUVWXYZ'; // Removed confusing I and O
  const lowercaseChars = 'abcdefghijkmnopqrstuvwxyz'; // Removed confusing l
  const numberChars = '23456789'; // Removed confusing 0 and 1
  const specialChars = '#-=+_&%$';

  // Combine all character sets
  const allChars = uppercaseChars + lowercaseChars + numberChars + specialChars;

  // Generate random bytes using cryptographically secure RNG
  const randomBytes = crypto.getRandomValues(new Uint8Array(length));

  // Ensure we have at least one character from each set by reserving positions
  let result: string[] = new Array(length);

  // Reserve first 4 positions for mandatory character types
  const charSets = [
    { chars: uppercaseChars, index: 0 },
    { chars: lowercaseChars, index: 1 },
    { chars: numberChars, index: 2 },
    { chars: specialChars, index: 3 }
  ];

  // Fill mandatory positions with secure randomness
  for (const charSet of charSets) {
    const randomByte = crypto.getRandomValues(new Uint8Array(1))[0];
    result[charSet.index] = charSet.chars.charAt(randomByte % charSet.chars.length);
  }

  // Fill remaining positions with secure random characters from all sets
  for (let i = 4; i < length; i++) {
    result[i] = allChars.charAt(randomBytes[i] % allChars.length);
  }

  // Shuffle using Fisher-Yates with cryptographically secure randomness
  for (let i = result.length - 1; i > 0; i--) {
    const j = Math.floor((crypto.getRandomValues(new Uint8Array(1))[0] / 256) * (i + 1));
    [result[i], result[j]] = [result[j], result[i]];
  }

  return result.join('');
}

/**
 * Creates a SHA-256 hash of any key (password, recovery key, passkey PRF) for lookup purposes
 * Optionally includes a salt for additional security
 *
 * @param key - The key to hash (password, recovery key, etc.)
 * @param salt - Optional salt to include in the hash
 * @returns Promise<string> - Base64 encoded hash
 */
export async function hashKey(key: string, salt: Uint8Array | null = null): Promise<string> {
  const encoder = new TextEncoder();
  const keyBytes = encoder.encode(key);

  let dataToHash: Uint8Array;

  // If salt is provided, combine it with the key
  if (salt) {
    dataToHash = new Uint8Array(keyBytes.length + salt.length);
    dataToHash.set(keyBytes);
    dataToHash.set(salt, keyBytes.length);
  } else {
    dataToHash = keyBytes;
  }

  // Hash the data
  // Ensure dataToHash is a proper BufferSource
  const dataToHashBuffer = new Uint8Array(dataToHash);
  const hashBuffer = await crypto.subtle.digest('SHA-256', dataToHashBuffer);
  const hashArray = new Uint8Array(hashBuffer);

  // Convert to base64 string
  let hashBinary = '';
  for (let i = 0; i < hashArray.length; i++) {
    hashBinary += String.fromCharCode(hashArray[i]);
  }
  return window.btoa(hashBinary);
}

// ============================================================================
// PASSKEY PRF AND HKDF FUNCTIONS
// ============================================================================

/**
 * HMAC-based Key Derivation Function (HKDF) as specified in RFC 5869
 * Used to derive wrapping keys from PRF signatures for passkey authentication
 * 
 * @param salt - Salt value (user_email_salt for passkeys)
 * @param ikm - Input key material (PRF signature bytes)
 * @param info - Application-specific information ("masterkey_wrapping")
 * @param length - Desired output length in bytes (32 for AES-256)
 * @returns Promise<Uint8Array> - Derived key bytes
 */
export async function hkdf(
  salt: Uint8Array,
  ikm: Uint8Array,
  info: string,
  length: number = 32
): Promise<Uint8Array> {
  if (typeof window === 'undefined') {
    return new Uint8Array(length);
  }

  const encoder = new TextEncoder();
  const infoBytes = encoder.encode(info);

  // Step 1: Extract (HKDF-Extract)
  // PRK = HMAC-Hash(salt, IKM)
  // Ensure salt is a proper BufferSource by creating a new Uint8Array
  const saltBuffer = new Uint8Array(salt);
  const extractKey = await crypto.subtle.importKey(
    'raw',
    saltBuffer,
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign']
  );

  // Ensure ikm is a proper BufferSource
  const ikmBuffer = new Uint8Array(ikm);
  const prk = await crypto.subtle.sign('HMAC', extractKey, ikmBuffer);
  const prkArray = new Uint8Array(prk);

  // Step 2: Expand (HKDF-Expand)
  // OKM = HKDF-Expand(PRK, info, L)
  const expandKey = await crypto.subtle.importKey(
    'raw',
    prkArray,
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign']
  );

  const okm: Uint8Array[] = [];
  let counter = 1;
  let remaining = length;

  while (remaining > 0) {
    // T(i) = HMAC-Hash(PRK, T(i-1) | info | i)
    const tInput = new Uint8Array(
      (okm.length > 0 ? okm[okm.length - 1].length : 0) + infoBytes.length + 1
    );
    let offset = 0;
    
    if (okm.length > 0) {
      tInput.set(okm[okm.length - 1], offset);
      offset += okm[okm.length - 1].length;
    }
    
    tInput.set(infoBytes, offset);
    offset += infoBytes.length;
    tInput[offset] = counter;

    const t = await crypto.subtle.sign('HMAC', expandKey, tInput);
    const tArray = new Uint8Array(t);
    
    const toTake = Math.min(remaining, tArray.length);
    okm.push(tArray.slice(0, toTake));
    remaining -= toTake;
    counter++;
  }

  // Concatenate all T(i) values
  const result = new Uint8Array(length);
  let resultOffset = 0;
  for (const chunk of okm) {
    result.set(chunk, resultOffset);
    resultOffset += chunk.length;
  }

  return result;
}

/**
 * Derives a wrapping key from a PRF signature using HKDF
 * This is used for passkey-based master key wrapping (zero-knowledge encryption)
 * 
 * @param prfSignature - PRF signature bytes from WebAuthn extension
 * @param emailSalt - User's email salt (user_email_salt)
 * @returns Promise<Uint8Array> - Derived wrapping key (32 bytes for AES-256)
 */
export async function deriveWrappingKeyFromPRF(
  prfSignature: Uint8Array,
  emailSalt: Uint8Array
): Promise<Uint8Array> {
  const info = 'masterkey_wrapping';
  return await hkdf(emailSalt, prfSignature, info, 32);
}

/**
 * Creates a lookup hash from PRF signature for authentication
 * Same pattern as password: SHA256(PRF_signature + user_email_salt)
 * 
 * @param prfSignature - PRF signature bytes from WebAuthn extension
 * @param emailSalt - User's email salt (user_email_salt)
 * @returns Promise<string> - Base64-encoded lookup hash
 */
export async function hashKeyFromPRF(
  prfSignature: Uint8Array,
  emailSalt: Uint8Array
): Promise<string> {
  // Combine PRF signature and salt
  const combined = new Uint8Array(prfSignature.length + emailSalt.length);
  combined.set(prfSignature);
  combined.set(emailSalt, prfSignature.length);

  // Hash with SHA-256
  const hashBuffer = await crypto.subtle.digest('SHA-256', combined);
  const hashArray = new Uint8Array(hashBuffer);

  // Convert to base64
  let hashBinary = '';
  for (let i = 0; i < hashArray.length; i++) {
    hashBinary += String.fromCharCode(hashArray[i]);
  }
  return window.btoa(hashBinary);
}

/**
 * Checks if PRF extension is supported by the browser/device
 * This is a helper function for error messages - actual PRF support
 * can only be verified after attempting to create a passkey
 * 
 * @returns boolean - True if WebAuthn and PRF extension might be supported
 */
export function checkPRFSupport(): boolean {
  if (typeof window === 'undefined' || !navigator.credentials) {
    return false;
  }
  
  // Check if WebAuthn is available
  if (!navigator.credentials.create || !navigator.credentials.get) {
    return false;
  }
  
  // PRF extension support can only be verified by attempting creation
  // This function just checks if WebAuthn API is available
  // Actual PRF support is checked via getClientExtensionResults() after creation
  return true;
}

/**
 * Unwraps a child embed key using a parent embed key (for shared embed access)
 * @param wrappedEmbedKey - Base64 encoded wrapped embed key with IV
 * @param parentEmbedKey - The parent embed-specific key to use for unwrapping
 * @returns Promise<Uint8Array | null> - Unwrapped child embed key or null if unwrapping fails
 */
export async function unwrapEmbedKeyWithEmbedKey(wrappedEmbedKey: string, parentEmbedKey: Uint8Array): Promise<Uint8Array | null> {
  try {
    const parentEmbedKeyBuffer = new Uint8Array(parentEmbedKey);
    const cryptoKey = await crypto.subtle.importKey(
      'raw',
      parentEmbedKeyBuffer,
      { name: 'AES-GCM' },
      false,
      ['decrypt']
    );

    const combined = base64ToUint8Array(wrappedEmbedKey);
    const iv = combined.slice(0, AES_IV_LENGTH);
    const ciphertext = combined.slice(AES_IV_LENGTH);

    const decrypted = await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv },
      cryptoKey,
      ciphertext
    );

    console.debug('[CryptoService] Successfully unwrapped child embed key with parent embed key, length:', decrypted.byteLength);
    return new Uint8Array(decrypted);
  } catch (error) {
    console.warn('[CryptoService] Failed to unwrap child embed key with parent embed key:', error);
    return null;
  }
}
