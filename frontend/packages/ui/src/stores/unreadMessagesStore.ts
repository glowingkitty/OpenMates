// frontend/packages/ui/src/stores/unreadMessagesStore.ts
/**
 * @file unreadMessagesStore.ts
 * @description Svelte store for tracking unread messages per chat.
 *
 * A finished assistant reply stays unread until its last line has been visible
 * in the user's viewport. The server owns the persisted count (incremented when
 * a reply is persisted, broadcast with the reply's message_id); this store mirrors
 * it and also counts background completions optimistically. Each reply is counted
 * at most once, whichever signal arrives first.
 *
 * Unread counts are cleared when:
 * 1. The last line of the chat's latest reply is visible (ActiveChat)
 * 2. The user sends a follow-up (a reply is assumed read once answered)
 * 3. The user marks the chat as read from the context menu
 * Opening a chat alone does NOT clear the count.
 */
import { writable, get } from "svelte/store";
import { EMPTY_UNREAD_STATE, type UnreadEvent, type UnreadQuery, type UnreadState } from "./unreadReducer";

export interface UnreadMessagesState {
  /** Map of chat_id -> unread message count */
  unreadCounts: Map<string, number>;
}

const initialState: UnreadMessagesState = {
  unreadCounts: new Map(),
};

// Create the writable store
const { subscribe, update } = writable<UnreadMessagesState>(initialState);

// The shared Rust chatState unit owns the bookkeeping rules (once-per-reply counting,
// manual-unread set); the store keeps the reduced state as view state and mirrors the counts.
// There is no TypeScript fallback.
let rustState: UnreadState = EMPTY_UNREAD_STATE;
/** Mutations apply in call order; `settled()` resolves when all queued ones are mirrored. */
let rustQueue: Promise<void> = Promise.resolve();

function rustApply(event: UnreadEvent): void {
  rustQueue = rustQueue
    .then(async () => {
      const { chatStateCall } = await import("../services/rustCore/chatState/chatListUnitClient");
      rustState = await chatStateCall("unreadReduce", { state: rustState, event });
      update(() => ({ unreadCounts: new Map(rustState.counts) }));
    })
    .catch((error) => console.error("[unreadMessagesStore] Rust unread update failed", error));
}

export const unreadMessagesStore = {
  subscribe,

  /**
   * Rust read model of one chat: drains queued mutations first so the
   * answer reflects every earlier call. `persisted` is the chat's stored unread count.
   */
  queryUnread: async (chatId: string, persisted: number | null | undefined): Promise<UnreadQuery> => {
    await rustQueue;
    const { chatStateCall } = await import("../services/rustCore/chatState/chatListUnitClient");
    return chatStateCall("unreadQuery", { state: rustState, chat: chatId, persisted: persisted ?? null });
  },

  /** Resolves once every queued Rust-reduced mutation is visible. */
  settled: (): Promise<void> => rustQueue,

  /**
   * Increment unread count for a chat
   * Called when an AI message completes for a background chat
   * @param chatId The chat ID
   * @param messageId The reply that became unread; repeated calls for it are ignored
   */
  incrementUnread: (chatId: string, messageId?: string) => {
    return rustApply({ type: "increment", chat: chatId, messageId });
  },

  /**
   * Set unread count for a chat to a specific value.
   * Used by cross-device sync (chat_read_status_updated event) and phased sync
   * to reflect the server-authoritative unread count on this device.
   * @param chatId The chat ID
   * @param count The unread count to set (0 removes the entry)
   * @param messageId Reply the server counted, so a later local increment for it is ignored
   */
  setUnread: (chatId: string, count: number, messageId?: string) => {
    return rustApply({ type: "set", chat: chatId, count, messageId });
  },

  /**
   * Clear unread count for a chat
   * Called when user opens/views the chat
   * @param chatId The chat ID
   */
  clearUnread: (chatId: string) => {
    return rustApply({ type: "clear", chat: chatId });
  },

  /**
   * Mark a chat unread by explicit user action (context menu). The count is
   * exactly 1, and automatic "last line visible" read detection skips the chat
   * until the user leaves it or marks it read.
   */
  markManuallyUnread: (chatId: string) => {
    return rustApply({ type: "mark_manual", chat: chatId });
  },

  isManuallyUnread: (chatId: string): boolean =>
    rustState.manual.includes(chatId),

  /** Called when the user leaves a chat, so returning to it can mark it read again. */
  releaseManualUnread: (chatId: string) => {
    return rustApply({ type: "release_manual", chat: chatId });
  },

  /**
   * Get unread count for a specific chat
   * @param chatId The chat ID
   * @returns The unread count (0 if none)
   */
  getUnreadCount: (chatId: string): number => {
    const state = get({ subscribe });
    return state.unreadCounts.get(chatId) || 0;
  },

  /**
   * Get total unread count across all chats
   * @returns Total unread messages
   */
  getTotalUnread: (): number => {
    const state = get({ subscribe });
    let total = 0;
    state.unreadCounts.forEach((count) => {
      total += count;
    });
    return total;
  },

  /**
   * Clear all unread counts
   */
  clearAll: () => {
    return rustApply({ type: "clear_all" });
  },
};
