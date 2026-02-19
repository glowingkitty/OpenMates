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
}

const initialState: SearchState = {
  query: "",
  isActive: false,
  isSearching: false,
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
 * Close search mode and clear the query.
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
 * Check if search is currently active.
 */
export function isSearchActive(): boolean {
  return get(searchStore).isActive;
}
