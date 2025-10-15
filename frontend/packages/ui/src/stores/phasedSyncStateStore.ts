// frontend/packages/ui/src/stores/phasedSyncStateStore.ts
/**
 * @file phasedSyncStateStore.ts
 * @description Svelte store for managing phased sync state across component lifecycle.
 * 
 * This store tracks whether the initial phased sync has completed after login,
 * preventing redundant sync requests when components are remounted (e.g., when
 * the Chats panel is closed and reopened).
 * 
 * Key features:
 * - Persists sync state across component mount/unmount cycles
 * - Resets on logout or connection loss
 * - Prevents Phase 1 auto-selection when user is in an active chat
 */

import { writable } from 'svelte/store';

export interface PhasedSyncState {
	/**
	 * Whether the initial phased sync has completed after login.
	 * This prevents redundant sync when components remount.
	 */
	initialSyncCompleted: boolean;
	
	/**
	 * The chat ID that Phase 1 would auto-select.
	 * Used to compare against current active chat.
	 */
	phase1ChatId: string | null;
	
	/**
	 * Current active chat ID from the UI.
	 * Used to prevent Phase 1 from overriding user's current chat.
	 */
	currentActiveChatId: string | null;
	
	/**
	 * Timestamp of when the last phased sync started.
	 * Used for debugging and monitoring.
	 */
	lastSyncTimestamp: number | null;
}

const initialState: PhasedSyncState = {
	initialSyncCompleted: false,
	phase1ChatId: null,
	currentActiveChatId: null,
	lastSyncTimestamp: null,
};

const { subscribe, set, update } = writable<PhasedSyncState>(initialState);

export const phasedSyncState = {
	subscribe,
	
	/**
	 * Mark that the initial phased sync has completed.
	 * This prevents redundant syncs when components remount.
	 */
	markSyncCompleted: () => {
		update(state => ({
			...state,
			initialSyncCompleted: true,
		}));
	},
	
	/**
	 * Set the Phase 1 chat ID that was received from the server.
	 * This is the "last opened" chat from the server.
	 */
	setPhase1ChatId: (chatId: string | null) => {
		update(state => ({
			...state,
			phase1ChatId: chatId,
		}));
	},
	
	/**
	 * Set the current active chat ID from the UI.
	 * Used to prevent Phase 1 from overriding the user's current chat.
	 */
	setCurrentActiveChatId: (chatId: string | null) => {
		update(state => ({
			...state,
			currentActiveChatId: chatId,
		}));
	},
	
	/**
	 * Update the last sync timestamp.
	 */
	updateSyncTimestamp: () => {
		update(state => ({
			...state,
			lastSyncTimestamp: Date.now(),
		}));
	},
	
	/**
	 * Check if Phase 1 should auto-select the last opened chat.
	 * Returns false if:
	 * - User is already in a different chat
	 * - Initial sync already completed
	 */
	shouldAutoSelectPhase1Chat: (phase1ChatId: string): boolean => {
		let should = true;
		update(state => {
			// Don't auto-select if user is in a different chat
			if (state.currentActiveChatId && state.currentActiveChatId !== phase1ChatId) {
				console.info(`[PhasedSyncState] Skipping Phase 1 auto-select: user is in ${state.currentActiveChatId}, Phase 1 is ${phase1ChatId}`);
				should = false;
			}
			return state;
		});
		return should;
	},
	
	/**
	 * Reset the sync state (e.g., on logout or connection loss).
	 */
	reset: () => {
		set(initialState);
	},
};

// Example usage:
// import { phasedSyncState } from './phasedSyncStateStore';
// 
// // In Chats.svelte onMount:
// if (!$phasedSyncState.initialSyncCompleted) {
//   await chatSyncService.startPhasedSync();
// }
//
// // In Phase 1 handler:
// if (phasedSyncState.shouldAutoSelectPhase1Chat(payload.chat_id)) {
//   // Auto-select the chat
// }
//
// // On logout:
// phasedSyncState.reset();

