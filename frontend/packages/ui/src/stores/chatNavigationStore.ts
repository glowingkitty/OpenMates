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

import { writable, get } from "svelte/store";
import type { Chat } from "../types/chat";
import { activeChatStore } from "./activeChatStore";

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
  if (!(chat as any).is_hidden) {
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
