// frontend/packages/ui/src/demo_chats/loadDefaultInspirations.ts
//
// Fetches default Daily Inspiration entries from the server and populates
// dailyInspirationStore when no personalized inspirations are present.
//
// ARCHITECTURE:
// - Called once on page load (+page.svelte) alongside loadCommunityDemos()
// - Only populates the store if it is still empty (i.e. no personalised
//   inspirations have arrived via WebSocket before this call resolves)
// - Returns immediately (no loading gate) — the banner simply stays hidden
//   until data arrives (store starts as empty array)
// - Uses the browser's Accept-Language header value (read from
//   document.documentElement.lang, same pattern as community demos)

import { get } from "svelte/store";
import { locale as svelteLocaleStore, waitLocale } from "svelte-i18n";
import { getApiEndpoint } from "../config/api";
import {
  dailyInspirationStore,
  type DailyInspiration,
} from "../stores/dailyInspirationStore";

const LOG_PREFIX = "[loadDefaultInspirations]";

/**
 * Fetch published default Daily Inspirations from the server and set them in
 * the store, but only if the store currently has no inspirations.
 *
 * This prevents overwriting personalized inspirations that may have arrived
 * earlier via WebSocket.
 */
export async function loadDefaultInspirations(): Promise<void> {
  try {
    // Wait for locale to be ready so we send the right language
    await waitLocale();

    const currentLang = get(svelteLocaleStore) || "en";
    console.debug(
      `${LOG_PREFIX} Fetching default inspirations for lang=${currentLang}`,
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
    // delivered via WebSocket have priority.
    const current = get(dailyInspirationStore);
    if (current.inspirations.length > 0) {
      console.debug(
        `${LOG_PREFIX} Store already has ${current.inspirations.length} inspiration(s) — skipping defaults`,
      );
      return;
    }

    dailyInspirationStore.setInspirations(inspirations);
    console.debug(
      `${LOG_PREFIX} Loaded ${inspirations.length} default inspiration(s) into store`,
    );
  } catch (error) {
    // Non-fatal: banner simply remains hidden until personalized ones arrive
    console.error(`${LOG_PREFIX} Failed to load default inspirations:`, error);
  }
}
