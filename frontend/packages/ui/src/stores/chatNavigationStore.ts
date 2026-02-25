/**
 * chatNavigationStore.ts
 *
 * Stores the prev/next navigation state for the currently active chat.
 * Updated by Chats.svelte whenever the selected chat changes.
 * Read by ChatHeader.svelte to show/hide the prev/next arrow buttons.
 *
 * This is a lightweight alternative to threading the state through multiple
 * component prop layers (Chats → +page → ActiveChat → ChatHistory → ChatHeader).
 */

import { writable } from "svelte/store";

export interface ChatNavigationState {
  /** True when there is a chat before the current one in the sorted list. */
  hasPrev: boolean;
  /** True when there is a chat after the current one in the sorted list. */
  hasNext: boolean;
}

/**
 * Write from Chats.svelte, read from ChatHeader.svelte.
 * Default: both false (no navigation available before first update).
 */
export const chatNavigationStore = writable<ChatNavigationState>({
  hasPrev: false,
  hasNext: false,
});
