/**
 * Active Chat Store
 * 
 * Maintains the currently active/selected chat ID across component lifecycle.
 * This ensures the chat list can correctly highlight the active chat even when
 * the Chats panel is closed and reopened.
 */

import { writable } from 'svelte/store';

/**
 * Store for tracking the currently active chat ID
 * Persists across component mount/unmount cycles
 */
function createActiveChatStore() {
	const { subscribe, set, update } = writable<string | null>(null);

	return {
		subscribe,
		
		/**
		 * Set the currently active chat ID
		 */
		setActiveChat: (chatId: string | null) => {
			set(chatId);
		},
		
		/**
		 * Clear the active chat (no chat selected)
		 */
		clearActiveChat: () => {
			set(null);
		},
		
		/**
		 * Get the current active chat ID (for one-time reads)
		 */
		get: () => {
			let value: string | null = null;
			subscribe(v => value = v)();
			return value;
		}
	};
}

export const activeChatStore = createActiveChatStore();

