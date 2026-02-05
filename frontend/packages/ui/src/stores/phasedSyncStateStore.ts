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

import { writable } from "svelte/store";

/**
 * Special sentinel value indicating the user is in "new chat" mode.
 * Used instead of null to explicitly track when user chose to start a new chat.
 * This allows shouldAutoSelectPhase1Chat to block auto-selection.
 */
export const NEW_CHAT_SENTINEL = "__new_chat__";

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
   * Can be NEW_CHAT_SENTINEL to indicate user chose "new chat" mode.
   */
  currentActiveChatId: string | null;

  /**
   * Timestamp of when the last phased sync started.
   * Used for debugging and monitoring.
   */
  lastSyncTimestamp: number | null;

  /**
   * Whether a chat has been loaded after initial page load.
   * Once true, sync phases should NOT override the user's current view.
   * This prevents sync phases from switching the user back to old chats.
   */
  initialChatLoaded: boolean;

  /**
   * Whether the user has made an explicit choice to switch chats or go to new chat.
   * This is set when user clicks on a chat or clicks "new chat" AFTER initial load.
   * When true, sync phases will NEVER override the user's choice.
   */
  userMadeExplicitChoice: boolean;
}

const initialState: PhasedSyncState = {
  initialSyncCompleted: false,
  phase1ChatId: null,
  currentActiveChatId: null,
  lastSyncTimestamp: null,
  initialChatLoaded: false,
  userMadeExplicitChoice: false,
};

const { subscribe, set, update } = writable<PhasedSyncState>(initialState);

export const phasedSyncState = {
  subscribe,

  /**
   * Mark that the initial phased sync has completed.
   * This prevents redundant syncs when components remount.
   */
  markSyncCompleted: () => {
    // DEBUG: Log stack trace to see who's calling this
    console.debug(
      "[phasedSyncState] markSyncCompleted called, stack:",
      new Error().stack,
    );
    update((state) => ({
      ...state,
      initialSyncCompleted: true,
    }));
  },

  /**
   * Set the Phase 1 chat ID that was received from the server.
   * This is the "last opened" chat from the server.
   */
  setPhase1ChatId: (chatId: string | null) => {
    update((state) => ({
      ...state,
      phase1ChatId: chatId,
    }));
  },

  /**
   * Set the current active chat ID from the UI.
   * Used to prevent Phase 1 from overriding the user's current chat.
   */
  setCurrentActiveChatId: (chatId: string | null) => {
    update((state) => ({
      ...state,
      currentActiveChatId: chatId,
    }));
  },

  /**
   * Update the last sync timestamp.
   */
  updateSyncTimestamp: () => {
    update((state) => ({
      ...state,
      lastSyncTimestamp: Date.now(),
    }));
  },

  /**
   * Check if Phase 1 should auto-select the last opened chat.
   * Returns false if:
   * - User has made an explicit choice to switch chats or go to new chat
   * - User is in "new chat" mode (currentActiveChatId === NEW_CHAT_SENTINEL)
   * - User is already in a different chat
   * - A chat has already been loaded after initial page load
   */
  shouldAutoSelectPhase1Chat: (phase1ChatId: string): boolean => {
    let should = true;
    update((state) => {
      // CRITICAL: If user made an explicit choice (clicked on a chat or new chat),
      // NEVER auto-select - respect the user's choice
      if (state.userMadeExplicitChoice) {
        console.info(
          `[PhasedSyncState] Skipping Phase 1 auto-select: user made explicit choice`,
        );
        should = false;
        return state;
      }

      // CRITICAL: If user is in "new chat" mode (indicated by sentinel value),
      // don't auto-select - they intentionally started a new chat
      if (state.currentActiveChatId === NEW_CHAT_SENTINEL) {
        console.info(
          `[PhasedSyncState] Skipping Phase 1 auto-select: user is in new chat mode`,
        );
        should = false;
        return state;
      }

      // Don't auto-select if a chat was already loaded after initial page load
      if (state.initialChatLoaded) {
        console.info(
          `[PhasedSyncState] Skipping Phase 1 auto-select: initial chat already loaded`,
        );
        should = false;
        return state;
      }

      // Don't auto-select if user is in a different chat
      if (
        state.currentActiveChatId &&
        state.currentActiveChatId !== phase1ChatId
      ) {
        console.info(
          `[PhasedSyncState] Skipping Phase 1 auto-select: user is in ${state.currentActiveChatId}, Phase 1 is ${phase1ChatId}`,
        );
        should = false;
      }
      return state;
    });
    return should;
  },

  /**
   * Mark that the initial chat has been loaded after page load.
   * Once set, sync phases should NOT override the user's current view.
   */
  markInitialChatLoaded: () => {
    update((state) => ({
      ...state,
      initialChatLoaded: true,
    }));
  },

  /**
   * Mark that the user has made an explicit choice to switch chats or go to new chat.
   * This is set when user clicks on a chat or clicks "new chat" AFTER initial load.
   * When true, sync phases will NEVER override the user's choice.
   */
  markUserMadeExplicitChoice: () => {
    update((state) => ({
      ...state,
      userMadeExplicitChoice: true,
    }));
  },

  /**
   * Check if the user can be auto-navigated to a chat by sync.
   * Returns false if user has made explicit choice or initial chat is already loaded.
   */
  canAutoNavigate: (): boolean => {
    let can = true;
    update((state) => {
      if (state.userMadeExplicitChoice || state.initialChatLoaded) {
        can = false;
      }
      return state;
    });
    return can;
  },

  /**
   * Reset the sync state (e.g., on logout or connection loss).
   */
  reset: () => {
    console.debug("[phasedSyncState] reset called, stack:", new Error().stack);
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
