/**
 * Active Chat Store
 *
 * Maintains the currently active/selected chat ID across component lifecycle.
 * This ensures the chat list can correctly highlight the active chat even when
 * the Chats panel is closed and reopened.
 *
 * URL management (privacy-first):
 *   - Public chats (intro, example, announcements, tips, legal) → semantic path
 *     e.g. /intro/for-everyone, /announcements/introducing-openmates-v09
 *     Shared links hit an SSR page with full OG tags, then redirect to the SPA.
 *   - Private chats → hash fragment (#chat-id=xxx), never sent to the server.
 *   All updates use replaceState — no browser history entries are added.
 */

import { writable } from "svelte/store";
import { browser } from "$app/environment";
import { replaceState } from "$app/navigation";
import { getSemanticUrlForChat, isOnSemanticChatPath } from "../services/chatUrlService";

/**
 * Store to track when deep link processing is happening
 * This prevents auto-loading of demo-for-everyone during deep link processing
 */
export const deepLinkProcessing = writable(false);

/**
 * Flag to prevent hashchange events from triggering when we programmatically update the hash
 * This prevents infinite loops when setActiveChat updates the hash
 * Uses a timestamp to track when we last updated the hash programmatically
 */
let lastProgrammaticHashUpdate = 0;
const PROGRAMMATIC_UPDATE_WINDOW_MS = 100; // Window to ignore hashchange events after programmatic update

/**
 * Update the browser URL to reflect the active chat.
 *
 * Public chats (intro, example, announcements, tips, legal) get a semantic path
 * (e.g. /intro/for-everyone) so shared links hit an SSR page with OG tags.
 * Private chats use the hash fragment (#chat-id=xxx) which is never sent to the
 * server, preserving privacy.
 *
 * Always uses replaceState — no browser history entries are added.
 */
function updateUrlHash(chatId: string | null) {
  if (!browser) return;

  if (chatId) {
    const semanticUrl = getSemanticUrlForChat(chatId);

    if (semanticUrl) {
      // Public chat → update path to semantic URL (no hash, no history entry)
      if (window.location.pathname !== semanticUrl) {
        replaceState(semanticUrl, {});
      }
      return;
    }

    // Private chat → use hash fragment.
    // If we're currently on a semantic path, move back to root first so the hash
    // doesn't get appended to e.g. /intro/for-everyone.
    const expectedHash = `#chat-id=${chatId}`;
    if (isOnSemanticChatPath()) {
      replaceState(`/${expectedHash}`, {});
      return;
    }

    const currentHash = window.location.hash;
    if (currentHash !== expectedHash) {
      lastProgrammaticHashUpdate = Date.now();
      window.location.hash = `chat-id=${chatId}`;
    }
    return;
  }

  // Clearing: go back to root (no hash, no semantic path)
  if (isOnSemanticChatPath()) {
    replaceState("/", {});
    return;
  }
  if (window.location.hash.startsWith("#chat-id=")) {
    replaceState(window.location.pathname + window.location.search, {});
  }
}

/**
 * Check if a hashchange event was triggered by our programmatic update
 * This allows hashchange handlers to ignore programmatic updates
 * Uses a time window to account for async hashchange event firing
 */
export function isProgrammaticHashUpdate(): boolean {
  const timeSinceUpdate = Date.now() - lastProgrammaticHashUpdate;
  return timeSinceUpdate < PROGRAMMATIC_UPDATE_WINDOW_MS;
}

/**
 * Read chat ID from URL hash
 * Returns the chat ID if found, null otherwise
 */
function readChatIdFromHash(): string | null {
  if (!browser) return null;

  const hash = window.location.hash;
  if (hash.startsWith("#chat-id=")) {
    const chatId = hash.substring("#chat-id=".length);
    return chatId || null;
  }

  return null;
}

/**
 * Store for tracking the currently active chat ID
 * Persists across component mount/unmount cycles
 * Also syncs with URL hash for shareable/bookmarkable chat links
 */
function createActiveChatStore() {
  // Initialize with chat ID from URL hash if present
  const initialChatId = readChatIdFromHash();
  const { subscribe, set } = writable<string | null>(initialChatId);

  return {
    subscribe,

    /**
     * Set the currently active chat ID
     * Also updates the URL hash to allow sharing/bookmarking
     */
    setActiveChat: (chatId: string | null) => {
      // Defense-in-depth: log abbreviated stack trace so any unexpected caller
      // that sets an active chat can be traced during debugging.
      if (chatId) {
        const stack =
          new Error().stack
            ?.split("\n")
            .slice(1, 4)
            .map((l) => l.trim())
            .join(" <- ") ?? "";
        console.debug(
          `[activeChatStore] setActiveChat("${chatId}") called from: ${stack}`,
        );
      }
      set(chatId);
      updateUrlHash(chatId);
    },

    /**
     * Clear the active chat (no chat selected)
     * Also clears the URL hash
     */
    clearActiveChat: () => {
      set(null);
      updateUrlHash(null);
    },

    /**
     * Set the store value without updating the URL hash
     * Used when we need to update the store state while preserving the hash
     * (e.g., during deep link processing)
     */
    setWithoutHashUpdate: (chatId: string | null) => {
      set(chatId);
    },

    /**
     * Get the current active chat ID (for one-time reads)
     */
    get: () => {
      let value: string | null = null;
      subscribe((v) => (value = v))();
      return value;
    },

    /**
     * Get chat ID from URL hash (for initialization)
     * This is called during app initialization to restore chat from URL
     */
    getChatIdFromHash: () => {
      return readChatIdFromHash();
    },
  };
}

export const activeChatStore = createActiveChatStore();
