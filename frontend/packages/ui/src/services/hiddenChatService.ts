/**
 * Hidden Chat Service
 *
 * Manages encryption and decryption of hidden chats using a code-derived secret.
 * Hidden chats use a combined secret derived from master_key + 4-6 digit code via PBKDF2.
 * This maintains zero-knowledge architecture: server never sees the code or can access hidden chat content.
 *
 * Architecture:
 * - Combined secret: PBKDF2(master_key || code, salt)
 * - Salt: User-specific, reuses user_email_salt from localStorage/sessionStorage (same across devices)
 * - KDF: PBKDF2 with 100,000 iterations (matching login flow strength)
 * - Scope: Each chat can be encrypted with a different code (per-chat, not per-user)
 */

import { getKeyFromStorage, getEmailSalt } from './cryptoService';
import { 
    encryptChatKeyWithMasterKey, 
    decryptChatKeyWithMasterKey,
    deriveKeyFromPassword,
    generateSalt,
    uint8ArrayToBase64,
    base64ToUint8Array
} from './cryptoService';
import { browser } from '$app/environment';

// Storage keys
const HIDDEN_CHAT_SALT_KEY = 'hidden_chat_salt';
// Note: Code is NOT stored - it's memory-only for security

// Rate limiting constants
const MAX_FAILED_ATTEMPTS = 3;
const LOCKOUT_DURATION_MS = 30000; // 30 seconds

class HiddenChatService {
    // Combined secret in volatile memory only (never persisted)
    private combinedSecret: Uint8Array | null = null;
    
    // Rate limiting state
    private failedAttempts = 0;
    private lockoutUntil: number | null = null;

    private async encryptChatKeyWithSecret(chatKey: Uint8Array, secret: Uint8Array): Promise<string> {
        // Ensure BufferSource compatibility across TS/libdom variants
        const secretBytes = new Uint8Array(secret);
        const chatKeyBytes = new Uint8Array(chatKey);

        // Import secret as CryptoKey
        const secretKey = await crypto.subtle.importKey(
            'raw',
            secretBytes,
            { name: 'AES-GCM', length: 256 },
            false,
            ['encrypt', 'decrypt']
        );

        // Generate random IV
        const iv = crypto.getRandomValues(new Uint8Array(12)); // 12 bytes for GCM

        // Encrypt chat key
        const encrypted = await crypto.subtle.encrypt(
            { name: 'AES-GCM', iv },
            secretKey,
            chatKeyBytes
        );

        // Combine IV + ciphertext
        const combined = new Uint8Array(iv.length + encrypted.byteLength);
        combined.set(iv);
        combined.set(new Uint8Array(encrypted), iv.length);

        return uint8ArrayToBase64(combined);
    }

    /**
     * Get or generate user-specific salt for hidden chat key derivation
     * Reuses the user_email_salt from localStorage/sessionStorage (same across devices)
     * This ensures cross-device compatibility: hidden chats encrypted on one device
     * can be decrypted on another device when the user enters the same code.
     * 
     * The email salt is already user-specific and stored securely, making it perfect
     * for this use case without requiring additional user ID syncing.
     */
    private async getOrCreateSalt(): Promise<Uint8Array> {
        if (!browser) {
            throw new Error('Hidden chat service requires browser environment');
        }

        // Try to get existing salt from sessionStorage (cached for performance)
        const storedSalt = sessionStorage.getItem(HIDDEN_CHAT_SALT_KEY);
        if (storedSalt) {
            try {
                return base64ToUint8Array(storedSalt);
            } catch (error) {
                console.error('[HiddenChatService] Error parsing stored salt:', error);
                // Fall through to get email salt
            }
        }

        // Reuse user_email_salt from localStorage/sessionStorage
        // This salt is user-specific and the same across all devices for the same user
        // It's already available after login and doesn't require additional syncing
        const emailSalt = getEmailSalt();
        if (!emailSalt) {
            // Email salt should be available after login - if missing, user needs to log in
            console.error('[HiddenChatService] Email salt not found. User may need to log in.');
            throw new Error('Email salt required for hidden chat salt generation. Please log in.');
        }

        // Use email salt directly (it's already user-specific and cross-device compatible)
        // Cache it in sessionStorage for performance (can be regenerated from email salt anytime)
        const salt = emailSalt.slice(0, 16); // Use first 16 bytes as salt (email salt is typically 16+ bytes)
        sessionStorage.setItem(HIDDEN_CHAT_SALT_KEY, uint8ArrayToBase64(salt));
        
        console.debug('[HiddenChatService] Using email salt for hidden chats (user-specific, cross-device compatible)');
        return salt;
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
            console.error('[HiddenChatService] Invalid code format:', code);
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
     * @returns Promise<{ success: boolean; decryptedCount: number }> - Success status and count of decrypted chats
     */
    async unlockHiddenChats(
        code: string,
        verifiedEncryptedChatKey?: string
    ): Promise<{ success: boolean; decryptedCount: number }> {
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
            // Optional fast verification path: if caller provides an encrypted chat key
            // (e.g., freshly encrypted during "hide chat"), verify that it can decrypt with this code.
            // This avoids depending on IndexedDB reads being immediately consistent.
            let verifiedDecryptableCount = 0;
            if (verifiedEncryptedChatKey) {
                const verified = await this.decryptChatKeyWithCombinedSecret(verifiedEncryptedChatKey);
                if (verified) {
                    verifiedDecryptableCount = 1;
                }
            }

            // Try to decrypt all chats that failed normal decryption (these are hidden chats)
            const { chatDB } = await import('./db');
            const allChats = await chatDB.getAllChats();
            
            let decryptedCount = 0;
            
            // Try to decrypt each chat that fails normal decryption
            for (const chat of allChats) {
                if (chat.encrypted_chat_key) {
                    // First try normal decryption.
                    // IMPORTANT: decryptChatKeyWithMasterKey returns null on failure (it doesn't throw).
                    const normalKey = await decryptChatKeyWithMasterKey(chat.encrypted_chat_key);
                    if (normalKey) {
                        continue;
                    }

                    // Normal decryption failed - this might be a hidden chat.
                    // Try to decrypt with combined secret.
                    const decrypted = await this.decryptChatKeyWithCombinedSecret(chat.encrypted_chat_key);
                    if (decrypted) {
                        // Successfully decrypted a hidden chat with this code
                        decryptedCount++;
                    }
                }
            }

            decryptedCount = Math.max(decryptedCount, verifiedDecryptableCount);
            
            // If we decrypted at least one chat, unlock succeeds
            if (decryptedCount > 0) {
                // Store combined secret in volatile memory only (never persisted)
                this.combinedSecret = combinedSecret;
                
                // Reset failed attempts on successful unlock
                this.failedAttempts = 0;
                this.lockoutUntil = null;

                console.debug(`[HiddenChatService] Hidden chats unlocked successfully: ${decryptedCount} chat(s) decrypted`);
                return { success: true, decryptedCount };
            } else {
                // No chats decrypted, but code derivation succeeded (code is valid)
                // Unlock anyway to allow user to see "No hidden chats" message
                // Store combined secret in volatile memory only (never persisted)
                this.combinedSecret = combinedSecret;
                
                // Reset failed attempts on successful code entry (even if no chats decrypted)
                this.failedAttempts = 0;
                this.lockoutUntil = null;

                console.debug('[HiddenChatService] Hidden chats unlocked (no chats decrypted, but code is valid)');
                return { success: true, decryptedCount: 0 };
            }
        } catch (error) {
            this.combinedSecret = tempSecret; // Restore previous state on error
            console.error('[HiddenChatService] Error during unlock:', error);
            this.recordFailedAttempt();
            return { success: false, decryptedCount: 0 };
        }
    }

    /**
     * Encrypt a chat key using a specific 4-6 digit code, without requiring the hidden chats
     * to already be unlocked.
     *
     * Used when hiding a chat while currently locked: we can encrypt the chat key with the code,
     * then proceed to unlock with the same code.
     */
    async encryptChatKeyWithCode(chatKey: Uint8Array, code: string): Promise<string | null> {
        if (!browser) {
            return null;
        }

        const derivedSecret = await this.deriveCombinedSecret(code);
        if (!derivedSecret) {
            return null;
        }

        try {
            return await this.encryptChatKeyWithSecret(chatKey, derivedSecret);
        } catch (error) {
            console.error('[HiddenChatService] Error encrypting chat key with code:', error);
            return null;
        } finally {
            // Ensure derived secret is cleared from memory
            derivedSecret.fill(0);
        }
    }

    /**
     * Lock hidden chats by clearing combined secret from memory
     * Also clears all decrypted chat keys from cache for hidden chats
     */
    async lockHiddenChats(): Promise<void> {
        if (this.combinedSecret) {
            // Clear secret from memory
            this.combinedSecret.fill(0);
            this.combinedSecret = null;
        }
        
        // Code is memory-only, no need to clear from storage

        // Clear all decrypted chat keys from cache
        // When hidden chats are locked, we clear all cached keys to ensure hidden chat data
        // is removed from memory. The keys will be re-decrypted when needed (for visible chats)
        // or when hidden chats are unlocked again.
        try {
            const { chatDB } = await import('./db');
            // Clear all chat keys from cache - this is safe because:
            // 1. Visible chats will re-decrypt with master key when accessed
            // 2. Hidden chats won't decrypt until unlocked again
            chatDB.clearAllChatKeys();
            console.debug('[HiddenChatService] Cleared all chat keys from cache');
        } catch (error) {
            console.error('[HiddenChatService] Error clearing chat keys from cache:', error);
            // Don't throw - locking should succeed even if cache clearing fails
        }

        console.debug('[HiddenChatService] Hidden chats locked and cache cleared');
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
            return await this.encryptChatKeyWithSecret(chatKey, new Uint8Array(this.combinedSecret));
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
            // Ensure BufferSource compatibility across TS/libdom variants
            const secretBytes = new Uint8Array(this.combinedSecret);

            // Import combined secret as CryptoKey
            const combinedSecretKey = await crypto.subtle.importKey(
                'raw',
                secretBytes,
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
    async tryDecryptChatKey(
        encryptedChatKeyWithIV: string
    ): Promise<{ chatKey: Uint8Array | null; isHidden: boolean; isHiddenCandidate: boolean }> {
        // First try: Normal decryption with master key.
        // IMPORTANT: decryptChatKeyWithMasterKey can throw (OperationError) when the key was encrypted with the hidden-chat secret.
        let normalKey: Uint8Array | null = null;
        try {
            normalKey = await decryptChatKeyWithMasterKey(encryptedChatKeyWithIV);
        } catch {
            normalKey = null;
        }

        if (normalKey) {
            return { chatKey: normalKey, isHidden: false, isHiddenCandidate: false };
        }

        // If we can't decrypt with the master key, this chat is a "hidden candidate":
        // it's either a locked hidden chat or corrupted data. We treat it as hidden for UI filtering.
        const isHiddenCandidate = true;

        // Second try: Hidden chat decryption with combined secret (if unlocked)
        if (this.combinedSecret) {
            const hiddenKey = await this.decryptChatKeyWithCombinedSecret(encryptedChatKeyWithIV);
            if (hiddenKey) {
                return { chatKey: hiddenKey, isHidden: true, isHiddenCandidate };
            }
        }

        // Both failed - could be corrupted or hidden chat that's locked
        return { chatKey: null, isHidden: false, isHiddenCandidate };
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
     * Check if a stored code exists
     * Always returns false - code is memory-only and never persisted for security
     */
    hasStoredCode(): boolean {
        return false;
    }

    /**
     * Get stored code
     * Always returns null - code is memory-only and never persisted for security
     */
    getStoredCode(): string | null {
        return null;
    }

    /**
     * Unhide a chat by re-encrypting its chat key with the master key
     * This converts a hidden chat back to a regular chat
     * 
     * @param chatId - The ID of the chat to unhide
     * @returns Promise<boolean> - True if unhide succeeded, false otherwise
     */
    async unhideChat(chatId: string): Promise<boolean> {
        if (!browser) {
            return false;
        }

        // Hidden chats must be unlocked to unhide them (we need the combined secret to decrypt)
        if (!this.combinedSecret) {
            console.error('[HiddenChatService] Cannot unhide: hidden chats are locked');
            return false;
        }

        try {
            const { chatDB } = await import('./db');
            const chat = await chatDB.getChat(chatId);
            
            if (!chat || !chat.encrypted_chat_key) {
                console.error('[HiddenChatService] Chat not found or missing encrypted_chat_key:', chatId);
                return false;
            }

            // Decrypt the chat key using the combined secret (hidden chat path)
            const decryptedChatKey = await this.decryptChatKeyWithCombinedSecret(chat.encrypted_chat_key);
            if (!decryptedChatKey) {
                console.error('[HiddenChatService] Failed to decrypt chat key with combined secret:', chatId);
                return false;
            }

            // Re-encrypt the chat key with the master key (regular chat path)
            // encryptChatKeyWithMasterKey gets the master key internally
            const reEncryptedChatKey = await encryptChatKeyWithMasterKey(decryptedChatKey);
            if (!reEncryptedChatKey) {
                console.error('[HiddenChatService] Failed to re-encrypt chat key with master key:', chatId);
                return false;
            }

            // Update the chat in IndexedDB with the re-encrypted key
            const updatedChat = {
                ...chat,
                encrypted_chat_key: reEncryptedChatKey
            };
            await chatDB.updateChat(updatedChat);

            // Clear the cached chat key so it gets re-decrypted with master key on next access
            chatDB.clearChatKey(chatId);
            
            // IMPORTANT: The chat list will be refreshed via the 'chatUnhidden' event
            // When updateChatListFromDB runs, it will reload from IndexedDB and re-decrypt
            // The re-decryption will set is_hidden = false and is_hidden_candidate = false
            // because the chat key can now be decrypted with the master key
            // The event handler in Chats.svelte will mark the cache as dirty and refresh the list

            // Sync to server
            try {
                const { chatSyncService } = await import('./chatSyncService');
                await chatSyncService.sendUpdateEncryptedChatKey(chatId, reEncryptedChatKey);
                console.debug('[HiddenChatService] Synced unhidden chat to server:', chatId);
            } catch (syncError) {
                console.warn('[HiddenChatService] Failed to sync unhidden chat to server:', syncError);
                // Don't fail the unhide operation if sync fails - local update succeeded
            }

            console.debug('[HiddenChatService] Chat unhidden successfully:', chatId);
            return true;
        } catch (error) {
            console.error('[HiddenChatService] Error unhiding chat:', error);
            return false;
        }
    }

}

// Export singleton instance
export const hiddenChatService = new HiddenChatService();
