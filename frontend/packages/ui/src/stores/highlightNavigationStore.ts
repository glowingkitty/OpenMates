// frontend/packages/ui/src/stores/highlightNavigationStore.ts
//
// Navigation state for the highlights overlay. Keeps track of the currently
// focused highlight (by id), plus a monotonically incrementing `jumpRequestId`
// that listeners subscribe to — each tick of the counter means "scroll the
// current highlight into view now". Pure counter-based design so multiple
// clicks on the pill always re-trigger the scroll even when focus didn't move.

import { derived, writable, get } from "svelte/store";
import type { MessageHighlight } from "../types/chat";

interface HighlightNavigationState {
  chatId: string | null;
  focusedHighlightId: string | null;
  orderedHighlights: MessageHighlight[];
  jumpRequestId: number;
  overlayVisible: boolean;
}

const initial: HighlightNavigationState = {
  chatId: null,
  focusedHighlightId: null,
  orderedHighlights: [],
  jumpRequestId: 0,
  overlayVisible: false,
};

const store = writable<HighlightNavigationState>(initial);

export const highlightNavigationStore = { subscribe: store.subscribe };

export function setOrderedHighlights(
  chatId: string,
  highlights: MessageHighlight[],
): void {
  store.update((s) => ({
    ...s,
    chatId,
    orderedHighlights: highlights,
    // If focus is now invalid, clear it.
    focusedHighlightId:
      s.focusedHighlightId &&
      highlights.some((h) => h.id === s.focusedHighlightId)
        ? s.focusedHighlightId
        : null,
    overlayVisible: highlights.length > 1 && s.overlayVisible,
  }));
}

/** Jump to the first highlight (used when the ChatHeader pill is clicked). */
export function jumpToFirstHighlight(): void {
  store.update((s) => {
    if (s.orderedHighlights.length === 0) return s;
    const first = s.orderedHighlights[0];
    return {
      ...s,
      focusedHighlightId: first.id,
      jumpRequestId: s.jumpRequestId + 1,
      overlayVisible: s.orderedHighlights.length > 1,
    };
  });
}

export function jumpToHighlight(id: string): void {
  store.update((s) => {
    if (!s.orderedHighlights.some((h) => h.id === id)) return s;
    return {
      ...s,
      focusedHighlightId: id,
      jumpRequestId: s.jumpRequestId + 1,
      overlayVisible: s.orderedHighlights.length > 1,
    };
  });
}

export function jumpNext(): void {
  const s = get(store);
  if (s.orderedHighlights.length === 0) return;
  const idx = s.focusedHighlightId
    ? s.orderedHighlights.findIndex((h) => h.id === s.focusedHighlightId)
    : -1;
  const nextIdx = (idx + 1) % s.orderedHighlights.length;
  jumpToHighlight(s.orderedHighlights[nextIdx].id);
}

export function jumpPrev(): void {
  const s = get(store);
  if (s.orderedHighlights.length === 0) return;
  const idx = s.focusedHighlightId
    ? s.orderedHighlights.findIndex((h) => h.id === s.focusedHighlightId)
    : 0;
  const prevIdx = (idx - 1 + s.orderedHighlights.length) % s.orderedHighlights.length;
  jumpToHighlight(s.orderedHighlights[prevIdx].id);
}

export function hideOverlay(): void {
  store.update((s) => ({ ...s, overlayVisible: false }));
}

export function clearNavigation(): void {
  store.set(initial);
}

/** Is there a previous / next highlight to step to? Cheap derived for UI. */
export const hasMultipleHighlights = derived(
  store,
  ($s) => $s.orderedHighlights.length > 1,
);
