// frontend/packages/ui/src/stores/activeChatFocusStore.ts
// Tracks the live active focus mode per chat while encrypted metadata catches up.
// WebSocket focus activation arrives before IndexedDB/cache consumers may see
// encrypted_active_focus_id, so UI surfaces use this as a temporary convergence
// layer and still prefer persisted decrypted metadata when it is available.

import { writable } from 'svelte/store';

type ActiveChatFocusState = Record<string, string>;

function createActiveChatFocusStore() {
  const { subscribe, update } = writable<ActiveChatFocusState>({});

  return {
    subscribe,
    setActiveFocus(chatId: string, focusId: string) {
      update((state) => ({ ...state, [chatId]: focusId }));
    },
    clearActiveFocus(chatId: string) {
      update((state) => {
        if (!(chatId in state)) return state;
        const next = { ...state };
        delete next[chatId];
        return next;
      });
    }
  };
}

export const activeChatFocusStore = createActiveChatFocusStore();
