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
  getAllExampleChats,
  translateDemoChat,
} from "../demo_chats";
import { convertDemoChatToChat } from "../demo_chats/convertToChat";
import { LOCAL_CHAT_LIST_CHANGED_EVENT } from "../services/drafts/draftConstants";

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
 * True when Chats.svelte (the sidebar) has explicitly set the chat list via
 * setChatNavigationList(). This distinguishes the authoritative sidebar list
 * from the interim list built by updateNavFromCache() during cold boot.
 *
 * Without this flag, updateNavFromCache sees a non-empty chatList (populated
 * by _applyNavigableList with intro/legal chats only) and incorrectly assumes
 * Chats.svelte owns the list — so nav arrows skip examples on first load.
 */
let chatListOwnedByChatsComponent = false;

/**
 * Replace the internal navigation list without marking it as owned by Chats.svelte.
 *
 * Used by updateNavFromCache() during cold boot while building a provisional list
 * from in-memory/public/cache sources. This keeps the list independent from sidebar
 * mount state and allows follow-up refinements (example chats + DB chats) to land.
 */
function setProvisionalChatNavigationList(
  chats: Chat[],
  activeChatId: string | null,
): void {
  chatList = chats;
  currentChatId = activeChatId;
}

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
  chatListOwnedByChatsComponent = true;
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
  chatListOwnedByChatsComponent = false;
  chatNavigationStore.set({ hasPrev: false, hasNext: false });
}

/**
 * Release Chats.svelte's ownership of the navigation list without clearing
 * the data. Called from Chats.svelte onDestroy so that, once the sidebar is
 * unmounted, the store resumes self-managing — the next chat-list change or
 * active-chat switch will rebuild the navigable list from cache/DB.
 *
 * Without this, `chatListOwnedByChatsComponent` stays true forever after the
 * sidebar's first mount, which causes `updateNavFromCache()` to treat a stale
 * list as authoritative — newly-created chats never show up in the header's
 * prev/next arrows until the sidebar is remounted.
 */
export function releaseChatNavigationOwnership(): void {
  chatListOwnedByChatsComponent = false;
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
  // ── Case 1: List already populated ───────────────────────────────────────
  //
  // If Chats.svelte owns the list (sidebar is/was open), it keeps the list
  // up-to-date via its own reactive $effect, so we can safely reuse it here.
  //
  // If the list is only provisional (built during cold boot from intro/legal
  // with possibly zero example chats), we must check whether example chats
  // are now available. If the active chat is missing from the list OR
  // new example chats are available, we fall through to Case 3 to rebuild
  // rather than returning stale hasPrev=false / hasNext=false.
  if (chatList.length > 0) {
    if (chatListOwnedByChatsComponent) {
      // Chats.svelte manages the list — just update position.
      currentChatId = activeChatId;
      const idx = chatList.findIndex((c) => c.chat_id === activeChatId);
      chatNavigationStore.set({
        hasPrev: idx > 0,
        hasNext: idx >= 0 && idx < chatList.length - 1,
      });
      return;
    }

    // Provisional list — check if it needs rebuilding.
    const idx = chatList.findIndex((c) => c.chat_id === activeChatId);
    const exampleCountInList = chatList.filter(
      (c) => c.group_key === "examples",
    ).length;
    const exampleCountAvailable = getAllExampleChats().length;

    if (idx >= 0 && exampleCountInList >= exampleCountAvailable) {
      // Active chat found AND we haven't missed any example chats.
      currentChatId = activeChatId;
      chatNavigationStore.set({
        hasPrev: idx > 0,
        hasNext: idx >= 0 && idx < chatList.length - 1,
      });
      return;
    }

    // Active chat not found OR more example chats are now available.
    // Fall through to Case 3 to rebuild the list from scratch.
  }

  // ── Case 2: Cache already populated by Chats.svelte ──────────────────────
  const cached = chatListCache.getCache();
  if (cached && cached.length > 0) {
    _applyNavigableList(cached, activeChatId);
    return;
  }

  // ── Case 3: Cold boot — apply public chats immediately, then refine with DB ─
  //
  // Public chats (intro, legal, example chats) are always in-memory and
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
  // Example chats are static Chat objects — always available synchronously
  const exampleChats: Chat[] = getAllExampleChats().map((chat) => ({
    ...chat,
    group_key: "examples" as const,
  }));

  // Apply public-only list immediately (synchronous) so arrows are visible right away.
  // This is especially important after logout on mobile (sidebar closed = Chats.svelte
  // unmounted) where the DB fetch below takes a few hundred ms to resolve.
  const publicOnlyChats = [...introChats, ...exampleChats, ...legalChats];
  if (publicOnlyChats.length > 0) {
    _applyNavigableList(publicOnlyChats, activeChatId);
  }

  // ── Case 3b: Async DB fetch to pick up authenticated user chats ───────────
  // Lazily import chatDB to avoid circular deps. This refines the list once
  // the DB resolves — if the user has real chats they should appear in nav.
  // We import chatDB lazily to avoid a circular dependency at module load time.
  import("../services/db")
    .then(({ chatDB }) => chatDB.getAllChats())
    .then((dbChats) => {
      // Skip if Chats.svelte has since mounted and taken ownership
      if (chatListOwnedByChatsComponent) return;
      // Skip if there are no user chats to add (avoids re-sorting unnecessarily)
      if (!dbChats || dbChats.length === 0) return;

      // Combine: real user chats first, then public in-memory chats.
      const allChats = [
        ...dbChats,
        ...introChats,
        ...getAllExampleChats().map((chat) => ({
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

  // Keep this list provisional unless Chats.svelte explicitly overwrites it via
  // setChatNavigationList(). This ensures cold-boot updates (example chats,
  // IndexedDB chats) keep flowing even when the sidebar never mounts.
  setProvisionalChatNavigationList(navigable, activeChatId);
  const idx = navigable.findIndex((c) => c.chat_id === activeChatId);
  chatNavigationStore.set({
    hasPrev: idx > 0,
    hasNext: idx >= 0 && idx < navigable.length - 1,
  });
}

/**
 * Rebuild the navigable list from the freshest source available for the
 * currently-tracked active chat. Used by the `localChatListChanged` listener
 * so newly-created chats land in the ChatHeader prev/next arrows immediately
 * — no sidebar mount/remount required.
 *
 * No-op when Chats.svelte owns the list (its own $effect already tracks DB
 * changes and calls setChatNavigationList) or when no active chat is tracked.
 */
function refreshNavFromLatestSources(): void {
  if (chatListOwnedByChatsComponent) return;
  if (!currentChatId) return;
  // updateNavFromCache already walks cache → in-memory public chats → DB fallback
  // in priority order, so delegate to it with the active chat we're tracking.
  updateNavFromCache(currentChatId);
}

// Subscribe once at module load: any part of the app that creates, renames,
// or deletes a chat dispatches LOCAL_CHAT_LIST_CHANGED_EVENT. This listener
// guarantees the ChatHeader arrows stay in sync without depending on the
// sidebar being mounted.
if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
  window.addEventListener(LOCAL_CHAT_LIST_CHANGED_EVENT, () => {
    refreshNavFromLatestSources();
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
