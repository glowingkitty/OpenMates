// frontend/packages/ui/src/services/chatMetadataCache.ts
// In-memory cache for decrypted chat metadata to improve performance in chat lists

import { decryptWithMasterKey } from "./cryptoService";
import { chatDB } from "./db";
import { chatKeyManager } from "./encryption/ChatKeyManager";
import type { Chat } from "../types/chat";

/**
 * Represents decrypted chat metadata for display in chat lists
 */
export interface DecryptedChatMetadata {
  chat_id: string;
  title: string | null;
  draftPreview: string | null; // Decrypted draft preview text
  icon: string | null; // Decrypted icon name
  category: string | null; // Decrypted category name
  summary: string | null; // Decrypted chat summary (2-3 sentences)
  activeFocusId: string | null; // Decrypted active focus mode ID (e.g., "jobs-career_insights")
  lastDecrypted: number; // Timestamp when this metadata was last decrypted
}

/**
 * Cache configuration
 */
const CACHE_MAX_AGE_MS = 5 * 60 * 1000; // 5 minutes
const CACHE_MAX_SIZE = 1000; // Maximum number of cached entries

/**
 * Global set to track chats that have pending invalidations
 * This persists even when components are unmounted/remounted
 */
const pendingInvalidations = new Set<string>();

/**
 * In-memory cache for decrypted chat metadata
 * This avoids repeated decryption of chat titles and draft previews
 */
class ChatMetadataCache {
  private cache = new Map<string, DecryptedChatMetadata>();

  /**
   * Get decrypted metadata for a chat, using cache if available and fresh
   * @param chat The chat object to get metadata for
   * @returns Decrypted metadata or null if decryption fails
   */
  async getDecryptedMetadata(
    chat: Chat,
  ): Promise<DecryptedChatMetadata | null> {
    const chatId = chat.chat_id;

    // Check for pending invalidations and clear them
    if (pendingInvalidations.has(chatId)) {
      this.cache.delete(chatId);
      pendingInvalidations.delete(chatId);
    }

    const cachedMetadata = this.cache.get(chatId);
    const now = Date.now();

    // Check if cached metadata is still fresh
    if (
      cachedMetadata &&
      now - cachedMetadata.lastDecrypted < CACHE_MAX_AGE_MS
    ) {
      // console.debug('[ChatMetadataCache] Using cached metadata for chat:', chat.chat_id);
      return cachedMetadata;
    }

    // Decrypt and cache new metadata
    const decryptedMetadata = await this.decryptChatMetadata(chat);
    if (decryptedMetadata) {
      this.setCachedMetadata(chat.chat_id, decryptedMetadata);
    }

    return decryptedMetadata;
  }

  /**
   * Decrypt chat metadata from encrypted fields
   * @param chat The chat object with encrypted fields
   * @returns Decrypted metadata or null if decryption fails
   */
  private async decryptChatMetadata(
    chat: Chat,
  ): Promise<DecryptedChatMetadata | null> {
    try {
      // KEYS-04: getKeySync acceptable here -- sidebar render path, shows "[Encrypted]" placeholder if key unavailable.
      // Uses async getKey() fallback below for re-render when key loads from IDB.
      // Ensure chat key is loaded from encrypted_chat_key if available
      if (chat.encrypted_chat_key && !chatKeyManager.getKeySync(chat.chat_id)) {
        const { decryptChatKeyWithMasterKey } = await import("./cryptoService");
        const chatKey = await decryptChatKeyWithMasterKey(
          chat.encrypted_chat_key,
        );
        if (chatKey) {
          chatDB.setChatKey(chat.chat_id, chatKey);
        }
      }

      // Decrypt title from encrypted_title field using chat-specific key
      // KEYS-04: getKeySync acceptable here -- sidebar render path, shows placeholder if key unavailable
      let title: string | null = null;
      if (chat.encrypted_title) {
        let chatKey = chatKeyManager.getKeySync(chat.chat_id);
        // Async fallback: try loading key from IDB if not in memory cache
        if (!chatKey) {
          chatKey = await chatKeyManager.getKey(chat.chat_id);
        }
        if (chatKey) {
          const { decryptWithChatKey } = await import("./cryptoService");
          title = await decryptWithChatKey(chat.encrypted_title, chatKey);
          if (!title) {
            console.warn(
              `[ChatMetadataCache] Failed to decrypt title for chat ${chat.chat_id}`,
            );
          }
        } else {
          console.warn(
            `[ChatMetadataCache] No chat key found for chat ${chat.chat_id}, cannot decrypt title`,
          );
        }
      }

      // Decrypt draft preview with master key
      let draftPreview: string | null = null;
      if (chat.encrypted_draft_preview) {
        draftPreview = await decryptWithMasterKey(chat.encrypted_draft_preview);
      }

      // Decrypt chat-key fields in parallel — all use the same key and are independent
      let icon: string | null = null;
      // KEYS-04: getKeySync acceptable here -- sidebar render path, shows placeholder if key unavailable
      let category: string | null = null;
      let summary: string | null = null;
      let activeFocusId: string | null = null;
      let chatKey = chatKeyManager.getKeySync(chat.chat_id);
      // Async fallback: try loading key from IDB if not in memory cache
      if (!chatKey) {
        chatKey = await chatKeyManager.getKey(chat.chat_id);
      }
      if (chatKey) {
        const { decryptWithChatKey } = await import("./cryptoService");

        const [iconResult, categoryResult, summaryResult, focusResult] =
          await Promise.all([
            chat.encrypted_icon
              ? decryptWithChatKey(chat.encrypted_icon, chatKey)
              : null,
            chat.encrypted_category
              ? decryptWithChatKey(chat.encrypted_category, chatKey)
              : null,
            chat.encrypted_chat_summary
              ? decryptWithChatKey(chat.encrypted_chat_summary, chatKey)
              : null,
            chat.encrypted_active_focus_id
              ? decryptWithChatKey(chat.encrypted_active_focus_id, chatKey)
              : null,
          ]);

        icon = iconResult;
        category = categoryResult;
        summary = summaryResult;
        activeFocusId = focusResult;
      }

      return {
        chat_id: chat.chat_id,
        title,
        draftPreview,
        icon,
        category,
        summary,
        activeFocusId,
        lastDecrypted: Date.now(),
      };
    } catch (error) {
      console.error(
        "[ChatMetadataCache] Error decrypting chat metadata:",
        error,
      );
      return null;
    }
  }

  /**
   * Set cached metadata for a chat
   * @param chatId The chat ID
   * @param metadata The decrypted metadata to cache
   */
  private setCachedMetadata(
    chatId: string,
    metadata: DecryptedChatMetadata,
  ): void {
    // Implement simple LRU eviction if cache is full
    if (this.cache.size >= CACHE_MAX_SIZE) {
      // Remove oldest entry (first in the Map)
      const firstKey = this.cache.keys().next().value;
      if (firstKey) {
        this.cache.delete(firstKey);
      }
    }

    this.cache.set(chatId, metadata);
  }

  /**
   * Invalidate cached metadata for a specific chat
   * Call this when a chat's encrypted data changes
   * @param chatId The chat ID to invalidate
   */
  invalidateChat(chatId: string): void {
    this.cache.delete(chatId);
    // Track this invalidation globally in case components are unmounted
    pendingInvalidations.add(chatId);
  }

  /**
   * Clear all cached metadata
   * Call this when the user logs out or master key changes
   */
  clearAll(): void {
    this.cache.clear();
  }

  /**
   * Get cache statistics for debugging
   */
  getCacheStats(): { size: number; maxSize: number; maxAgeMs: number } {
    return {
      size: this.cache.size,
      maxSize: CACHE_MAX_SIZE,
      maxAgeMs: CACHE_MAX_AGE_MS,
    };
  }

  /**
   * Clean up expired entries from the cache
   * This method can be called periodically to prevent memory buildup
   */
  cleanupExpired(): void {
    const now = Date.now();
    const expiredKeys: string[] = [];

    // Use Array.from to avoid iterator issues
    for (const [chatId, metadata] of Array.from(this.cache.entries())) {
      if (now - metadata.lastDecrypted >= CACHE_MAX_AGE_MS) {
        expiredKeys.push(chatId);
      }
    }

    for (const key of expiredKeys) {
      this.cache.delete(key);
    }

    // Expired entry cleanup is silent — only errors are worth logging
  }
}

// Export a singleton instance
export const chatMetadataCache = new ChatMetadataCache();

// Set up periodic cleanup of expired entries (every 2 minutes)
setInterval(
  () => {
    chatMetadataCache.cleanupExpired();
  },
  2 * 60 * 1000,
);
