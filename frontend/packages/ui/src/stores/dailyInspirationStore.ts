// frontend/packages/ui/src/stores/dailyInspirationStore.ts
// Svelte 4 writable store for Daily Inspiration banners.
//
// Stores up to 3 inspiration items received from the backend via WebSocket.
// The store drives DailyInspirationBanner.svelte (carousel on the new chat screen).
//
// NOTE: Stores in .ts files use Svelte 4 writable (not runes) — this is intentional.

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
}

export interface DailyInspirationState {
  /** Up to 3 inspirations for the current day */
  inspirations: DailyInspiration[];
  /** Currently displayed index (0-based) */
  currentIndex: number;
}

// ─── Initial state ────────────────────────────────────────────────────────────

const initialState: DailyInspirationState = {
  inspirations: [],
  currentIndex: 0,
};

// ─── Store ────────────────────────────────────────────────────────────────────

const store = writable<DailyInspirationState>(initialState);

export const dailyInspirationStore = {
  subscribe: store.subscribe,

  /**
   * Replace all inspirations (e.g. on fresh WS delivery).
   * Resets the carousel index to 0.
   */
  setInspirations: (inspirations: DailyInspiration[]): void => {
    store.set({
      inspirations: inspirations.slice(0, 3),
      currentIndex: 0,
    });
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
