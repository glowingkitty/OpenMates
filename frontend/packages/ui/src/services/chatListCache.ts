// frontend/packages/ui/src/services/chatListCache.ts
// Global cache for chat list to persist across component remounts
// This prevents unnecessary database reads when the sidebar is closed and reopened

import type { Chat, Message } from '../types/chat';

/**
 * Global cache for the full chat list and last messages.
 * This persists across component instances, so when the Chats component
 * is destroyed and recreated (when sidebar closes/opens), the cache remains.
 */
class ChatListCache {
	private cachedChats: Chat[] = [];
	private cachedChatsTimestamp = 0;
	private cacheReady = false;
	private cacheDirty = false;
	private updateInProgress = false;
	private readonly CACHE_STALE_MS = 5 * 60 * 1000; // 5 minutes
	
	// Cache for last messages per chat to avoid repeated decryption
	private lastMessageCache = new Map<string, { message: Message | null; timestamp: number }>();
	private readonly LAST_MESSAGE_CACHE_STALE_MS = 5 * 60 * 1000; // 5 minutes

	/**
	 * Set the cached chat list
	 */
	setCache(chats: Chat[]): void {
		this.cachedChats = [...chats];
		this.cachedChatsTimestamp = Date.now();
		this.cacheReady = true;
		this.cacheDirty = false;
		console.debug(`[ChatListCache] Cache updated: ${chats.length} chats, timestamp: ${this.cachedChatsTimestamp}`);
	}

	/**
	 * Get cached chats if available and fresh
	 * @param force - If true, ignore cache and return null
	 * @returns Cached chats array or null if cache miss
	 */
	getCache(force = false): Chat[] | null {
		if (!this.cacheReady) {
			console.debug('[ChatListCache] Cache not ready');
			return null;
		}
		if (!force && !this.cacheDirty && Date.now() - this.cachedChatsTimestamp < this.CACHE_STALE_MS) {
			console.debug(`[ChatListCache] Cache hit: ${this.cachedChats.length} chats (age: ${Date.now() - this.cachedChatsTimestamp}ms)`);
			return [...this.cachedChats];
		}
		console.debug(`[ChatListCache] Cache miss: force=${force}, dirty=${this.cacheDirty}, age=${Date.now() - this.cachedChatsTimestamp}ms`);
		return null;
	}

	/**
	 * Update or insert a chat in the cache
	 */
	upsertChat(chat: Chat): void {
		if (!this.cacheReady) {
			console.debug('[ChatListCache] Cache not ready, skipping upsert');
			return;
		}
		const idx = this.cachedChats.findIndex(c => c.chat_id === chat.chat_id);
		if (idx === -1) {
			this.cachedChats = [...this.cachedChats, chat];
			console.debug(`[ChatListCache] Added chat to cache: ${chat.chat_id}`);
		} else {
			const updated = [...this.cachedChats];
			updated[idx] = chat;
			this.cachedChats = updated;
			console.debug(`[ChatListCache] Updated chat in cache: ${chat.chat_id}`);
		}
		this.cacheDirty = false;
		this.cachedChatsTimestamp = Date.now();
	}

	/**
	 * Remove a chat from the cache
	 */
	removeChat(chatId: string): void {
		if (!this.cacheReady) return;
		this.cachedChats = this.cachedChats.filter(c => c.chat_id !== chatId);
		this.cacheDirty = false;
		this.cachedChatsTimestamp = Date.now();
		console.debug(`[ChatListCache] Removed chat from cache: ${chatId}`);
	}

	/**
	 * Mark cache as dirty (needs refresh)
	 */
	markDirty(): void {
		this.cacheDirty = true;
		console.debug('[ChatListCache] Cache marked as dirty');
	}

	/**
	 * Clear the entire cache (e.g., on logout)
	 */
	clear(): void {
		this.cachedChats = [];
		this.cacheReady = false;
		this.cacheDirty = false;
		this.cachedChatsTimestamp = 0;
		console.debug('[ChatListCache] Cache cleared');
	}

	/**
	 * Check if an update is in progress (prevents concurrent DB reads)
	 */
	isUpdateInProgress(): boolean {
		return this.updateInProgress;
	}

	/**
	 * Set update in progress flag
	 */
	setUpdateInProgress(inProgress: boolean): void {
		this.updateInProgress = inProgress;
		if (inProgress) {
			console.debug('[ChatListCache] Update started');
		} else {
			console.debug('[ChatListCache] Update completed');
		}
	}

	/**
	 * Get cache statistics for debugging
	 */
	getStats(): { ready: boolean; count: number; age: number; dirty: boolean } {
		return {
			ready: this.cacheReady,
			count: this.cachedChats.length,
			age: Date.now() - this.cachedChatsTimestamp,
			dirty: this.cacheDirty
		};
	}

	/**
	 * Get cached last message for a chat
	 * @param chatId The chat ID
	 * @returns Cached last message or null if not cached or stale
	 */
	getLastMessage(chatId: string): Message | null | undefined {
		const cached = this.lastMessageCache.get(chatId);
		if (!cached) {
			return undefined; // Not cached
		}
		const age = Date.now() - cached.timestamp;
		if (age > this.LAST_MESSAGE_CACHE_STALE_MS) {
			this.lastMessageCache.delete(chatId);
			return undefined; // Stale, removed from cache
		}
		console.debug(`[ChatListCache] Last message cache hit for chat ${chatId} (age: ${age}ms)`);
		return cached.message;
	}

	/**
	 * Cache the last message for a chat
	 * @param chatId The chat ID
	 * @param message The last message (or null if no messages)
	 */
	setLastMessage(chatId: string, message: Message | null): void {
		this.lastMessageCache.set(chatId, {
			message,
			timestamp: Date.now()
		});
		console.debug(`[ChatListCache] Cached last message for chat ${chatId}`);
	}

	/**
	 * Invalidate last message cache for a chat (e.g., when a new message is added)
	 * @param chatId The chat ID
	 */
	invalidateLastMessage(chatId: string): void {
		this.lastMessageCache.delete(chatId);
		console.debug(`[ChatListCache] Invalidated last message cache for chat ${chatId}`);
	}

	/**
	 * Clear all last message caches
	 */
	clearLastMessages(): void {
		this.lastMessageCache.clear();
		console.debug('[ChatListCache] Cleared all last message caches');
	}

	/**
	 * Clear the entire cache (e.g., on logout)
	 */
	clear(): void {
		this.cachedChats = [];
		this.cacheReady = false;
		this.cacheDirty = false;
		this.cachedChatsTimestamp = 0;
		this.lastMessageCache.clear();
		console.debug('[ChatListCache] Cache cleared');
	}
}

// Export singleton instance
export const chatListCache = new ChatListCache();
