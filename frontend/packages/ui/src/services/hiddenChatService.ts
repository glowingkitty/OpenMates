/**
 * Hidden Chat Service
 *
 * Manages encryption and decryption of hidden chats using a password-derived secret.
 * Hidden chats use a combined secret derived from master_key + password (4-30 characters) via PBKDF2.
 * This maintains zero-knowledge architecture: server never sees the password or can access hidden chat content.
 *
 * Architecture:
 * - Combined secret: PBKDF2(master_key || code, salt)
 * - Salt: User-specific, reuses user_email_salt from localStorage/sessionStorage (same across devices)
 * - KDF: PBKDF2 with 100,000 iterations (matching login flow strength)
 * - Scope: Each chat can be encrypted with a different password (per-chat, not per-user)
 */

import { decryptChatKeyWithMasterKey } from "./cryptoService";
import { browser } from "$app/environment";
import { hiddenLockMirror } from "./rustCore/chatState/hiddenLockMirror";

class HiddenChatService {
  /**
   * Unlock hidden chats. The combined secret never leaves the Rust Worker; the Worker derives it,
   * tries every non-master-wrapped chat key and applies the rate limit.
   *
   * @param password - Password (4-30 characters) entered by user
   * @returns Promise<{ success: boolean; decryptedCount: number }> - Success status and count of decrypted chats
   */
  async unlockHiddenChats(
    password: string,
    verifiedEncryptedChatKey?: string,
  ): Promise<{ success: boolean; decryptedCount: number }> {
    const rust = await import("./rustCore/chatState/rustHiddenChat");
    const { chatDB } = await import("./db");
    const allChats = await chatDB.getAllChats();
    const keys = allChats.flatMap((chat) => (chat.encrypted_chat_key ? [chat.encrypted_chat_key] : []));
    return rust.rustHiddenUnlock(password, keys, verifiedEncryptedChatKey);
  }

  /**
   * Encrypt a chat key using a specific password (4-30 characters), without requiring the hidden chats
   * to already be unlocked.
   *
   * Used when hiding a chat while currently locked: we can encrypt the chat key with the password,
   * then proceed to unlock with the same password.
   */
  async encryptChatKeyWithCode(
    chatKey: Uint8Array,
    password: string,
  ): Promise<string | null> {
    const rust = await import("./rustCore/chatState/rustHiddenChat");
    return rust.rustHiddenWrapWithCode(chatKey, password);
  }

  /**
   * Lock hidden chats (the combined secret is cleared inside the Rust Worker)
   * Also clears all decrypted chat keys from cache for hidden chats
   */
  async lockHiddenChats(): Promise<void> {
    await (await import("./rustCore/chatState/rustHiddenChat")).rustHiddenLock();

    // Code is memory-only, no need to clear from storage

    // Clear all decrypted chat keys from cache
    // When hidden chats are locked, we clear all cached keys to ensure hidden chat data
    // is removed from memory. The keys will be re-decrypted when needed (for visible chats)
    // or when hidden chats are unlocked again.
    try {
      const { chatDB } = await import("./db");
      // Clear all chat keys from cache - this is safe because:
      // 1. Visible chats will re-decrypt with master key when accessed
      // 2. Hidden chats won't decrypt until unlocked again
      chatDB.clearAllChatKeys();
      console.debug("[HiddenChatService] Cleared all chat keys from cache");
    } catch (error) {
      console.error(
        "[HiddenChatService] Error clearing chat keys from cache:",
        error,
      );
      // Don't throw - locking should succeed even if cache clearing fails
    }

    console.debug("[HiddenChatService] Hidden chats locked and cache cleared");
  }

  /**
   * Check if hidden chats are currently unlocked
   */
  isUnlocked(): boolean {
    return hiddenLockMirror.unlocked;
  }

  /**
   * Get the combined secret (only available when unlocked)
   */
  getCombinedSecret(): Uint8Array | null {
    // The combined secret never leaves the Rust Worker.
    return null;
  }

  /**
   * Encrypt a chat key with the combined secret (for hidden chats)
   * @param chatKey - The chat key to encrypt
   * @returns Promise<string | null> - Base64 encoded encrypted chat key or null if encryption fails
   */
  async encryptChatKeyWithCombinedSecret(
    chatKey: Uint8Array,
  ): Promise<string | null> {
    return (await import("./rustCore/chatState/rustHiddenChat")).rustHiddenWrap(chatKey);
  }

  /**
   * Decrypt a chat key using the combined secret (for hidden chats)
   * @param encryptedChatKeyWithIV - Base64 encoded encrypted chat key with IV
   * @param _chatId - Optional chat ID (kept for callers; unused by the Rust unwrap)
   * @returns Promise<Uint8Array | null> - Decrypted chat key or null if decryption fails
   */
  async decryptChatKeyWithCombinedSecret(
    encryptedChatKeyWithIV: string,
    _chatId?: string,
  ): Promise<Uint8Array | null> {
    return (await import("./rustCore/chatState/rustHiddenChat")).rustHiddenUnwrap(encryptedChatKeyWithIV);
  }

  /**
   * Try to decrypt a chat key using both normal and hidden chat paths
   * This is used to detect if a chat is hidden
   *
   * @param encryptedChatKeyWithIV - Base64 encoded encrypted chat key with IV
   * @returns Promise<{ chatKey: Uint8Array | null, isHidden: boolean }>
   */
  async tryDecryptChatKey(encryptedChatKeyWithIV: string): Promise<{
    chatKey: Uint8Array | null;
    isHidden: boolean;
    isHiddenCandidate: boolean;
  }> {
    // Ordinary chats open with the master key (keys lane) without a Worker round trip;
    // only the hidden-secret path (and its classification) is decided in Rust.
    let ordinaryKey: Uint8Array | null = null;
    try {
      ordinaryKey = await decryptChatKeyWithMasterKey(encryptedChatKeyWithIV);
    } catch {
      ordinaryKey = null;
    }
    if (ordinaryKey) return { chatKey: ordinaryKey, isHidden: false, isHiddenCandidate: false };
    if (!hiddenLockMirror.unlocked) return { chatKey: null, isHidden: false, isHiddenCandidate: true };
    return (await import("./rustCore/chatState/rustHiddenChat")).rustHiddenTryDecrypt(encryptedChatKeyWithIV);
  }

  /**
   * Get remaining lockout time in seconds
   */
  getRemainingLockoutTime(): number {
    return hiddenLockMirror.lockoutSeconds();
  }

  /**
   * Check if a stored password exists
   * Always returns false - password is memory-only and never persisted for security
   */
  hasStoredPassword(): boolean {
    return false;
  }

  /**
   * Get stored password
   * Always returns null - password is memory-only and never persisted for security
   */
  getStoredPassword(): string | null {
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

    // Hidden chats must be unlocked (the Worker vault holds the secret) to unhide them.
    if (!hiddenLockMirror.unlocked) {
      console.error("[HiddenChatService] Cannot unhide: hidden chats are locked");
      return false;
    }

    try {
      const { chatDB } = await import("./db");
      const chat = await chatDB.getChat(chatId);

      if (!chat || !chat.encrypted_chat_key) {
        console.error(
          "[HiddenChatService] Chat not found or missing encrypted_chat_key:",
          chatId,
        );
        return false;
      }

      // The Rust Worker re-wraps the hidden chat key with the master key.
      const rust = await import("./rustCore/chatState/rustHiddenChat");
      const rewrapped = await rust.rustHiddenUnhide(chat.encrypted_chat_key);
      if (!rewrapped) return false;
      await chatDB.updateChat({ ...chat, encrypted_chat_key: rewrapped });
      chatDB.clearChatKey(chatId);
      try {
        const { chatSyncService } = await import("./chatSyncService");
        await chatSyncService.sendUpdateEncryptedChatKey(chatId, rewrapped);
      } catch (syncError) {
        console.warn("[HiddenChatService] Failed to sync unhidden chat to server:", syncError);
      }
      return true;
    } catch (error) {
      console.error("[HiddenChatService] Error unhiding chat:", error);
      return false;
    }
  }
}

// Export singleton instance
export const hiddenChatService = new HiddenChatService();
