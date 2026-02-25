/**
 * chatNavigationStore.ts
 *
 * Stores the prev/next navigation state AND the full chat list for the
 * currently active chat. This allows ChatHeader.svelte to navigate between
 * chats even when Chats.svelte (the sidebar) is unmounted (closed).
 *
 * Updated by Chats.svelte whenever the sorted chat list or selection changes.
 * Read by ChatHeader.svelte to show/hide the prev/next arrow buttons and
 * to trigger navigation via the navigate methods.
 *
 * Navigation flow:
 *   1. ChatHeader calls navigatePrev()/navigateNext() on this store
 *   2. The store finds the target chat from the persisted chat list
 *   3. The store dispatches a 'chatHeaderNavigation' window event with the
 *      target chat object and scrollToTop:true
 *   4. +page.svelte listens for 'chatHeaderNavigation' and calls
 *      activeChat.loadChat(chat, { scrollToTop: true })
 *   5. The store also calls chatSyncService.sendSetActiveChat() and updates
 *      activeChatStore to persist the selection (same as Chats.svelte handleChatClick)
 */

import { writable } from "svelte/store";
import type { Chat } from "../types/chat";
import { activeChatStore } from "./activeChatStore";
import { chatListCache } from "../services/chatListCache";

export interface ChatNavigationState {
  /** True when there is a chat before the current one in the sorted list. */
  hasPrev: boolean;
  /** True when there is a chat after the current one in the sorted list. */
  hasNext: boolean;
}

/**
 * The hasPrev/hasNext flags for ChatHeader arrow button visibility.
 * Write from Chats.svelte, read from ChatHeader.svelte.
 */
export const chatNavigationStore = writable<ChatNavigationState>({
  hasPrev: false,
  hasNext: false,
});

// ─── Internal state for navigation when sidebar is closed ────────────────────

/**
 * The full sorted/filtered chat list, written by Chats.svelte whenever
 * flattenedNavigableChats changes. Persists across sidebar mount/unmount
 * cycles because this is a module-level variable.
 */
let chatList: Chat[] = [];

/**
 * The currently selected chat ID, written by Chats.svelte whenever
 * the selection changes. Used to find the current index in chatList.
 */
let currentChatId: string | null = null;

/**
 * Update the internal chat list and active chat ID used for navigation.
 * Called by Chats.svelte whenever the list or selection changes.
 */
export function setChatNavigationList(
  chats: Chat[],
  activeChatId: string | null,
): void {
  chatList = chats;
  currentChatId = activeChatId;
}

/**
 * Navigate to the previous chat in the list.
 * Works even when Chats.svelte is unmounted because we use the persisted chatList.
 *
 * Dispatches a 'chatHeaderNavigation' window event that +page.svelte handles
 * to call activeChat.loadChat() with scrollToTop: true.
 * Also persists the selection via activeChatStore and chatSyncService.
 */
export async function navigatePrev(): Promise<void> {
  if (chatList.length === 0) return;

  const idx = currentChatId
    ? chatList.findIndex((c) => c.chat_id === currentChatId)
    : -1;

  // Already at the start or not found
  if (idx <= 0) return;

  const targetChat = chatList[idx - 1];
  if (!targetChat) return;

  await selectChat(targetChat);
}

/**
 * Navigate to the next chat in the list.
 * Works even when Chats.svelte is unmounted because we use the persisted chatList.
 *
 * Dispatches a 'chatHeaderNavigation' window event that +page.svelte handles
 * to call activeChat.loadChat() with scrollToTop: true.
 * Also persists the selection via activeChatStore and chatSyncService.
 */
export async function navigateNext(): Promise<void> {
  if (chatList.length === 0) return;

  const idx = currentChatId
    ? chatList.findIndex((c) => c.chat_id === currentChatId)
    : -1;

  // Already at the end or not found
  if (idx < 0 || idx >= chatList.length - 1) return;

  const targetChat = chatList[idx + 1];
  if (!targetChat) return;

  await selectChat(targetChat);
}

/**
 * Populate the navigation store so ChatHeader prev/next arrows work even when
 * Chats.svelte (the sidebar) has never been opened (e.g. on mobile).
 *
 * Priority:
 *   1. If Chats.svelte already populated chatList, just update the active ID
 *      and recompute hasPrev/hasNext — never overwrite the authoritative list.
 *   2. If chatListCache has a fresh snapshot, build the navigable list from it.
 *   3. If the cache is empty (cold boot, sidebar never opened), load the full
 *      chat list from IndexedDB in the background and update when ready.
 *
 * Called by ActiveChat.loadChat() on every chat switch.
 */
export function updateNavFromCache(activeChatId: string): void {
  // ── Case 1: Chats.svelte already owns the list ───────────────────────────
  if (chatList.length > 0) {
    currentChatId = activeChatId;
    const idx = chatList.findIndex((c) => c.chat_id === activeChatId);
    chatNavigationStore.set({
      hasPrev: idx > 0,
      hasNext: idx >= 0 && idx < chatList.length - 1,
    });
    return;
  }

  // ── Case 2: Cache already populated by Chats.svelte ──────────────────────
  const cached = chatListCache.getCache();
  if (cached && cached.length > 0) {
    _applyNavigableList(cached, activeChatId);
    return;
  }

  // ── Case 3: Cold boot — load from IndexedDB in the background ────────────
  // We import chatDB lazily to avoid a circular dependency at module load time.
  // This runs asynchronously; the arrows will appear once the promise resolves
  // (typically within a few hundred milliseconds on a warm device).
  import("../services/db")
    .then(({ chatDB }) => chatDB.getAllChats())
    .then((chats) => {
      if (!chats || chats.length === 0) return;
      // Only apply if Chats.svelte still hasn't mounted and set its own list
      if (chatList.length === 0) {
        _applyNavigableList(chats, activeChatId);
      }
    })
    .catch((err) => {
      console.warn(
        "[chatNavigationStore] Failed to load chat list from DB for nav:",
        err,
      );
    });
}

/**
 * Internal helper: filter to navigable chats, update the module-level list,
 * and push the new hasPrev/hasNext to the store.
 *
 * "Navigable" = user-owned chats without a group_key (same basic filter as
 * Chats.svelte's flattenedNavigableChats, but without demo/legal filtering
 * which would require importing demo_chats here).  In practice group_key is
 * only set on grouped/demo entries so this is equivalent for regular users.
 */
function _applyNavigableList(allChats: Chat[], activeChatId: string): void {
  const navigable = allChats.filter((c) => !c.group_key);
  setChatNavigationList(navigable, activeChatId);
  const idx = navigable.findIndex((c) => c.chat_id === activeChatId);
  chatNavigationStore.set({
    hasPrev: idx > 0,
    hasNext: idx >= 0 && idx < navigable.length - 1,
  });
}

/**
 * Internal helper: select a target chat by updating stores, persisting via
 * chatSyncService, and dispatching the window event for +page.svelte.
 */
async function selectChat(chat: Chat): Promise<void> {
  // Update local tracking immediately so rapid clicks work correctly
  currentChatId = chat.chat_id;

  // Update the persistent activeChatStore (survives component unmount/remount)
  activeChatStore.setActiveChat(chat.chat_id);

  // Persist to IndexedDB + server via chatSyncService (same as Chats.svelte handleChatClick)
  // Only for non-hidden chats (hidden chats require password after page reload)
  if (!(chat as Chat & { is_hidden?: boolean }).is_hidden) {
    try {
      const { chatSyncService } = await import("../services/chatSyncService");
      await chatSyncService.sendSetActiveChat(chat.chat_id);
    } catch (error) {
      console.error(
        "[chatNavigationStore] Error persisting active chat:",
        error,
      );
    }
  }

  // Dispatch window event for +page.svelte to call activeChat.loadChat()
  // The scrollToTop flag tells ActiveChat to scroll to the top of the chat
  // so the ChatHeader banner is visible after navigation.
  window.dispatchEvent(
    new CustomEvent("chatHeaderNavigation", {
      detail: { chat, scrollToTop: true },
    }),
  );

  // Update hasPrev/hasNext for the new position
  const newIdx = chatList.findIndex((c) => c.chat_id === chat.chat_id);
  chatNavigationStore.set({
    hasPrev: newIdx > 0,
    hasNext: newIdx >= 0 && newIdx < chatList.length - 1,
  });
}
