// frontend/packages/ui/src/demo_chats/loadDefaultInspirations.ts
//
// Loads Daily Inspiration entries for the DailyInspirationBanner on page load.
//
// PRIORITY ORDER (highest to lowest):
//   1. IndexedDB — persisted personalised inspirations from previous WS delivery
//      These survive page reloads and are preferred over server defaults.
//      Only used when master key is present (i.e. user is logged in or
//      'stay logged in' is enabled).
//   2. Server defaults — published inspirations from /v1/default-inspirations
//      Public endpoint, no auth required. Used as a fallback for new sessions
//      or logged-out users.
//
// This function is called once on page load (+page.svelte) alongside
// loadCommunityDemos(). It returns immediately (no loading gate) — the banner
// simply stays hidden until data arrives (store starts as empty array).
//
// ARCHITECTURE:
// - Personalized WS inspirations still take priority. If the WS delivers new
//   inspirations AFTER this function runs, the store is replaced (store.set).
// - If IndexedDB has stale or expired inspirations, dailyInspirationDB.ts
//   filters them out (TTL = 72 h) so we fall through to server defaults.

import { get } from "svelte/store";
import { locale as svelteLocaleStore, waitLocale } from "svelte-i18n";
import { getApiEndpoint } from "../config/api";
import {
  dailyInspirationStore,
  type DailyInspiration,
} from "../stores/dailyInspirationStore";

const LOG_PREFIX = "[loadDefaultInspirations]";

/**
 * Populate the daily inspiration store on page load.
 *
 * Tries IndexedDB first (persisted personalised inspirations from previous
 * WebSocket delivery), then falls back to the public server defaults endpoint.
 *
 * Only populates the store if it is currently empty — personalized inspirations
 * delivered via WebSocket earlier in the same session take precedence.
 */
export async function loadDefaultInspirations(): Promise<void> {
  try {
    // Skip immediately if the store is already populated by a WS delivery
    // that raced ahead of us (e.g. fast reconnect).
    const current = get(dailyInspirationStore);
    if (current.inspirations.length > 0) {
      console.debug(
        `${LOG_PREFIX} Store already populated (${current.inspirations.length} items) — skipping`,
      );
      return;
    }

    // ── Step 1: Try IndexedDB ─────────────────────────────────────────────────
    // Attempt to load persisted personalised inspirations. This is fast (local)
    // and only works if the user has a master key (i.e. is logged in or has
    // "stay logged in" enabled from a previous session).
    try {
      const { loadInspirationsFromIndexedDB } =
        await import("../services/dailyInspirationDB");
      const persisted = await loadInspirationsFromIndexedDB();

      if (persisted.length > 0) {
        // Re-check store — a WS event may have arrived during the async load
        const currentNow = get(dailyInspirationStore);
        if (currentNow.inspirations.length === 0) {
          dailyInspirationStore.setInspirations(persisted);
          console.debug(
            `${LOG_PREFIX} Loaded ${persisted.length} personalised inspiration(s) from IndexedDB`,
          );
          // Return — IndexedDB wins over server defaults
          return;
        } else {
          console.debug(
            `${LOG_PREFIX} WS delivered inspirations while loading from IndexedDB — keeping WS data`,
          );
          return;
        }
      }
    } catch (idbError) {
      // Non-fatal: master key not available (guest user / session expired) or
      // IndexedDB not accessible. Fall through to server defaults.
      console.debug(
        `${LOG_PREFIX} IndexedDB load skipped or failed (will use server defaults):`,
        idbError,
      );
    }

    // ── Step 2: Fall back to server defaults ──────────────────────────────────
    await waitLocale();
    const currentLang = get(svelteLocaleStore) || "en";
    console.debug(
      `${LOG_PREFIX} Fetching server default inspirations for lang=${currentLang}`,
    );

    const url = getApiEndpoint(`/v1/default-inspirations?lang=${currentLang}`);
    const response = await fetch(url);

    if (!response.ok) {
      console.warn(
        `${LOG_PREFIX} Server returned ${response.status} — skipping default inspirations`,
      );
      return;
    }

    const data = await response.json();
    const inspirations: DailyInspiration[] = data.inspirations || [];

    if (inspirations.length === 0) {
      console.debug(
        `${LOG_PREFIX} No default inspirations available from server`,
      );
      return;
    }

    // Only populate the store if it is still empty — personalized inspirations
    // delivered via WebSocket or loaded from IndexedDB have priority.
    const currentFinal = get(dailyInspirationStore);
    if (currentFinal.inspirations.length > 0) {
      console.debug(
        `${LOG_PREFIX} Store populated while fetching defaults — skipping server defaults`,
      );
      return;
    }

    dailyInspirationStore.setInspirations(inspirations);
    console.debug(
      `${LOG_PREFIX} Loaded ${inspirations.length} server default inspiration(s) into store`,
    );
  } catch (error) {
    // Non-fatal: banner simply remains hidden until personalized ones arrive
    console.error(`${LOG_PREFIX} Failed to load inspirations:`, error);
  }
}
