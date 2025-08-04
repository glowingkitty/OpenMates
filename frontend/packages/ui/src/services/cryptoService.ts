/**
 * Cryptographic service for OpenMates
 *
 * This service handles:
 * - Master key generation and storage (decrypted in session/local storage)
 * - Email encryption key generation and storage (for server use only)
 * - Email encryption with master key (for client storage)
 * - General-purpose encryption/decryption using master key
 * - Key wrapping for server storage
 *
 * Security Architecture:
 * - Master key: Generated client-side, stored decrypted in session/local storage
 * - Email encryption key: SHA256(email + user_email_salt), stored on client, sent to server only during login
 * - Email storage: Encrypted with master key on client, encrypted with email encryption key on server
 *
 * Email Handling Flow:
 * 1. During signup, the email is collected in plaintext in the signup store
 * 2. In the password step:
 *    - The master key is generated and stored in session/local storage
 *    - The email encryption key is generated and stored in session/local storage
 *    - The email is encrypted with the master key and stored in session/local storage
 *    - The plaintext email is removed from the signup store
 * 3. After the password step:
 *    - Components that need the email should decrypt it on demand using getEmailDecryptedWithMasterKey()
 *    - The email should never be stored in plaintext in the store or any other persistent storage
 *    - The email encryption key is sent to the server only during login/2FA setup
 */
import nacl from 'tweetnacl';

// Master key storage constants
const SESSION_STORAGE_KEY = 'openmates_master_key';
const LOCAL_STORAGE_KEY = 'openmates_master_key_persistent';

// Email encryption key storage constants (for server communication)
const EMAIL_ENCRYPTION_KEY = 'openmates_email_encryption_key';

// Email salt storage constant
const EMAIL_SALT_KEY = 'openmates_email_salt';

// Email storage constants (encrypted with master key for client use)
const EMAIL_ENCRYPTED_WITH_MASTER_KEY = 'openmates_email_encrypted_master';

// Helper function to convert Uint8Array to Base64
export function uint8ArrayToBase64(bytes: Uint8Array): string {
  let binary = '';
  const len = bytes.byteLength;
  for (let i = 0; i < len; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return window.btoa(binary);
}

// Helper function to convert Base64 to Uint8Array
export function base64ToUint8Array(base64: string): Uint8Array {
  const binary_string = window.atob(base64);
  const len = binary_string.length;
  const bytes = new Uint8Array(len);
  for (let i = 0; i < len; i++) {
    bytes[i] = binary_string.charCodeAt(i);
  }
  return bytes;
}

export function generateSalt(length = 16): Uint8Array {
  return nacl.randomBytes(length);
}

export function generateUserMasterKey(): Uint8Array {
  return nacl.randomBytes(nacl.secretbox.keyLength);
}

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
        iterations: 100000,
        hash: 'SHA-256'
      },
      keyMaterial,
      256
    );
    
    return new Uint8Array(derivedBits);
  }
  return new Uint8Array(32);
}

export function encryptKey(masterKey: Uint8Array, wrappingKey: Uint8Array): string {
  const nonce = nacl.randomBytes(nacl.secretbox.nonceLength);
  const encryptedKey = nacl.secretbox(masterKey, nonce, wrappingKey);

  const combined = new Uint8Array(nonce.length + encryptedKey.length);
  combined.set(nonce);
  combined.set(encryptedKey, nonce.length);

  return uint8ArrayToBase64(combined);
}

export function decryptKey(encryptedKeyWithNonce: string, wrappingKey: Uint8Array): Uint8Array | null {
  const combined = base64ToUint8Array(encryptedKeyWithNonce);
  const nonce = combined.slice(0, nacl.secretbox.nonceLength);
  const encryptedKey = combined.slice(nacl.secretbox.nonceLength);

  const decryptedKey = nacl.secretbox.open(encryptedKey, nonce, wrappingKey);

  return decryptedKey;
}

// Modified to accept useLocalStorage parameter
export function saveKeyToSession(key: Uint8Array, useLocalStorage: boolean = false): void {
  if (typeof window !== 'undefined') {
    const keyB64 = uint8ArrayToBase64(key);
    if (useLocalStorage) {
      localStorage.setItem(LOCAL_STORAGE_KEY, keyB64);
      sessionStorage.removeItem(SESSION_STORAGE_KEY); // Ensure session storage is clear if using local
    } else {
      sessionStorage.setItem(SESSION_STORAGE_KEY, keyB64);
      localStorage.removeItem(LOCAL_STORAGE_KEY); // Ensure local storage is clear if not using local
    }
  }
}

// New function to get key from storage (prefers local storage)
export function getKeyFromStorage(): Uint8Array | null {
  if (typeof window !== 'undefined') {
    let keyB64 = localStorage.getItem(LOCAL_STORAGE_KEY);
    if (keyB64) {
      return base64ToUint8Array(keyB64);
    }
    keyB64 = sessionStorage.getItem(SESSION_STORAGE_KEY);
    if (keyB64) {
      return base64ToUint8Array(keyB64);
    }
  }
  return null;
}

// New function to clear key from both storage types
export function clearKeyFromStorage(): void {
  if (typeof window !== 'undefined') {
    sessionStorage.removeItem(SESSION_STORAGE_KEY);
    localStorage.removeItem(LOCAL_STORAGE_KEY);
  }
}

// Original functions (kept for compatibility if needed, but new ones are preferred)
export function getKeyFromSession(): Uint8Array | null {
  if (typeof window !== 'undefined') {
    const keyB64 = sessionStorage.getItem(SESSION_STORAGE_KEY);
    if (!keyB64) {
      return null;
    }
    return base64ToUint8Array(keyB64);
  }
  return null;
}

export function clearKeyFromSession(): void {
  if (typeof window !== 'undefined') {
    sessionStorage.removeItem(SESSION_STORAGE_KEY);
  }
}

// Email encryption functions

/**
 * Generates a random salt for email encryption
 * @returns {Uint8Array} Random salt
 */
export function generateEmailSalt(): Uint8Array {
  return nacl.randomBytes(16);
}

/**
 * Derives an encryption key from email and salt using SHA-256
 * @param {string} email - The email address
 * @param {Uint8Array} salt - The salt
 * @returns {Promise<Uint8Array>} - The derived key
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
 * Encrypts an email address using the derived key
 * @param {string} email - The email address to encrypt
 * @param {Uint8Array} key - The encryption key
 * @returns {string} - Base64 encoded encrypted email
 */
export function encryptEmail(email: string, key: Uint8Array): string {
  const encoder = new TextEncoder();
  const emailBytes = encoder.encode(email);
  
  const nonce = nacl.randomBytes(nacl.secretbox.nonceLength);
  const encryptedEmail = nacl.secretbox(emailBytes, nonce, key);
  
  const combined = new Uint8Array(nonce.length + encryptedEmail.length);
  combined.set(nonce);
  combined.set(encryptedEmail, nonce.length);
  
  return uint8ArrayToBase64(combined);
}

/**
 * Decrypts an encrypted email address
 * @param {string} encryptedEmailWithNonce - Base64 encoded encrypted email with nonce
 * @param {Uint8Array} key - The decryption key
 * @returns {string|null} - Decrypted email or null if decryption fails
 */
export function decryptEmail(encryptedEmailWithNonce: string, key: Uint8Array): string | null {
  const combined = base64ToUint8Array(encryptedEmailWithNonce);
  const nonce = combined.slice(0, nacl.secretbox.nonceLength);
  const encryptedEmail = combined.slice(nacl.secretbox.nonceLength);
  
  const decryptedEmailBytes = nacl.secretbox.open(encryptedEmail, nonce, key);
  
  if (!decryptedEmailBytes) return null;
  
  const decoder = new TextDecoder();
  return decoder.decode(decryptedEmailBytes);
}

/**
 * Creates a SHA-256 hash of an email for lookup purposes
 * @param {string} email - The email address to hash
 * @returns {Promise<string>} - Base64 encoded hash
 */
export async function hashEmail(email: string): Promise<string> {
  const encoder = new TextEncoder();
  const emailBytes = encoder.encode(email);
  
  const hashBuffer = await crypto.subtle.digest('SHA-256', emailBytes);
  const hashArray = new Uint8Array(hashBuffer);
  
  return uint8ArrayToBase64(hashArray);
}

// ============================================================================
// GENERAL-PURPOSE ENCRYPTION/DECRYPTION USING MASTER KEY
// ============================================================================

/**
 * Encrypts data using the master key from storage
 * @param {string} data - The data to encrypt
 * @returns {string|null} - Base64 encoded encrypted data or null if master key not found
 */
export function encryptWithMasterKey(data: string): string | null {
  const masterKey = getKeyFromStorage();
  if (!masterKey) {
    return null;
  }
  
  const encoder = new TextEncoder();
  const dataBytes = encoder.encode(data);
  
  const nonce = nacl.randomBytes(nacl.secretbox.nonceLength);
  const encryptedData = nacl.secretbox(dataBytes, nonce, masterKey);
  
  const combined = new Uint8Array(nonce.length + encryptedData.length);
  combined.set(nonce);
  combined.set(encryptedData, nonce.length);
  
  return uint8ArrayToBase64(combined);
}

/**
 * Decrypts data using the master key from storage
 * @param {string} encryptedDataWithNonce - Base64 encoded encrypted data with nonce
 * @returns {string|null} - Decrypted data or null if decryption fails or master key not found
 */
export function decryptWithMasterKey(encryptedDataWithNonce: string): string | null {
  const masterKey = getKeyFromStorage();
  if (!masterKey) {
    return null;
  }
  
  try {
    const combined = base64ToUint8Array(encryptedDataWithNonce);
    const nonce = combined.slice(0, nacl.secretbox.nonceLength);
    const encryptedData = combined.slice(nacl.secretbox.nonceLength);
    
    const decryptedDataBytes = nacl.secretbox.open(encryptedData, nonce, masterKey);
    
    if (!decryptedDataBytes) return null;
    
    const decoder = new TextDecoder();
    return decoder.decode(decryptedDataBytes);
  } catch (error) {
    console.error('Error decrypting data with master key:', error);
    return null;
  }
}

// ============================================================================
// EMAIL ENCRYPTION KEY MANAGEMENT (FOR SERVER COMMUNICATION)
// ============================================================================

/**
 * Stores the email encryption key in storage
 * @param {Uint8Array} emailEncryptionKey - The email encryption key
 * @param {boolean} useLocalStorage - Whether to use localStorage (true) or sessionStorage (false)
 */
export function saveEmailEncryptionKey(emailEncryptionKey: Uint8Array, useLocalStorage: boolean = false): void {
  if (typeof window !== 'undefined') {
    const keyBase64 = uint8ArrayToBase64(emailEncryptionKey);
    
    if (useLocalStorage) {
      localStorage.setItem(EMAIL_ENCRYPTION_KEY, keyBase64);
      sessionStorage.removeItem(EMAIL_ENCRYPTION_KEY);
    } else {
      sessionStorage.setItem(EMAIL_ENCRYPTION_KEY, keyBase64);
      localStorage.removeItem(EMAIL_ENCRYPTION_KEY);
    }
  }
}

/**
 * Retrieves the email encryption key from storage
 * @returns {Uint8Array|null} - The email encryption key or null if not found
 */
export function getEmailEncryptionKey(): Uint8Array | null {
  if (typeof window !== 'undefined') {
    // Try localStorage first
    let keyBase64 = localStorage.getItem(EMAIL_ENCRYPTION_KEY);
    if (keyBase64) {
      return base64ToUint8Array(keyBase64);
    }
    
    // Try sessionStorage
    keyBase64 = sessionStorage.getItem(EMAIL_ENCRYPTION_KEY);
    if (keyBase64) {
      return base64ToUint8Array(keyBase64);
    }
  }
  
  return null;
}

/**
 * Gets the email encryption key as base64 for API use
 * @returns {string|null} - Base64 encoded email encryption key or null if not found
 */
export function getEmailEncryptionKeyForApi(): string | null {
  const key = getEmailEncryptionKey();
  return key ? uint8ArrayToBase64(key) : null;
}

/**
 * Clears the email encryption key from storage
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
 * @param {string} email - The plaintext email
 * @param {boolean} useLocalStorage - Whether to use localStorage (true) or sessionStorage (false)
 * @returns {boolean} - True if successful, false if master key not available
 */
export function saveEmailEncryptedWithMasterKey(email: string, useLocalStorage: boolean = false): boolean {
  const encryptedEmail = encryptWithMasterKey(email);
  if (!encryptedEmail) {
    return false;
  }
  
  if (typeof window !== 'undefined') {
    if (useLocalStorage) {
      localStorage.setItem(EMAIL_ENCRYPTED_WITH_MASTER_KEY, encryptedEmail);
      sessionStorage.removeItem(EMAIL_ENCRYPTED_WITH_MASTER_KEY);
    } else {
      sessionStorage.setItem(EMAIL_ENCRYPTED_WITH_MASTER_KEY, encryptedEmail);
      localStorage.removeItem(EMAIL_ENCRYPTED_WITH_MASTER_KEY);
    }
  }
  
  return true;
}

/**
 * Gets the plaintext email by decrypting it with the master key
 * @returns {string|null} - Decrypted email or null if not found or decryption fails
 */
export function getEmailDecryptedWithMasterKey(): string | null {
  if (typeof window !== 'undefined') {
    // Try localStorage first
    let encryptedEmail = localStorage.getItem(EMAIL_ENCRYPTED_WITH_MASTER_KEY);
    if (encryptedEmail) {
      return decryptWithMasterKey(encryptedEmail);
    }
    
    // Try sessionStorage
    encryptedEmail = sessionStorage.getItem(EMAIL_ENCRYPTED_WITH_MASTER_KEY);
    if (encryptedEmail) {
      return decryptWithMasterKey(encryptedEmail);
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
 * Stores the email salt in storage
 * @param {Uint8Array} emailSalt - The email salt
 * @param {boolean} useLocalStorage - Whether to use localStorage (true) or sessionStorage (false)
 */
export function saveEmailSalt(emailSalt: Uint8Array, useLocalStorage: boolean = false): void {
  if (typeof window !== 'undefined') {
    const saltBase64 = uint8ArrayToBase64(emailSalt);
    
    if (useLocalStorage) {
      localStorage.setItem(EMAIL_SALT_KEY, saltBase64);
      sessionStorage.removeItem(EMAIL_SALT_KEY);
    } else {
      sessionStorage.setItem(EMAIL_SALT_KEY, saltBase64);
      localStorage.removeItem(EMAIL_SALT_KEY);
    }
  }
}

/**
 * Retrieves the email salt from storage
 * @returns {Uint8Array|null} - The email salt or null if not found
 */
export function getEmailSalt(): Uint8Array | null {
  if (typeof window !== 'undefined') {
    // Try localStorage first
    let saltBase64 = localStorage.getItem(EMAIL_SALT_KEY);
    if (saltBase64) {
      return base64ToUint8Array(saltBase64);
    }
    
    // Try sessionStorage
    saltBase64 = sessionStorage.getItem(EMAIL_SALT_KEY);
    if (saltBase64) {
      return base64ToUint8Array(saltBase64);
    }
  }
  
  return null;
}

/**
 * Clears the email salt from storage
 */
export function clearEmailSalt(): void {
  if (typeof window !== 'undefined') {
    sessionStorage.removeItem(EMAIL_SALT_KEY);
    localStorage.removeItem(EMAIL_SALT_KEY);
  }
}

// ============================================================================
// RECOVERY KEY MANAGEMENT
// ============================================================================

/**
 * Generates a secure recovery key with good entropy and readability
 * @param {number} length - The length of the recovery key
 * @returns {string} - The generated recovery key
 */
export function generateSecureRecoveryKey(length = 24): string {
  // Define character sets for the recovery key
  const uppercaseChars = 'ABCDEFGHJKLMNPQRSTUVWXYZ'; // Removed confusing I and O
  const lowercaseChars = 'abcdefghijkmnopqrstuvwxyz'; // Removed confusing l
  const numberChars = '23456789'; // Removed confusing 0 and 1
  const specialChars = '#-=+_&%$';
  
  // Combine all character sets
  const allChars = uppercaseChars + lowercaseChars + numberChars + specialChars;
  
  // Ensure we have at least one character from each set
  let result = '';
  result += uppercaseChars.charAt(Math.floor(Math.random() * uppercaseChars.length));
  result += lowercaseChars.charAt(Math.floor(Math.random() * lowercaseChars.length));
  result += numberChars.charAt(Math.floor(Math.random() * numberChars.length));
  result += specialChars.charAt(Math.floor(Math.random() * specialChars.length));
  
  // Fill the rest with random characters from all sets
  for (let i = result.length; i < length; i++) {
    result += allChars.charAt(Math.floor(Math.random() * allChars.length));
  }
  
  // Shuffle the result to avoid predictable patterns
  return result.split('').sort(() => 0.5 - Math.random()).join('');
}

/**
 * Creates a SHA-256 hash of any key (password, recovery key, passkey PRF) for lookup purposes
 * Optionally includes a salt for additional security
 *
 * @param {string} key - The key to hash (password, recovery key, etc.)
 * @param {Uint8Array|null} salt - Optional salt to include in the hash
 * @returns {Promise<string>} - Base64 encoded hash
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
