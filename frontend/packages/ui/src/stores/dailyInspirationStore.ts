// frontend/packages/ui/src/stores/dailyInspirationStore.ts
// Svelte 4 writable store for Daily Inspiration banners.
//
// Stores up to 3 inspiration items received from the backend via WebSocket or
// loaded via loadDefaultInspirations() on page load.
//
// The store drives DailyInspirationBanner.svelte (carousel on the new chat screen).
//
// The store starts EMPTY. The banner is hidden when there are no inspirations
// (DailyInspirationBanner.svelte wraps content in {#if inspirations.length > 0}).
// Inspirations are populated by:
//   1. loadDefaultInspirations() on page load (fetches published server defaults)
//   2. WebSocket events delivering personalised inspirations (replace defaults)
//   3. IndexedDB / Directus on login sync (restores persisted inspirations)
//
// NOTE: Stores in .ts files use Svelte 4 writable (not runes) — this is intentional.
//
// PERSISTENCE ARCHITECTURE:
// - Personalised inspirations are persisted to IndexedDB (encrypted) via dailyInspirationDB.ts
// - They are also synced to Directus for cross-device / re-login recovery
// - The `is_opened` flag is set locally immediately when user starts a chat, then
//   synced to the API. Opened inspirations still appear in the carousel but are not
//   shown as the default card (next unopened is preferred).

import { writable } from "svelte/store";

// ─── Types ────────────────────────────────────────────────────────────────────

export interface DailyInspirationVideo {
  youtube_id: string;
  title: string;
  thumbnail_url: string;
  channel_name: string | null;
  view_count: number | null;
  duration_seconds: number | null;
  published_at: string | null;
}

export interface DailyInspiration {
  inspiration_id: string;
  phrase: string;
  category: string;
  /** Currently always 'video'. Future: 'article' | 'fact' | 'challenge' | 'project' | 'podcast' */
  content_type: string;
  video: DailyInspirationVideo | null;
  generated_at: number;
  /** First assistant message content (phrase + embed reference). Used for persistence. */
  assistant_response?: string;
  /** UUID of the embed created for the video, if any. Set after embed is stored. */
  embed_id?: string | null;
  /** Whether the user has already started a chat from this inspiration. */
  is_opened?: boolean;
  /** Hashed chat ID created from this inspiration (set after chat creation). */
  opened_chat_id?: string | null;
}

export interface DailyInspirationState {
  /** Up to 3 inspirations for the current day */
  inspirations: DailyInspiration[];
  /** Currently displayed index (0-based). Prefers the first unopened inspiration. */
  currentIndex: number;
}

// ─── Initial state ────────────────────────────────────────────────────────────

// Start empty — the banner is hidden until defaults are loaded from the server
// (loadDefaultInspirations on page load) or personalized ones arrive via WebSocket.
const initialState: DailyInspirationState = {
  inspirations: [],
  currentIndex: 0,
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

/**
 * Find the preferred carousel index — the first inspiration that is NOT opened.
 * Falls back to 0 if all are opened (or none are present).
 */
function preferredIndex(inspirations: DailyInspiration[]): number {
  if (inspirations.length === 0) return 0;
  const firstUnopenedIdx = inspirations.findIndex((i) => !i.is_opened);
  return firstUnopenedIdx >= 0 ? firstUnopenedIdx : 0;
}

// ─── Store ────────────────────────────────────────────────────────────────────

const store = writable<DailyInspirationState>(initialState);

export const dailyInspirationStore = {
  subscribe: store.subscribe,

  /**
   * Replace all inspirations (e.g. on fresh WS delivery or login sync).
   * Automatically positions the carousel at the first unopened inspiration.
   */
  setInspirations: (inspirations: DailyInspiration[]): void => {
    const sliced = inspirations.slice(0, 3);
    store.set({
      inspirations: sliced,
      currentIndex: preferredIndex(sliced),
    });
  },

  /**
   * Mark a specific inspiration as opened (user has started a chat from it).
   * The carousel remains visible; the next unopened becomes the default.
   */
  markOpened: (inspirationId: string, openedChatId?: string): void => {
    store.update((state) => {
      const updatedInspirations = state.inspirations.map((i) => {
        if (i.inspiration_id === inspirationId) {
          return {
            ...i,
            is_opened: true,
            opened_chat_id: openedChatId ?? i.opened_chat_id ?? null,
          };
        }
        return i;
      });
      return {
        inspirations: updatedInspirations,
        // Move to the next unopened inspiration as the new default
        currentIndex: preferredIndex(updatedInspirations),
      };
    });
  },

  /**
   * Update the embed_id on an inspiration after the video embed has been stored.
   * This is called from handleDailyInspirationImpl before persisting to IndexedDB.
   */
  setEmbedId: (inspirationId: string, embedId: string): void => {
    store.update((state) => ({
      ...state,
      inspirations: state.inspirations.map((i) =>
        i.inspiration_id === inspirationId ? { ...i, embed_id: embedId } : i,
      ),
    }));
  },

  /**
   * Navigate to the next inspiration in the carousel.
   * Wraps around to the first if at the end.
   */
  next: (): void => {
    store.update((state) => {
      if (state.inspirations.length === 0) return state;
      return {
        ...state,
        currentIndex: (state.currentIndex + 1) % state.inspirations.length,
      };
    });
  },

  /**
   * Navigate to the previous inspiration in the carousel.
   * Wraps around to the last if at the start.
   */
  previous: (): void => {
    store.update((state) => {
      if (state.inspirations.length === 0) return state;
      return {
        ...state,
        currentIndex:
          (state.currentIndex - 1 + state.inspirations.length) %
          state.inspirations.length,
      };
    });
  },

  /**
   * Navigate directly to a specific index.
   */
  goTo: (index: number): void => {
    store.update((state) => {
      if (index < 0 || index >= state.inspirations.length) return state;
      return { ...state, currentIndex: index };
    });
  },

  /**
   * Clear all inspirations (e.g. on logout).
   */
  reset: (): void => {
    store.set({ ...initialState });
  },
};
