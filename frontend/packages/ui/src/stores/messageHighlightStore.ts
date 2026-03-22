import { writable } from "svelte/store";

/** Store for scroll-to-message highlighting: set to a messageId to scroll + blink that message */
export const messageHighlightStore = writable<string | null>(null);

/**
 * Store for in-chat search text highlighting.
 * When non-null, all matching text in the active chat's messages is visually highlighted.
 * Set to the search query string while search is open, null when closed.
 */
export const searchTextHighlightStore = writable<string | null>(null);

/**
 * Store for code line highlighting in the code embed fullscreen.
 * Set when the user clicks an embed: link with a #L42 or #L10-L20 line range suffix.
 * The CodeEmbedFullscreen consumes this to highlight and auto-scroll to the target lines.
 * Cleared when the fullscreen is closed.
 */
export const codeLineHighlightStore = writable<{
  start: number;
  end: number;
} | null>(null);
