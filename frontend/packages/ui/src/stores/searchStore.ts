// frontend/packages/ui/src/stores/searchStore.ts
// Svelte store for search state management.
// Uses writable store (not runes) because stores must work outside components.
// Components using this store should access it via $searchStore syntax.

import { writable, get } from "svelte/store";

/** Search store state */
export interface SearchState {
  /** Current search query string */
  query: string;
  /** Whether search mode is active (search bar is open/visible) */
  isActive: boolean;
  /** Whether a search is currently in progress */
  isSearching: boolean;
  /**
   * The message ID that was most recently clicked from search results.
   * Used by ChatHistory to scroll-to and highlight the matched message.
   * Null when no message is being highlighted from search.
   */
  activeMessageId: string | null;
  /**
   * The chat ID whose messages should have highlights while search is open.
   * While search is open, all matches in the active chat should be visually highlighted.
   */
  activeSearchChatId: string | null;
}

const initialState: SearchState = {
  query: "",
  isActive: false,
  isSearching: false,
  activeMessageId: null,
  activeSearchChatId: null,
};

export const searchStore = writable<SearchState>(initialState);

/**
 * Open search mode (show the search bar).
 * Called when user clicks the search icon or presses Cmd+K.
 */
export function openSearch(): void {
  searchStore.update((state) => ({
    ...state,
    isActive: true,
  }));
}

/**
 * Close search mode and clear all state.
 * Called when user clicks the X button or presses Escape.
 */
export function closeSearch(): void {
  searchStore.set(initialState);
}

/**
 * Update the search query.
 * @param query - The new search query string
 */
export function setSearchQuery(query: string): void {
  searchStore.update((state) => ({
    ...state,
    query,
    isSearching: query.trim().length > 0,
    // Clear active message when query changes
    activeMessageId: null,
  }));
}

/**
 * Set the searching state (used while search is in progress).
 * @param isSearching - Whether search is currently executing
 */
export function setSearching(isSearching: boolean): void {
  searchStore.update((state) => ({
    ...state,
    isSearching,
  }));
}

/**
 * Set the active message ID from search results.
 * This triggers scroll-to-message in ChatHistory via messageHighlightStore.
 * @param messageId - The message ID to scroll to (null to clear)
 * @param chatId - The chat the message belongs to
 */
export function setActiveSearchMessage(
  messageId: string | null,
  chatId: string | null,
): void {
  searchStore.update((state) => ({
    ...state,
    activeMessageId: messageId,
    activeSearchChatId: chatId,
  }));
}

/**
 * Check if search is currently active.
 */
export function isSearchActive(): boolean {
  return get(searchStore).isActive;
}
