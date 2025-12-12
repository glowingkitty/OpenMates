/**
 * Hidden Chat Service
 *
 * Manages encryption and decryption of hidden chats using a code-derived secret.
 * Hidden chats use a combined secret derived from master_key + 4-6 digit code via PBKDF2.
 * This maintains zero-knowledge architecture: server never sees the code or can access hidden chat content.
 *
 * Architecture:
 * - Combined secret: PBKDF2(master_key || code, salt)
 * - Salt: Device-specific, derived from user_id + device_hash, stored in sessionStorage
 * - KDF: PBKDF2 with 100,000 iterations (matching login flow strength)
 * - Scope: One code unlocks all hidden chats (per-user, not per-chat)
 */

import { getKeyFromStorage } from './cryptoService';
import { 
    encryptChatKeyWithMasterKey, 
    decryptChatKeyWithMasterKey,
    deriveKeyFromPassword,
    generateSalt,
    uint8ArrayToBase64,
    base64ToUint8Array,
    PBKDF2_ITERATIONS
} from './cryptoService';
import { userDB } from './userDB';
import { browser } from '$app/environment';

// Storage keys
const HIDDEN_CHAT_SALT_KEY = 'hidden_chat_salt';
const HIDDEN_CHAT_CODE_KEY = 'hidden_chat_code'; // Stored in sessionStorage only

// Rate limiting constants
const MAX_FAILED_ATTEMPTS = 3;
const LOCKOUT_DURATION_MS = 30000; // 30 seconds

class HiddenChatService {
    // Combined secret in volatile memory only (never persisted)
    private combinedSecret: Uint8Array | null = null;
    
    // Rate limiting state
    private failedAttempts = 0;
    private lockoutUntil: number | null = null;

    /**
     * Get or generate device-specific salt for hidden chat key derivation
     * Salt is derived from user_id + device_hash and stored in sessionStorage
     */
    private async getOrCreateSalt(): Promise<Uint8Array> {
        if (!browser) {
            throw new Error('Hidden chat service requires browser environment');
        }

        // Try to get existing salt from sessionStorage
        const storedSalt = sessionStorage.getItem(HIDDEN_CHAT_SALT_KEY);
        if (storedSalt) {
            try {
                return base64ToUint8Array(storedSalt);
            } catch (error) {
                console.error('[HiddenChatService] Error parsing stored salt:', error);
                // Fall through to generate new salt
            }
        }

        // Generate new salt from username + device identifier
        // Use username as identifier (unique per user, always available)
        const userData = await userDB.getUserData();
        const username = userData?.username;
        if (!username) {
            throw new Error('Username required for hidden chat salt generation');
        }

        // Create device identifier (simple hash of user agent + stored device ID)
        const deviceId = this.getDeviceIdentifier();
        const saltInput = `${username}:${deviceId}`;
        
        // Generate salt using SHA-256 of the input (deterministic per device)
        const encoder = new TextEncoder();
        const saltInputBytes = encoder.encode(saltInput);
        const hashBuffer = await crypto.subtle.digest('SHA-256', saltInputBytes);
        const salt = new Uint8Array(hashBuffer).slice(0, 16); // Use first 16 bytes as salt

        // Store salt in sessionStorage
        sessionStorage.setItem(HIDDEN_CHAT_SALT_KEY, uint8ArrayToBase64(salt));
        
        console.debug('[HiddenChatService] Generated new salt for hidden chats');
        return salt;
    }

    /**
     * Get or create device identifier for salt generation
     * Uses a stored device ID or generates one
     */
    private getDeviceIdentifier(): string {
        if (!browser) {
            return 'unknown';
        }

        const DEVICE_ID_KEY = 'openmates_device_id';
        let deviceId = localStorage.getItem(DEVICE_ID_KEY);
        
        if (!deviceId) {
            // Generate a simple device ID from user agent + random component
            const userAgent = navigator.userAgent || 'unknown';
            const random = crypto.getRandomValues(new Uint8Array(8));
            const randomHex = Array.from(random).map(b => b.toString(16).padStart(2, '0')).join('');
            deviceId = `${userAgent.substring(0, 20)}:${randomHex}`;
            localStorage.setItem(DEVICE_ID_KEY, deviceId);
        }
        
        return deviceId;
    }

    /**
     * Derive combined secret from master key + code
     * Formula: PBKDF2(master_key || code, salt)
     * 
     * @param code - 4-6 digit code entered by user
     * @returns Promise<Uint8Array | null> - Combined secret or null if derivation fails
     */
    async deriveCombinedSecret(code: string): Promise<Uint8Array | null> {
        if (!browser) {
            return null;
        }

        // Validate code format (4-6 digits)
        if (!/^\d{4,6}$/.test(code)) {
            console.error('[HiddenChatService] Invalid code format');
            return null;
        }

        // Check rate limiting
        if (this.isLockedOut()) {
            throw new Error('Too many failed attempts. Please wait before trying again.');
        }

        try {
            // Get master key
            const masterKey = await getKeyFromStorage();
            if (!masterKey) {
                console.error('[HiddenChatService] Master key not found');
                return null;
            }

            // Export master key as raw bytes
            const masterKeyBytes = await crypto.subtle.exportKey('raw', masterKey);
            const masterKeyArray = new Uint8Array(masterKeyBytes);

            // Get or create salt
            const salt = await this.getOrCreateSalt();

            // Combine master_key || code
            const encoder = new TextEncoder();
            const codeBytes = encoder.encode(code);
            const combinedInput = new Uint8Array(masterKeyArray.length + codeBytes.length);
            combinedInput.set(masterKeyArray);
            combinedInput.set(codeBytes, masterKeyArray.length);

            // Derive combined secret using PBKDF2
            // Note: Architecture doc mentions Argon2, but codebase uses PBKDF2 for consistency
            const combinedSecret = await deriveKeyFromPassword(
                uint8ArrayToBase64(combinedInput), // Convert to string for PBKDF2
                salt
            );

            // Clear master key bytes from memory
            masterKeyArray.fill(0);

            return combinedSecret;
        } catch (error) {
            console.error('[HiddenChatService] Error deriving combined secret:', error);
            this.recordFailedAttempt();
            return null;
        }
    }

    /**
     * Unlock hidden chats by deriving and storing combined secret
     * Tries to decrypt all chats that failed normal decryption with the entered code.
     * If at least one chat decrypts successfully, unlock succeeds.
     * If no chats decrypt, unlock fails (code is wrong or no chats encrypted with that code).
     * 
     * @param code - 4-6 digit code entered by user
     * @param verifiedEncryptedChatKey - Optional: If provided, verify this encrypted chat key can be decrypted with the code
     *                                   This allows unlock to succeed even if getAllChats() hasn't picked up a newly encrypted chat yet
     * @returns Promise<{ success: boolean; decryptedCount: number }> - Success status and count of decrypted chats
     */
    async unlockHiddenChats(code: string, verifiedEncryptedChatKey?: string): Promise<{ success: boolean; decryptedCount: number }> {
        if (!browser) {
            return { success: false, decryptedCount: 0 };
        }

        // Check rate limiting
        if (this.isLockedOut()) {
            throw new Error('Too many failed attempts. Please wait before trying again.');
        }

        const combinedSecret = await this.deriveCombinedSecret(code);
        if (!combinedSecret) {
            this.recordFailedAttempt();
            return { success: false, decryptedCount: 0 };
        }

        // Temporarily store combined secret to test decryption
        const tempSecret = this.combinedSecret;
        this.combinedSecret = combinedSecret;
        
        try {
            // Try to decrypt all chats that failed normal decryption (these are hidden chats)
            const { chatDB } = await import('./db');
            const allChats = await chatDB.getAllChats();
            
            let decryptedCount = 0;
            
            // Try to decrypt each chat that fails normal decryption
            for (const chat of allChats) {
                if (chat.encrypted_chat_key) {
                    try {
                        // First try normal decryption
                        await decryptChatKeyWithMasterKey(chat.encrypted_chat_key);
                        // Normal decryption succeeded, not a hidden chat - skip
                    } catch {
                        // Normal decryption failed - this might be a hidden chat
                        // Try to decrypt with combined secret
                        const decrypted = await this.decryptChatKeyWithCombinedSecret(chat.encrypted_chat_key);
                        if (decrypted) {
                            // Successfully decrypted a hidden chat with this code
                            decryptedCount++;
                        }
                    }
                }
            }
            
            // If we have a verified encrypted chat key, test it directly
            // This handles the case where we just encrypted a chat but getAllChats() hasn't picked it up yet
            if (verifiedEncryptedChatKey && decryptedCount === 0) {
                try {
                    const verifiedDecrypt = await this.decryptChatKeyWithCombinedSecret(verifiedEncryptedChatKey);
                    if (verifiedDecrypt) {
                        // The verified chat can be decrypted with this code - unlock succeeds
                        decryptedCount = 1;
                    }
                } catch (error) {
                    console.error('[HiddenChatService] Error verifying encrypted chat key:', error);
                }
            }
            
            // If we decrypted at least one chat (or verified one), unlock succeeds
            if (decryptedCount > 0) {
                // Store combined secret in volatile memory
                this.combinedSecret = combinedSecret;
                
                // Store code in sessionStorage (for convenience, not for security)
                sessionStorage.setItem(HIDDEN_CHAT_CODE_KEY, code);
                
                // Reset failed attempts on successful unlock
                this.failedAttempts = 0;
                this.lockoutUntil = null;

                console.debug(`[HiddenChatService] Hidden chats unlocked successfully: ${decryptedCount} chat(s) decrypted`);
                return { success: true, decryptedCount };
            } else {
                // No chats decrypted - code is wrong or no chats encrypted with this code
                this.combinedSecret = tempSecret; // Restore previous state
                this.recordFailedAttempt();
                console.debug('[HiddenChatService] Unlock failed: no chats could be decrypted with this code');
                return { success: false, decryptedCount: 0 };
            }
        } catch (error) {
            this.combinedSecret = tempSecret; // Restore previous state on error
            console.error('[HiddenChatService] Error during unlock:', error);
            this.recordFailedAttempt();
            return { success: false, decryptedCount: 0 };
        }
    }

    /**
     * Lock hidden chats by clearing combined secret from memory
     */
    lockHiddenChats(): void {
        if (this.combinedSecret) {
            // Clear secret from memory
            this.combinedSecret.fill(0);
            this.combinedSecret = null;
        }
        
        // Clear code from sessionStorage
        if (browser) {
            sessionStorage.removeItem(HIDDEN_CHAT_CODE_KEY);
        }

        console.debug('[HiddenChatService] Hidden chats locked');
    }

    /**
     * Check if hidden chats are currently unlocked
     */
    isUnlocked(): boolean {
        return this.combinedSecret !== null;
    }

    /**
     * Get the combined secret (only available when unlocked)
     */
    getCombinedSecret(): Uint8Array | null {
        return this.combinedSecret;
    }

    /**
     * Encrypt a chat key with the combined secret (for hidden chats)
     * @param chatKey - The chat key to encrypt
     * @returns Promise<string | null> - Base64 encoded encrypted chat key or null if encryption fails
     */
    async encryptChatKeyWithCombinedSecret(chatKey: Uint8Array): Promise<string | null> {
        if (!this.combinedSecret) {
            console.error('[HiddenChatService] Cannot encrypt: hidden chats are locked');
            return null;
        }

        try {
            // Import combined secret as CryptoKey
            const combinedSecretKey = await crypto.subtle.importKey(
                'raw',
                this.combinedSecret,
                { name: 'AES-GCM', length: 256 },
                false,
                ['encrypt', 'decrypt']
            );

            // Generate random IV
            const iv = crypto.getRandomValues(new Uint8Array(12)); // 12 bytes for GCM

            // Encrypt chat key
            const encrypted = await crypto.subtle.encrypt(
                { name: 'AES-GCM', iv },
                combinedSecretKey,
                chatKey
            );

            // Combine IV + ciphertext
            const combined = new Uint8Array(iv.length + encrypted.byteLength);
            combined.set(iv);
            combined.set(new Uint8Array(encrypted), iv.length);

            return uint8ArrayToBase64(combined);
        } catch (error) {
            console.error('[HiddenChatService] Error encrypting chat key:', error);
            return null;
        }
    }

    /**
     * Decrypt a chat key using the combined secret (for hidden chats)
     * @param encryptedChatKeyWithIV - Base64 encoded encrypted chat key with IV
     * @returns Promise<Uint8Array | null> - Decrypted chat key or null if decryption fails
     */
    async decryptChatKeyWithCombinedSecret(encryptedChatKeyWithIV: string): Promise<Uint8Array | null> {
        if (!this.combinedSecret) {
            // Not an error - hidden chats are just locked
            return null;
        }

        try {
            // Import combined secret as CryptoKey
            const combinedSecretKey = await crypto.subtle.importKey(
                'raw',
                this.combinedSecret,
                { name: 'AES-GCM', length: 256 },
                false,
                ['encrypt', 'decrypt']
            );

            // Extract IV and ciphertext
            const combined = base64ToUint8Array(encryptedChatKeyWithIV);
            const iv = combined.slice(0, 12);
            const ciphertext = combined.slice(12);

            // Decrypt chat key
            const decrypted = await crypto.subtle.decrypt(
                { name: 'AES-GCM', iv },
                combinedSecretKey,
                ciphertext
            );

            return new Uint8Array(decrypted);
        } catch (error) {
            console.error('[HiddenChatService] Error decrypting chat key:', error);
            return null;
        }
    }

    /**
     * Try to decrypt a chat key using both normal and hidden chat paths
     * This is used to detect if a chat is hidden
     * 
     * @param encryptedChatKeyWithIV - Base64 encoded encrypted chat key with IV
     * @returns Promise<{ chatKey: Uint8Array | null, isHidden: boolean }>
     */
    async tryDecryptChatKey(encryptedChatKeyWithIV: string): Promise<{ chatKey: Uint8Array | null; isHidden: boolean }> {
        // First try: Normal decryption with master key
        const normalKey = await decryptChatKeyWithMasterKey(encryptedChatKeyWithIV);
        if (normalKey) {
            return { chatKey: normalKey, isHidden: false };
        }

        // Second try: Hidden chat decryption with combined secret (if unlocked)
        if (this.combinedSecret) {
            const hiddenKey = await this.decryptChatKeyWithCombinedSecret(encryptedChatKeyWithIV);
            if (hiddenKey) {
                return { chatKey: hiddenKey, isHidden: true };
            }
        }

        // Both failed - could be corrupted or hidden chat that's locked
        return { chatKey: null, isHidden: false };
    }

    /**
     * Record a failed unlock attempt and enforce rate limiting
     */
    private recordFailedAttempt(): void {
        this.failedAttempts++;
        if (this.failedAttempts >= MAX_FAILED_ATTEMPTS) {
            this.lockoutUntil = Date.now() + LOCKOUT_DURATION_MS;
            console.warn('[HiddenChatService] Rate limit triggered after', this.failedAttempts, 'failed attempts');
        }
    }

    /**
     * Check if unlock attempts are currently locked out
     */
    private isLockedOut(): boolean {
        if (this.lockoutUntil === null) {
            return false;
        }
        
        if (Date.now() >= this.lockoutUntil) {
            // Lockout expired
            this.lockoutUntil = null;
            this.failedAttempts = 0;
            return false;
        }
        
        return true;
    }

    /**
     * Get remaining lockout time in seconds
     */
    getRemainingLockoutTime(): number {
        if (!this.isLockedOut()) {
            return 0;
        }
        return Math.ceil((this.lockoutUntil! - Date.now()) / 1000);
    }

    /**
     * Check if a stored code exists (for auto-unlock on page reload)
     */
    hasStoredCode(): boolean {
        if (!browser) {
            return false;
        }
        return sessionStorage.getItem(HIDDEN_CHAT_CODE_KEY) !== null;
    }

    /**
     * Get stored code (for auto-unlock on page reload)
     * Note: This is a convenience feature - code is stored in sessionStorage
     */
    getStoredCode(): string | null {
        if (!browser) {
            return null;
        }
        return sessionStorage.getItem(HIDDEN_CHAT_CODE_KEY);
    }

    /**
     * Encrypt a chat key with a code (for hiding a chat)
     * This derives the combined secret and encrypts the chat key without unlocking.
     * After calling this, you should call unlockHiddenChats() to unlock and show the hidden chat.
     * 
     * @param chatKey - The chat key to encrypt
     * @param code - 4-6 digit code to use for encryption
     * @returns Promise<string | null> - Encrypted chat key or null if encryption fails
     */
    async encryptChatKeyWithCode(chatKey: Uint8Array, code: string): Promise<string | null> {
        if (!browser) {
            return null;
        }

        // Derive combined secret from code
        const combinedSecret = await this.deriveCombinedSecret(code);
        if (!combinedSecret) {
            return null;
        }

        // Temporarily store combined secret to encrypt
        const tempSecret = this.combinedSecret;
        this.combinedSecret = combinedSecret;

        try {
            // Encrypt chat key with combined secret
            const encrypted = await this.encryptChatKeyWithCombinedSecret(chatKey);
            return encrypted;
        } finally {
            // Restore previous state (don't keep the secret unless unlock succeeds)
            this.combinedSecret = tempSecret;
        }
    }

}

// Export singleton instance
export const hiddenChatService = new HiddenChatService();

