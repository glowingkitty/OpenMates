/**
 * Active Chat Store
 *
 * Maintains the currently active/selected chat ID across component lifecycle.
 * This ensures the chat list can correctly highlight the active chat even when
 * the Chats panel is closed and reopened.
 *
 * URL management (privacy-first):
 *   - All in-session chat navigation → hash fragment (#chat-id=xxx)
 *     Using replaceState to a different SvelteKit route (e.g. /intro/for-developers)
 *     can trigger SvelteKit's client router on prerendered (seo) pages, causing
 *     unexpected navigation or UI freeze. Hash-based navigation is safe for all
 *     in-session switching. Prerendered semantic paths serve SEO crawlers only.
 *   - Private chats → hash fragment (#chat-id=xxx), never sent to the server.
 *   All updates use replaceState or hash assignment — no browser history entries added.
 */

import { writable } from "svelte/store";
import { browser } from "$app/environment";
import { replaceState } from "$app/navigation";
import { isOnSemanticChatPath } from "../services/chatUrlService";

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
 * All in-session navigation uses the hash fragment so no SvelteKit route change occurs.
 * Always uses replaceState or hash assignment — no browser history entries are added.
 */
function updateUrlHash(chatId: string | null) {
  if (!browser) return;

  if (chatId) {
    // Always use hash fragment for in-session navigation (public and private chats alike).
    // Using replaceState to a semantic path like /intro/for-developers risks triggering
    // SvelteKit's client router because those paths exist as real prerendered (seo) routes.
    // If SvelteKit navigates to the SEO page, its onMount fires window.location.replace
    // which can interrupt loadChat mid-flight and leave the UI unresponsive.
    // Hash-based navigation avoids any route change and is consistent for all chat types.
    const expectedHash = `#chat-id=${chatId}`;
    if (isOnSemanticChatPath()) {
      // Currently on a semantic path (e.g. user arrived via direct link /intro/for-developers).
      // Move back to root with the hash so it doesn't get appended to the semantic path.
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
