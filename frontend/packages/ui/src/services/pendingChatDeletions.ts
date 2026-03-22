// frontend/packages/ui/src/services/pendingChatDeletions.ts
// Tracks chat IDs that were deleted locally (IndexedDB) while offline,
// so the delete can be sent to the server once the connection is restored.
//
// This uses localStorage for persistence because:
// 1. It survives page reloads and browser restarts
// 2. It doesn't require an IndexedDB schema migration
// 3. The data is tiny (just an array of chat ID strings)
//
// The pending deletions set is checked in two places:
// - startPhasedSync(): Filters pending deletes from client_chat_ids so the server
//   doesn't re-send the deleted chat during Phase 2/3
// - storeRecentChats/storeAllChats: Skips chats that are pending deletion so they
//   don't get re-added to IndexedDB even if the server sends them
//
// On reconnect, flushPendingDeletions() sends each pending delete to the server
// via the existing sendDeleteChat() WebSocket call and removes it from the set.

const STORAGE_KEY = "openmates_pending_chat_deletions";

/**
 * Get all chat IDs that are pending server deletion.
 * Returns an empty array if none are pending.
 */
export function getPendingChatDeletions(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed;
  } catch {
    return [];
  }
}

/**
 * Get pending deletions as a Set for fast lookups.
 * Used by phased sync handlers to check if a chat should be skipped.
 */
export function getPendingChatDeletionsSet(): Set<string> {
  return new Set(getPendingChatDeletions());
}

/**
 * Add a chat ID to the pending deletions set.
 * Called when a chat is deleted from IndexedDB but the server delete couldn't be sent
 * (e.g., WebSocket disconnected / offline).
 */
export function addPendingChatDeletion(chatId: string): void {
  try {
    const current = getPendingChatDeletions();
    if (!current.includes(chatId)) {
      current.push(chatId);
      localStorage.setItem(STORAGE_KEY, JSON.stringify(current));
      console.debug(
        `[PendingChatDeletions] Queued chat ${chatId} for server deletion on reconnect. Total pending: ${current.length}`,
      );
    }
  } catch (error) {
    console.error(
      `[PendingChatDeletions] Failed to queue chat ${chatId}:`,
      error,
    );
  }
}

/**
 * Remove a chat ID from the pending deletions set.
 * Called after the server delete has been successfully sent.
 */
export function removePendingChatDeletion(chatId: string): void {
  try {
    const current = getPendingChatDeletions();
    const updated = current.filter((id) => id !== chatId);
    if (updated.length === 0) {
      localStorage.removeItem(STORAGE_KEY);
    } else {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
    }
    console.debug(
      `[PendingChatDeletions] Removed chat ${chatId} from pending deletions. Remaining: ${updated.length}`,
    );
  } catch (error) {
    console.error(
      `[PendingChatDeletions] Failed to remove chat ${chatId}:`,
      error,
    );
  }
}

/**
 * Check if a chat ID is pending server deletion.
 * Used by phased sync storage helpers to skip re-adding deleted chats.
 */
export function isChatPendingDeletion(chatId: string): boolean {
  return getPendingChatDeletions().includes(chatId);
}

/**
 * Clear all pending deletions.
 * Called on logout to reset state.
 */
export function clearAllPendingChatDeletions(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
    console.debug("[PendingChatDeletions] Cleared all pending deletions");
  } catch (error) {
    console.error(
      "[PendingChatDeletions] Failed to clear pending deletions:",
      error,
    );
  }
}
