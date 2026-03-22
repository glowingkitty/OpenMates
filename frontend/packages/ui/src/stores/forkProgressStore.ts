// frontend/packages/ui/src/stores/forkProgressStore.ts
//
// Global store that tracks the state of an active fork operation.
//
// A fork runs entirely in the background (in forkChatService.ts) so the user
// can freely navigate to other chats while the re-encryption / save happens.
// Components subscribe here to show progress UI:
//
//   - SettingsFork.svelte  → progress bar + percentage while in the settings panel
//   - ForkProgressBanner   → slim banner at the top of the source chat window
//   - Notification          → "Chat fork complete" toast on completion
//
// Only one fork can be active at a time. Starting a new fork while one is
// already running is prevented at the service layer.

import { writable, derived, get } from "svelte/store";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ForkStatus =
  | "idle" // No fork running
  | "running" // Re-encrypting and saving messages
  | "complete" // Finished successfully
  | "error"; // Failed

export interface ForkState {
  status: ForkStatus;
  /** The chat ID being forked (the source chat). */
  sourceChatId: string | null;
  /** The new chat ID that will be created. */
  forkChatId: string | null;
  /** Human-readable title for the forked chat (decrypted, in memory only). */
  forkTitle: string | null;
  /** Progress percentage 0-100 (only meaningful while status === 'running'). */
  progress: number;
  /** Total messages to process (for progress calculation). */
  totalMessages: number;
  /** Messages processed so far. */
  processedMessages: number;
  /** Error message if status === 'error'. */
  errorMessage: string | null;
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

const initialState: ForkState = {
  status: "idle",
  sourceChatId: null,
  forkChatId: null,
  forkTitle: null,
  progress: 0,
  totalMessages: 0,
  processedMessages: 0,
  errorMessage: null,
};

const { subscribe, set, update } = writable<ForkState>(initialState);

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export const forkProgressStore = {
  subscribe,

  /** Returns the current state snapshot (non-reactive, for service layer use). */
  getSnapshot(): ForkState {
    return get({ subscribe });
  },

  /** Called by forkChatService when a fork begins. */
  start(
    sourceChatId: string,
    forkChatId: string,
    forkTitle: string,
    totalMessages: number,
  ) {
    set({
      status: "running",
      sourceChatId,
      forkChatId,
      forkTitle,
      progress: 0,
      totalMessages,
      processedMessages: 0,
      errorMessage: null,
    });
  },

  /** Called by forkChatService after each batch of messages is processed. */
  updateProgress(processedMessages: number) {
    update((state) => {
      const total = state.totalMessages || 1; // Guard against division by zero
      const progress = Math.min(
        100,
        Math.round((processedMessages / total) * 100),
      );
      return { ...state, processedMessages, progress };
    });
  },

  /** Called by forkChatService when the operation completes successfully. */
  complete() {
    update((state) => ({
      ...state,
      status: "complete",
      progress: 100,
      processedMessages: state.totalMessages,
    }));
  },

  /** Called by forkChatService when the operation fails. */
  fail(errorMessage: string) {
    update((state) => ({
      ...state,
      status: "error",
      errorMessage,
    }));
  },

  /** Reset back to idle (called after notification is shown or user dismisses). */
  reset() {
    set(initialState);
  },
};

// ---------------------------------------------------------------------------
// Derived stores (convenience selectors for components)
// ---------------------------------------------------------------------------

/** True while a fork is running — used to disable the fork button. */
export const isForkRunning = derived(
  { subscribe },
  ($state) => $state.status === "running",
);

/** True when the source chat currently open is being forked. */
export function isForkingChat(chatId: string) {
  return derived(
    { subscribe },
    ($state) => $state.status === "running" && $state.sourceChatId === chatId,
  );
}
