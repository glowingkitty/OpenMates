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
import {
  INTRO_CHATS,
  LEGAL_CHATS,
  getUiVisibleCommunityDemoChats,
  communityDemoStore,
  loadCommunityDemos,
  translateDemoChat,
} from "../demo_chats";
import { convertDemoChatToChat } from "../demo_chats/convertToChat";

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
 * Reset all navigation state to defaults.
 *
 * Called during logout to clear the module-level chat list so that stale
 * user chats do not remain in memory when Chats.svelte is unmounted (e.g.
 * sidebar closed on mobile). Without this reset, the next call to
 * updateNavFromCache() would find the old user-chat list still in chatList
 * (Case 1 branch) and incorrectly compute hasPrev=true for the intro chat.
 */
export function resetChatNavigationList(): void {
  chatList = [];
  currentChatId = null;
  chatNavigationStore.set({ hasPrev: false, hasNext: false });
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

  // ── Case 3: Cold boot — apply public chats immediately, then refine with DB ─
  //
  // Public chats (intro, legal, community demos) are always in-memory and
  // available synchronously. We apply them right away so that nav arrows appear
  // immediately after logout on mobile where Chats.svelte is unmounted and the
  // async DB fetch would otherwise cause a visible delay or missing arrows.
  //
  // After the synchronous apply, we also start an async IndexedDB fetch to pick
  // up any authenticated user chats (e.g. cold boot with sidebar closed).
  //
  // translateDemoChat() resolves i18n keys to strings — same as Chats.svelte does
  // before calling convertDemoChatToChat(). Skipping this step would leave raw
  // translation keys (e.g. "demo_chats.who_develops_openmates.title") in the title.
  const introChats: Chat[] = INTRO_CHATS.map((demo) => {
    const chat = convertDemoChatToChat(translateDemoChat(demo));
    chat.group_key = "intro";
    return chat;
  });
  const legalChats: Chat[] = LEGAL_CHATS.map((legal) => {
    const chat = convertDemoChatToChat(translateDemoChat(legal));
    chat.group_key = "legal";
    return chat;
  });
  // Community demos are already Chat objects with group_key='examples'
  const communityChats: Chat[] = getUiVisibleCommunityDemoChats().map(
    (chat) => ({
      ...chat,
      group_key: "examples" as const,
    }),
  );

  // Apply public-only list immediately (synchronous) so arrows are visible right away.
  // This is especially important after logout on mobile (sidebar closed = Chats.svelte
  // unmounted) where the DB fetch below takes a few hundred ms to resolve.
  const publicOnlyChats = [...introChats, ...communityChats, ...legalChats];
  if (publicOnlyChats.length > 0) {
    _applyNavigableList(publicOnlyChats, activeChatId);
  }

  // If community demos are still empty on cold boot, proactively trigger the
  // shared loader so example chats are available to header prev/next navigation
  // even when Chats.svelte (sidebar) has never mounted.
  const shouldBootstrapCommunityDemos =
    communityChats.length === 0 &&
    !communityDemoStore.isLoading() &&
    !communityDemoStore.isCacheLoaded();
  if (shouldBootstrapCommunityDemos) {
    loadCommunityDemos().catch((error) => {
      console.warn(
        "[chatNavigationStore] Failed to bootstrap community demos for navigation:",
        error,
      );
    });
  }

  // ── Case 3b: Community demos not loaded yet ───────────────────────────────
  // Community demos are fetched asynchronously, so cold boot often starts with
  // intro/legal only. Subscribe once and rebuild the navigation list when demos
  // arrive, even if the active chat is already found in intro/legal.
  // Without this, header prev/next can keep skipping examples until sidebar mount.
  //
  // FIX: Svelte's subscribe() fires the callback synchronously on the first call,
  // BEFORE the return value (unsubscribe function) is assigned. If `chatList`
  // is already populated (e.g. by _applyNavigableList above), the callback would
  // try to call `unsubscribeCommunity` while it's still in the Temporal Dead Zone,
  // crashing with "Cannot access variable before initialization". We use a mutable
  // holder so the callback can safely reference `unsub[0]` — on the synchronous
  // first invocation it's still `undefined` (harmless no-op), and on subsequent
  // calls the real unsubscribe function is available.
  if (communityChats.length === 0) {
    const unsub: [(() => void) | undefined] = [undefined];
    let done = false;
    unsub[0] = communityDemoStore.subscribe(() => {
      if (done) return;
      // Skip if Chats.svelte has since mounted and taken ownership
      if (chatList.length > 0) {
        done = true;
        unsub[0]?.();
        return;
      }
      const updatedCommunityChats: Chat[] =
        getUiVisibleCommunityDemoChats().map((chat) => ({
          ...chat,
          group_key: "examples" as const,
        }));
      if (updatedCommunityChats.length === 0) return; // still loading
      const rebuilt = [...introChats, ...updatedCommunityChats, ...legalChats];
      _applyNavigableList(rebuilt, activeChatId);
      done = true;
      unsub[0]?.(); // one-shot: stop listening after first successful update
    });
    // If the synchronous first call already resolved (chatList was populated),
    // unsubscribe immediately now that the function is available.
    if (done) {
      unsub[0]();
    }
  }

  // ── Case 3c: Async DB fetch to pick up authenticated user chats ───────────
  // Lazily import chatDB to avoid circular deps. This refines the list once
  // the DB resolves — if the user has real chats they should appear in nav.
  // We import chatDB lazily to avoid a circular dependency at module load time.
  import("../services/db")
    .then(({ chatDB }) => chatDB.getAllChats())
    .then((dbChats) => {
      // Skip if Chats.svelte has since mounted and taken ownership
      if (chatList.length > 0) return;
      // Skip if there are no user chats to add (avoids re-sorting unnecessarily)
      if (!dbChats || dbChats.length === 0) return;

      // Combine: real user chats first, then public in-memory chats.
      const allChats = [
        ...dbChats,
        ...introChats,
        ...getUiVisibleCommunityDemoChats().map((chat) => ({
          ...chat,
          group_key: "examples" as const,
        })),
        ...legalChats,
      ];
      _applyNavigableList(allChats, activeChatId);
    })
    .catch((err) => {
      console.warn(
        "[chatNavigationStore] Failed to load chat list from DB for nav:",
        err,
      );
    });
}

/**
 * Internal helper: build the navigable list, update the module-level list,
 * and push hasPrev/hasNext to the store.
 *
 * Uses the same ordering as Chats.svelte's flattenedNavigableChats:
 *   Authenticated:   user chats (no group_key) first, then intro/examples/legal
 *   Unauthenticated: intro → examples → legal (all have a group_key)
 *
 * All chats are included — filtering out demo/legal here would break navigation
 * for unauthenticated users where every chat has a group_key.
 */
function _applyNavigableList(allChats: Chat[], activeChatId: string): void {
  // Mirror the section-first sort from Chats.svelte flattenedNavigableChats.
  // We don't have access to authStore here, but we can infer auth state from
  // whether any chat lacks a group_key (only real user chats have none).
  const hasUserChats = allChats.some((c) => !c.group_key);
  const groupOrder: Record<string, number> = hasUserChats
    ? { intro: 1, examples: 2, legal: 3 } // authenticated order
    : { intro: 0, examples: 1, legal: 2 }; // unauthenticated order

  const navigable = [...allChats].sort((a, b) => {
    const aGroup = a.group_key
      ? (groupOrder[a.group_key] ?? 99)
      : hasUserChats
        ? 0
        : 99;
    const bGroup = b.group_key
      ? (groupOrder[b.group_key] ?? 99)
      : hasUserChats
        ? 0
        : 99;
    if (aGroup !== bGroup) return aGroup - bGroup;
    return (
      (b.last_edited_overall_timestamp || 0) -
      (a.last_edited_overall_timestamp || 0)
    );
  });

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
