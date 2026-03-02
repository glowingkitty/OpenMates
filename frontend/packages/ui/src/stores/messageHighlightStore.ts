import { writable } from "svelte/store";

/** Store for scroll-to-message highlighting: set to a messageId to scroll + blink that message */
export const messageHighlightStore = writable<string | null>(null);

/**
 * Store for in-chat search text highlighting.
 * When non-null, all matching text in the active chat's messages is visually highlighted.
 * Set to the search query string while search is open, null when closed.
 */
export const searchTextHighlightStore = writable<string | null>(null);
