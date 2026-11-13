// frontend/packages/ui/src/stores/chatRecommendationsStore.ts
//
// In-memory, per-chat ChatRecommendationsState shown by the Recommendations card.
// Plaintext only lives here and in the encrypted chats.encrypted_recommendations
// field; persistence and decryption live in services/chatRecommendationsPersistence.ts.
// Duplicate/dismiss policy is the Rust core's reconcile step, never this store.
// Plan: docs/plans/chat-recommendations/plan.yml (D-7, wire_contract.client_storage)

import { derived, get, writable, type Readable } from 'svelte/store';
import type {
  ChatRecommendation,
  ChatRecommendationsState,
} from '../types/recommendations';

const MAX_TITLE_LIST = 200;

const store = writable<Record<string, ChatRecommendationsState>>({});

/** Read-only map chat id -> recommendations state. */
export const chatRecommendations: Readable<Record<string, ChatRecommendationsState>> = {
  subscribe: store.subscribe,
};

/** Open recommendations of one chat (empty when none are known). */
export function chatRecommendationItems(chatId: string): Readable<ChatRecommendation[]> {
  return derived(store, (states) => states[chatId]?.items ?? []);
}

export function nowSeconds(): number {
  return Math.floor(Date.now() / 1000);
}

export function emptyChatRecommendationsState(updatedAt = nowSeconds()): ChatRecommendationsState {
  return { schema_version: 1, items: [], dismissed: [], resolved: [], updated_at: updatedAt };
}

function isRecommendation(value: unknown): value is ChatRecommendation {
  if (!value || typeof value !== 'object') return false;
  const item = value as Record<string, unknown>;
  return typeof item.id === 'string' && item.id.length > 0
    && (item.kind === 'memory' || item.kind === 'workflow')
    && (item.action === 'create' || item.action === 'update')
    && (item.target_id === null || typeof item.target_id === 'string')
    && typeof item.title === 'string' && item.title.trim().length > 0
    && typeof item.summary === 'string';
}

function isTitleList(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((entry) => typeof entry === 'string');
}

/**
 * Validates the decrypted JSON of chats.encrypted_recommendations.
 * Returns null for anything that is not a schema_version 1 state.
 */
export function parseChatRecommendationsState(json: string): ChatRecommendationsState | null {
  let raw: unknown;
  try {
    raw = JSON.parse(json);
  } catch {
    return null;
  }
  if (!raw || typeof raw !== 'object') return null;
  const state = raw as Record<string, unknown>;
  if (state.schema_version !== 1 || !Array.isArray(state.items)
    || !state.items.every(isRecommendation)
    || !isTitleList(state.dismissed) || !isTitleList(state.resolved)
    || typeof state.updated_at !== 'number' || !Number.isFinite(state.updated_at)) {
    return null;
  }
  return {
    schema_version: 1,
    items: state.items,
    dismissed: state.dismissed,
    resolved: state.resolved,
    updated_at: state.updated_at,
  };
}

export function getChatRecommendations(chatId: string): ChatRecommendationsState | null {
  return get(store)[chatId] ?? null;
}

/** Replace (or with null, forget) the state held for one chat. */
export function setChatRecommendations(chatId: string, state: ChatRecommendationsState | null): void {
  store.update((states) => {
    if (!state) {
      if (!(chatId in states)) return states;
      const next = { ...states };
      delete next[chatId];
      return next;
    }
    return { ...states, [chatId]: state };
  });
}

/** Forget every chat (logout / account switch). */
export function clearAllChatRecommendations(): void {
  store.set({});
}

/**
 * The state without recommendation `id`, with its title appended to `list`
 * ('dismissed' on dismiss, 'resolved' on save). Null when the item is unknown.
 * The Rust reconcile step normalizes these titles when it compares them.
 */
export function withRecommendationRemoved(
  state: ChatRecommendationsState,
  id: string,
  list: 'dismissed' | 'resolved',
  updatedAt = nowSeconds(),
): ChatRecommendationsState | null {
  const item = state.items.find((entry) => entry.id === id);
  if (!item) return null;
  const titles = state[list].includes(item.title) ? state[list] : [...state[list], item.title];
  return {
    ...state,
    items: state.items.filter((entry) => entry.id !== id),
    [list]: titles.slice(-MAX_TITLE_LIST),
    updated_at: updatedAt,
  };
}
