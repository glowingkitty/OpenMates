/**
 * Active Chat Store
 * 
 * Maintains the currently active/selected chat ID across component lifecycle.
 * This ensures the chat list can correctly highlight the active chat even when
 * the Chats panel is closed and reopened.
 * 
 * Also manages URL hash to allow users to share/bookmark specific chats.
 * Format: #chat-id={chatId}
 */

import { writable } from 'svelte/store';
import { browser } from '$app/environment';

/**
 * Flag to prevent hashchange events from triggering when we programmatically update the hash
 * This prevents infinite loops when setActiveChat updates the hash
 * Uses a timestamp to track when we last updated the hash programmatically
 */
let lastProgrammaticHashUpdate = 0;
const PROGRAMMATIC_UPDATE_WINDOW_MS = 100; // Window to ignore hashchange events after programmatic update

/**
 * Update the URL hash with the chat ID
 * Format: #chat-id={chatId}
 * Only updates if the hash doesn't already match to prevent unnecessary hashchange events
 */
function updateUrlHash(chatId: string | null) {
	if (!browser) return; // Only update URL in browser environment
	
	const currentHash = window.location.hash;
	const expectedHash = chatId ? `#chat-id=${chatId}` : '';
	
	// Only update if hash doesn't already match (prevents unnecessary hashchange events)
	if (currentHash === expectedHash) {
		return; // Hash already matches, no update needed
	}
	
	// Record timestamp of programmatic update
	lastProgrammaticHashUpdate = Date.now();
	
	if (chatId) {
		// Set hash to #chat-id={chatId}
		window.location.hash = `chat-id=${chatId}`;
	} else {
		// Clear hash if no chat is selected
		// Use replaceState to avoid adding to browser history
		if (window.location.hash.startsWith('#chat-id=')) {
			window.history.replaceState(null, '', window.location.pathname + window.location.search);
		}
	}
}

/**
 * Check if a hashchange event was triggered by our programmatic update
 * This allows hashchange handlers to ignore programmatic updates
 * Uses a time window to account for async hashchange event firing
 */
export function isProgrammaticHashUpdate(): boolean {
	const timeSinceUpdate = Date.now() - lastProgrammaticHashUpdate;
	return timeSinceUpdate < PROGRAMMATIC_UPDATE_WINDOW_MS;
}

/**
 * Read chat ID from URL hash
 * Returns the chat ID if found, null otherwise
 */
function readChatIdFromHash(): string | null {
	if (!browser) return null;
	
	const hash = window.location.hash;
	if (hash.startsWith('#chat-id=')) {
		const chatId = hash.substring('#chat-id='.length);
		return chatId || null;
	}
	
	return null;
}

/**
 * Store for tracking the currently active chat ID
 * Persists across component mount/unmount cycles
 * Also syncs with URL hash for shareable/bookmarkable chat links
 */
function createActiveChatStore() {
	// Initialize with chat ID from URL hash if present
	const initialChatId = readChatIdFromHash();
	const { subscribe, set, update } = writable<string | null>(initialChatId);

	return {
		subscribe,
		
		/**
		 * Set the currently active chat ID
		 * Also updates the URL hash to allow sharing/bookmarking
		 */
		setActiveChat: (chatId: string | null) => {
			set(chatId);
			updateUrlHash(chatId);
		},
		
		/**
		 * Clear the active chat (no chat selected)
		 * Also clears the URL hash
		 */
		clearActiveChat: () => {
			set(null);
			updateUrlHash(null);
		},
		
		/**
		 * Get the current active chat ID (for one-time reads)
		 */
		get: () => {
			let value: string | null = null;
			subscribe(v => value = v)();
			return value;
		},
		
		/**
		 * Get chat ID from URL hash (for initialization)
		 * This is called during app initialization to restore chat from URL
		 */
		getChatIdFromHash: () => {
			return readChatIdFromHash();
		}
	};
}

export const activeChatStore = createActiveChatStore();

