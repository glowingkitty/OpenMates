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
 */
export function base64ToUint8Array(base64: string): Uint8Array {
  const binary_string = window.atob(base64);
  const len = binary_string.length;
  const bytes = new Uint8Array(len);
  for (let i = 0; i < len; i++) {
    bytes[i] = binary_string.charCodeAt(i);
  }
  return bytes;
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
 * Saves a CryptoKey to IndexedDB (for extractable session keys)
 * Extractable keys allow wrapping for recovery keys while still using Web Crypto API
 * @param key - The CryptoKey to store
 */
export async function saveKeyToSession(key: CryptoKey): Promise<void> {
  await saveMasterKeyToIndexedDB(key);
}

/**
 * Gets the master CryptoKey from IndexedDB
 * @returns Promise<CryptoKey | null> - The master key or null if not found
 */
export async function getKeyFromStorage(): Promise<CryptoKey | null> {
  return await getMasterKeyFromIndexedDB();
}

/**
 * Clears the master key from IndexedDB
 */
export async function clearKeyFromStorage(): Promise<void> {
  await clearMasterKeyFromIndexedDB();
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

    const derivedBits = await crypto.subtle.deriveBits(
      {
        name: 'PBKDF2',
        salt: salt,
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
 * Wraps (encrypts) a master key with a password-derived key for server storage
 * Uses Web Crypto API wrapKey() for secure key wrapping
 * @param masterKey - The master CryptoKey to wrap
 * @param wrappingKeyBytes - Password-derived key bytes
 * @returns Promise<{wrapped: string, iv: string}> - Base64 encoded wrapped key and IV
 */
export async function encryptKey(masterKey: CryptoKey, wrappingKeyBytes: Uint8Array): Promise<{ wrapped: string; iv: string }> {
  // Import the wrapping key bytes as a CryptoKey
  const wrappingKey = await crypto.subtle.importKey(
    'raw',
    wrappingKeyBytes,
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
    const unwrappingKey = await crypto.subtle.importKey(
      'raw',
      wrappingKeyBytes,
      { name: 'AES-GCM' },
      false,
      ['unwrapKey']
    );

    // Unwrap the master key as extractable
    // Extractable keys allow wrapping for recovery keys while still using Web Crypto API
    // XSS can use keys anyway if they have access, so extractability is a marginal security trade-off
    const masterKey = await crypto.subtle.unwrapKey(
      'raw',
      base64ToUint8Array(wrappedKeyBase64),
      unwrappingKey,
      { name: 'AES-GCM', iv: base64ToUint8Array(iv) },
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
 * @param useLocalStorage - Ignored (always uses sessionStorage)
 * @returns Promise<boolean> - True if successful, false if master key not available
 */
export async function saveEmailEncryptedWithMasterKey(email: string, useLocalStorage: boolean = false): Promise<boolean> {
  const encryptedEmail = await encryptWithMasterKey(email);
  if (!encryptedEmail) {
    return false;
  }

  if (typeof window !== 'undefined') {
    // Always use sessionStorage for encrypted email
    sessionStorage.setItem(EMAIL_ENCRYPTED_WITH_MASTER_KEY, encryptedEmail);
  }

  return true;
}

/**
 * Gets the plaintext email by decrypting it with the master key
 * @returns Promise<string | null> - Decrypted email or null if not found or decryption fails
 */
export async function getEmailDecryptedWithMasterKey(): Promise<string | null> {
  if (typeof window !== 'undefined') {
    const encryptedEmail = sessionStorage.getItem(EMAIL_ENCRYPTED_WITH_MASTER_KEY);
    if (encryptedEmail) {
      return await decryptWithMasterKey(encryptedEmail);
    }
  }
  return null;
}

/**
 * Clears the encrypted email from storage
 */
export function clearEmailEncryptedWithMasterKey(): void {
  if (typeof window !== 'undefined') {
    sessionStorage.removeItem(EMAIL_ENCRYPTED_WITH_MASTER_KEY);
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
  const cryptoKey = await crypto.subtle.importKey(
    'raw',
    chatKey,
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
    const cryptoKey = await crypto.subtle.importKey(
      'raw',
      chatKey,
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
    console.error('Chat decryption failed:', error);
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
    const encrypted = await crypto.subtle.encrypt(
      { name: 'AES-GCM', iv },
      masterKey,
      chatKey
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
    console.error('Failed to decrypt chat key:', error);
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
  const hashBuffer = await crypto.subtle.digest('SHA-256', dataToHash);
  const hashArray = new Uint8Array(hashBuffer);

  // Convert to base64 string
  let hashBinary = '';
  for (let i = 0; i < hashArray.length; i++) {
    hashBinary += String.fromCharCode(hashArray[i]);
  }
  return window.btoa(hashBinary);
}
