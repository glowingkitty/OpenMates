// frontend/packages/ui/src/stores/messageHighlightsStore.ts
//
// In-memory cache of decrypted message highlights, keyed by (chatId, messageId).
// Synced one-way from IndexedDB (messageHighlights.ts data-access) — the store
// is the render-side source of truth. All reads in Svelte components go through
// this store; all writes go through chatSyncService which persists to IDB and
// pushes over WS, then calls back into the store.

import { writable, derived, get } from "svelte/store";
import type { MessageHighlight } from "../types/chat";
import {
  countHighlightsAndComments,
  sortHighlightsForNavigation,
} from "../utils/messageHighlights";

type HighlightsByMessageId = Record<string, MessageHighlight[]>;
type HighlightsByChatId = Record<string, HighlightsByMessageId>;

const store = writable<HighlightsByChatId>({});

export const messageHighlightsStore = { subscribe: store.subscribe };

/**
 * Ids of highlights this client created locally. Used by the popover to
 * decide whether to show Edit/Delete buttons — more reliable than comparing
 * userProfile.user_id against the server-echoed author_user_id, which can
 * race (local optimistic version arrives before userProfile is populated,
 * or the id formats differ subtly).
 *
 * The set is memory-only. After reload, authorship falls back to the
 * user_id comparison in the parent component.
 */
const myHighlightIdsStore = writable<Set<string>>(new Set());

export function markHighlightAsMine(id: string): void {
  myHighlightIdsStore.update((s) => {
    const next = new Set(s);
    next.add(id);
    return next;
  });
}

export function isMyHighlight(id: string): boolean {
  let v = false;
  myHighlightIdsStore.subscribe((s) => (v = s.has(id)))();
  return v;
}

export { myHighlightIdsStore };

function cloneByMessage(
  byMessage: HighlightsByMessageId | undefined,
): HighlightsByMessageId {
  if (!byMessage) return {};
  const out: HighlightsByMessageId = {};
  for (const [k, v] of Object.entries(byMessage)) out[k] = [...v];
  return out;
}

/** Replace all highlights for a chat in one shot (used after cold-boot load). */
export function loadHighlightsForChat(
  chatId: string,
  highlights: MessageHighlight[],
): void {
  const byMessage: HighlightsByMessageId = {};
  for (const h of highlights) {
    if (!byMessage[h.message_id]) byMessage[h.message_id] = [];
    byMessage[h.message_id].push(h);
  }
  for (const k of Object.keys(byMessage)) {
    byMessage[k].sort((a, b) => a.created_at - b.created_at);
  }
  store.update((state) => ({ ...state, [chatId]: byMessage }));
}

/** Insert/replace a single highlight (used by send + inbound WS add/update). */
export function upsertHighlight(highlight: MessageHighlight): void {
  store.update((state) => {
    const chat = cloneByMessage(state[highlight.chat_id]);
    const list = chat[highlight.message_id] ? [...chat[highlight.message_id]] : [];
    const idx = list.findIndex((h) => h.id === highlight.id);
    if (idx >= 0) list[idx] = highlight;
    else list.push(highlight);
    list.sort((a, b) => a.created_at - b.created_at);
    chat[highlight.message_id] = list;
    return { ...state, [highlight.chat_id]: chat };
  });
}

/** Remove a single highlight (used by inbound WS remove + author delete). */
export function removeHighlight(
  chatId: string,
  messageId: string,
  highlightId: string,
): void {
  store.update((state) => {
    const chat = cloneByMessage(state[chatId]);
    const list = (chat[messageId] ?? []).filter((h) => h.id !== highlightId);
    if (list.length === 0) delete chat[messageId];
    else chat[messageId] = list;
    return { ...state, [chatId]: chat };
  });
}

/** Drop all highlights for a message (on message edit/delete). */
export function clearHighlightsForMessage(
  chatId: string,
  messageId: string,
): void {
  store.update((state) => {
    const chat = cloneByMessage(state[chatId]);
    delete chat[messageId];
    return { ...state, [chatId]: chat };
  });
}

/** Drop all highlights for a chat (on chat delete). */
export function clearHighlightsForChat(chatId: string): void {
  store.update((state) => {
    const next = { ...state };
    delete next[chatId];
    return next;
  });
}

/** Get the current array of highlights for a message (snapshot, not reactive). */
export function getHighlightsForMessageSnapshot(
  chatId: string,
  messageId: string,
): MessageHighlight[] {
  const chat = get(store)[chatId];
  if (!chat) return [];
  return chat[messageId] ?? [];
}

/** Reactive selector: all highlights for one message, sorted for navigation. */
export function selectHighlightsForMessage(
  chatId: string,
  messageId: string,
) {
  return derived(store, ($state) => {
    const byMsg = $state[chatId];
    const list = byMsg?.[messageId] ?? [];
    return sortHighlightsForNavigation(list);
  });
}

/** Reactive selector: aggregate counts for a chat (drives the ChatHeader pill). */
export function selectHighlightStatsForChat(chatId: string) {
  return derived(store, ($state) => {
    const byMessage = $state[chatId] ?? {};
    return countHighlightsAndComments(byMessage);
  });
}

/** Reactive selector: flat, sorted list of all highlights in a chat for navigation. */
export function selectHighlightsForChatFlat(chatId: string) {
  return derived(store, ($state) => {
    const byMessage = $state[chatId] ?? {};
    const all: MessageHighlight[] = [];
    for (const list of Object.values(byMessage)) all.push(...list);
    return sortHighlightsForNavigation(all).sort((a, b) => {
      // Group by message_id order first (oldest message first), then by offset.
      if (a.message_id === b.message_id) {
        if (a.kind === "text" && b.kind === "text") return a.start - b.start;
        return 0;
      }
      return a.created_at - b.created_at;
    });
  });
}
