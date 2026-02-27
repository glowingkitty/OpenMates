/**
 * appStoreNavigationStore.ts
 *
 * Stores the prev/next navigation state for app store sub-item pages:
 * skills, focus modes, and settings/memories categories within a single app.
 *
 * Mirrors the pattern of chatNavigationStore.ts — a sibling of the current
 * item is identified from the full list, and navigation dispatches an
 * openSettings event back through the settings panel.
 *
 * Updated by SkillDetails, FocusModeDetails, and AppSettingsMemoriesCategory
 * whenever the component mounts or the current item changes.
 *
 * Read by AppDetailsHeader to show/hide the prev/next arrow buttons and to
 * trigger navigation via the navigate methods.
 *
 * Navigation flow:
 *   1. A sub-item page (SkillDetails etc.) calls setAppStoreNavList() with:
 *        – the full ordered list of sibling items (id + name)
 *        – the current item's ID
 *        – a navigate callback that dispatches 'openSettings' with the target path
 *   2. AppDetailsHeader reads appStoreNavigationStore for hasPrev/hasNext flags
 *      and calls navigatePrev() / navigateNext() when the arrow buttons are clicked.
 *   3. The store calls the registered navigate callback with the target item ID.
 */

import { writable } from "svelte/store";

// ─── Types ────────────────────────────────────────────────────────────────────

/** A single navigable item (skill, focus mode, or settings/memories category). */
export interface AppStoreNavItem {
  /** Unique ID within the app (skill.id, focusMode.id, category.id). */
  id: string;
  /** Display name for the aria-label on the arrow buttons. */
  name: string;
}

/** The store shape exposed to AppDetailsHeader. */
export interface AppStoreNavigationState {
  hasPrev: boolean;
  hasNext: boolean;
  /** Name of the previous item, used for aria-label. Empty when hasPrev=false. */
  prevName: string;
  /** Name of the next item, used for aria-label. Empty when hasNext=false. */
  nextName: string;
}

// ─── Internal state ───────────────────────────────────────────────────────────

/** The ordered list of sibling items for the currently open sub-item page. */
let navItems: AppStoreNavItem[] = [];

/** The ID of the currently displayed sub-item. */
let currentItemId: string | null = null;

/**
 * Callback registered by the current sub-item component.
 * Called with the target item ID when the user presses a nav arrow.
 * The component is responsible for dispatching the openSettings event.
 */
let navigateCallback: ((itemId: string) => void) | null = null;

// ─── Store ────────────────────────────────────────────────────────────────────

/**
 * The hasPrev/hasNext flags + adjacent item names for AppDetailsHeader.
 * Write from sub-item pages via setAppStoreNavList.
 * Read from AppDetailsHeader to render arrow buttons.
 */
export const appStoreNavigationStore = writable<AppStoreNavigationState>({
  hasPrev: false,
  hasNext: false,
  prevName: "",
  nextName: "",
});

// ─── Public API ───────────────────────────────────────────────────────────────

/**
 * Register the full list of sibling items, the current item, and the
 * navigation callback for the currently open sub-item page.
 *
 * Called by SkillDetails, FocusModeDetails, and AppSettingsMemoriesCategory
 * on component init ($effect) so that the store is always up to date.
 * Also works correctly when a sub-item page is opened via deep link because
 * the page calls this on mount regardless of how the user arrived.
 *
 * @param items        All sibling items (ordered list — same order shown in the app).
 * @param activeItemId The id of the currently displayed item.
 * @param onNavigate   Called with the target item id when an arrow is pressed.
 */
export function setAppStoreNavList(
  items: AppStoreNavItem[],
  activeItemId: string,
  onNavigate: (itemId: string) => void,
): void {
  navItems = items;
  currentItemId = activeItemId;
  navigateCallback = onNavigate;
  _updateStore();
}

/**
 * Clear all navigation state.
 * Called when navigating away from a sub-item page to the app detail or
 * another settings page so stale arrows don't bleed through.
 */
export function clearAppStoreNav(): void {
  navItems = [];
  currentItemId = null;
  navigateCallback = null;
  appStoreNavigationStore.set({
    hasPrev: false,
    hasNext: false,
    prevName: "",
    nextName: "",
  });
}

/**
 * Navigate to the previous sibling item.
 * No-op if there is no previous item or no navigate callback registered.
 */
export function appStoreNavigatePrev(): void {
  if (!navigateCallback || navItems.length === 0 || currentItemId === null)
    return;

  const idx = navItems.findIndex((item) => item.id === currentItemId);
  if (idx <= 0) return; // Already at the start

  const target = navItems[idx - 1];
  if (!target) return;

  currentItemId = target.id;
  navigateCallback(target.id);
  _updateStore();
}

/**
 * Navigate to the next sibling item.
 * No-op if there is no next item or no navigate callback registered.
 */
export function appStoreNavigateNext(): void {
  if (!navigateCallback || navItems.length === 0 || currentItemId === null)
    return;

  const idx = navItems.findIndex((item) => item.id === currentItemId);
  if (idx < 0 || idx >= navItems.length - 1) return; // Already at the end

  const target = navItems[idx + 1];
  if (!target) return;

  currentItemId = target.id;
  navigateCallback(target.id);
  _updateStore();
}

// ─── Internal helpers ─────────────────────────────────────────────────────────

/**
 * Recompute and push the hasPrev/hasNext flags + adjacent item names to the store.
 */
function _updateStore(): void {
  if (navItems.length === 0 || currentItemId === null) {
    appStoreNavigationStore.set({
      hasPrev: false,
      hasNext: false,
      prevName: "",
      nextName: "",
    });
    return;
  }

  const idx = navItems.findIndex((item) => item.id === currentItemId);
  const hasPrev = idx > 0;
  const hasNext = idx >= 0 && idx < navItems.length - 1;

  appStoreNavigationStore.set({
    hasPrev,
    hasNext,
    prevName: hasPrev ? (navItems[idx - 1]?.name ?? "") : "",
    nextName: hasNext ? (navItems[idx + 1]?.name ?? "") : "",
  });
}
