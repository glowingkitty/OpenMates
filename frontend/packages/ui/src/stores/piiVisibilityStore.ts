/**
 * PII Visibility Store
 *
 * Manages whether sensitive personal information (PII) is revealed or hidden
 * in chat messages. By default, PII is hidden (placeholders shown with reduced
 * opacity highlight). Users can toggle visibility per chat via the eye icon
 * button in the chat header.
 *
 * Architecture:
 * - Default state: PII is HIDDEN (placeholders shown, background opacity 0.3)
 * - Revealed state: PII originals shown in place of placeholders (opacity 1.0)
 * - State is tracked per chat ID (Map<chatId, boolean>)
 * - State is session-only (not persisted) for privacy — defaults to hidden on reload
 *
 * Consumers:
 * - ChatHistory.svelte: decides whether to call restorePIIInMarkdown()
 * - ReadOnlyMessage.svelte: decides decoration class (hidden vs revealed)
 * - ChatMessage.svelte: handleCopyMessage() respects visibility
 * - chatExportService.ts / zipExportService.ts: copy/download respect visibility
 * - SettingsShare.svelte: share respects PII visibility
 */

import { writable, derived } from "svelte/store";

/**
 * Internal state: Map of chatId → boolean (true = PII revealed, false = hidden).
 * Chats not in the map default to hidden (false).
 */
const piiRevealedChats = writable<Map<string, boolean>>(new Map());

/**
 * Check if PII is currently revealed for a specific chat.
 * Returns false (hidden) by default.
 */
function isRevealed(chatId: string): boolean {
  let value = false;
  piiRevealedChats.subscribe((map) => {
    value = map.get(chatId) ?? false;
  })();
  return value;
}

/**
 * Toggle PII visibility for a specific chat.
 * If currently hidden, reveals PII. If currently revealed, hides PII.
 */
function toggle(chatId: string): void {
  piiRevealedChats.update((map) => {
    const newMap = new Map(map);
    const current = newMap.get(chatId) ?? false;
    newMap.set(chatId, !current);
    return newMap;
  });
}

/**
 * Set PII visibility for a specific chat.
 * @param chatId - The chat to update
 * @param revealed - true to show originals, false to show placeholders
 */
function setRevealed(chatId: string, revealed: boolean): void {
  piiRevealedChats.update((map) => {
    const newMap = new Map(map);
    newMap.set(chatId, revealed);
    return newMap;
  });
}

/**
 * Create a derived store that tracks PII visibility for a specific chat.
 * Useful for reactive bindings in Svelte components.
 */
function forChat(chatId: string) {
  return derived(piiRevealedChats, ($map) => $map.get(chatId) ?? false);
}

/**
 * Reset all PII visibility state (e.g., on logout).
 */
function reset(): void {
  piiRevealedChats.set(new Map());
}

export const piiVisibilityStore = {
  /** The raw Svelte store (subscribe to get the full Map) */
  subscribe: piiRevealedChats.subscribe,
  /** Check if PII is revealed for a chat (one-time read) */
  isRevealed,
  /** Toggle PII visibility for a chat */
  toggle,
  /** Set PII visibility for a chat */
  setRevealed,
  /** Create a derived store for a specific chat's PII visibility */
  forChat,
  /** Reset all visibility state */
  reset,
};
