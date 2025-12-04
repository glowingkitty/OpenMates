// frontend/packages/ui/src/services/chatMetadataCache.ts
// In-memory cache for decrypted chat metadata to improve performance in chat lists

import { decryptWithMasterKey } from './cryptoService';
import { chatDB } from './db';
import type { Chat } from '../types/chat';

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
    async getDecryptedMetadata(chat: Chat): Promise<DecryptedChatMetadata | null> {
        const chatId = chat.chat_id;
        
        // Check for pending invalidations and clear them
        if (pendingInvalidations.has(chatId)) {
            console.debug('[ChatMetadataCache] Processing pending invalidation for chat:', chatId);
            this.cache.delete(chatId);
            pendingInvalidations.delete(chatId);
        }
        
        const cachedMetadata = this.cache.get(chatId);
        const now = Date.now();
        
        // Check if cached metadata is still fresh
        if (cachedMetadata && (now - cachedMetadata.lastDecrypted) < CACHE_MAX_AGE_MS) {
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
    private async decryptChatMetadata(chat: Chat): Promise<DecryptedChatMetadata | null> {
        try {
            console.debug('[ChatMetadataCache] Decrypting metadata for chat:', chat.chat_id, {
                hasEncryptedTitle: !!chat.encrypted_title,
                hasEncryptedChatKey: !!chat.encrypted_chat_key
            });
            
            // Ensure chat key is loaded from encrypted_chat_key if available
            if (chat.encrypted_chat_key && !chatDB.getChatKey(chat.chat_id)) {
                const { decryptChatKeyWithMasterKey } = await import('./cryptoService');
                const chatKey = decryptChatKeyWithMasterKey(chat.encrypted_chat_key);
                if (chatKey) {
                    // Store the chat key in the database service's cache
                    chatDB.setChatKey(chat.chat_id, chatKey);
                    console.debug(`[ChatMetadataCache] Loaded chat key for chat ${chat.chat_id}`);
                }
            }
            
            // Decrypt title from encrypted_title field using chat-specific key
            let title: string | null = null;
            if (chat.encrypted_title) {
                // Get chat key for decryption (should be available after decryptChatFromStorage)
                const chatKey = chatDB.getChatKey(chat.chat_id);
                console.debug(`[ChatMetadataCache] Chat key from cache: ${!!chatKey}`);
                
                if (chatKey) {
                    const { decryptWithChatKey } = await import('./cryptoService');
                    // CRITICAL FIX: await decryptWithChatKey since it's async to prevent storing Promises
                    title = await decryptWithChatKey(chat.encrypted_title, chatKey);
                    if (title) {
                        console.debug(`[ChatMetadataCache] Successfully decrypted title for chat ${chat.chat_id}: ${title.substring(0, 50)}...`);
                    } else {
                        console.warn(`[ChatMetadataCache] Failed to decrypt title for chat ${chat.chat_id}`);
                    }
                } else {
                    console.warn(`[ChatMetadataCache] No chat key found for chat ${chat.chat_id}, cannot decrypt title`);
                }
            } else {
                // No encrypted title - this is normal for new chats
                console.debug(`[ChatMetadataCache] No encrypted title for chat ${chat.chat_id} - will use fallback in UI`);
            }
            
            // CRITICAL FIX: await decryptWithMasterKey since it's async to prevent storing Promises (causes "[object Promise]" in UI)
            // Decrypt draft preview
            let draftPreview: string | null = null;
            if (chat.encrypted_draft_preview) {
                draftPreview = await decryptWithMasterKey(chat.encrypted_draft_preview);
                // console.debug('[ChatMetadataCache] Decrypted draft preview:', {
                //     chatId: chat.chat_id,
                //     previewLength: draftPreview?.length || 0,
                //     preview: draftPreview?.substring(0, 50) + (draftPreview && draftPreview.length > 50 ? '...' : '')
                // });
            }
            
            // Decrypt icon, category, and summary with chat-specific key
            let icon: string | null = null;
            let category: string | null = null;
            let summary: string | null = null;
            const chatKey = chatDB.getChatKey(chat.chat_id);
            if (chatKey) {
                const { decryptWithChatKey } = await import('./cryptoService');

                if (chat.encrypted_icon) {
                    // CRITICAL FIX: await decryptWithChatKey since it's async to prevent storing Promises
                    icon = await decryptWithChatKey(chat.encrypted_icon, chatKey);
                    console.debug(`[ChatMetadataCache] Decrypted icon for chat ${chat.chat_id}: ${icon}`);
                }

                if (chat.encrypted_category) {
                    // CRITICAL FIX: await decryptWithChatKey since it's async to prevent storing Promises
                    category = await decryptWithChatKey(chat.encrypted_category, chatKey);
                    console.debug(`[ChatMetadataCache] Decrypted category for chat ${chat.chat_id}: ${category}`);
                }

                if (chat.encrypted_chat_summary) {
                    // CRITICAL FIX: await decryptWithChatKey since it's async to prevent storing Promises
                    summary = await decryptWithChatKey(chat.encrypted_chat_summary, chatKey);
                    console.debug(`[ChatMetadataCache] Decrypted summary for chat ${chat.chat_id}: ${summary?.substring(0, 50)}...`);
                }
            }

            return {
                chat_id: chat.chat_id,
                title,
                draftPreview,
                icon,
                category,
                summary,
                lastDecrypted: Date.now()
            };
        } catch (error) {
            console.error('[ChatMetadataCache] Error decrypting chat metadata:', error);
            return null;
        }
    }
    
    /**
     * Set cached metadata for a chat
     * @param chatId The chat ID
     * @param metadata The decrypted metadata to cache
     */
    private setCachedMetadata(chatId: string, metadata: DecryptedChatMetadata): void {
        // Implement simple LRU eviction if cache is full
        if (this.cache.size >= CACHE_MAX_SIZE) {
            // Remove oldest entry (first in the Map)
            const firstKey = this.cache.keys().next().value;
            if (firstKey) {
                this.cache.delete(firstKey);
                console.debug('[ChatMetadataCache] Evicted oldest cache entry:', firstKey);
            }
        }
        
        this.cache.set(chatId, metadata);
        console.debug('[ChatMetadataCache] Cached metadata for chat:', chatId);
    }
    
    /**
     * Invalidate cached metadata for a specific chat
     * Call this when a chat's encrypted data changes
     * @param chatId The chat ID to invalidate
     */
    invalidateChat(chatId: string): void {
        if (this.cache.has(chatId)) {
            this.cache.delete(chatId);
            console.debug('[ChatMetadataCache] Invalidated cache for chat:', chatId);
        }
        // Track this invalidation globally in case components are unmounted
        pendingInvalidations.add(chatId);
    }
    
    /**
     * Clear all cached metadata
     * Call this when the user logs out or master key changes
     */
    clearAll(): void {
        this.cache.clear();
        console.debug('[ChatMetadataCache] Cleared all cached metadata');
    }
    
    /**
     * Get cache statistics for debugging
     */
    getCacheStats(): { size: number; maxSize: number; maxAgeMs: number } {
        return {
            size: this.cache.size,
            maxSize: CACHE_MAX_SIZE,
            maxAgeMs: CACHE_MAX_AGE_MS
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
            if ((now - metadata.lastDecrypted) >= CACHE_MAX_AGE_MS) {
                expiredKeys.push(chatId);
            }
        }
        
        for (const key of expiredKeys) {
            this.cache.delete(key);
        }
        
        if (expiredKeys.length > 0) {
            console.debug('[ChatMetadataCache] Cleaned up expired entries:', expiredKeys.length);
        }
    }
}

// Export a singleton instance
export const chatMetadataCache = new ChatMetadataCache();

// Set up periodic cleanup of expired entries (every 2 minutes)
setInterval(() => {
    chatMetadataCache.cleanupExpired();
}, 2 * 60 * 1000);
