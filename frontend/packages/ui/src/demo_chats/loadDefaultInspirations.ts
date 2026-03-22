// frontend/packages/ui/src/demo_chats/loadDefaultInspirations.ts
//
// Loads Daily Inspiration entries for the DailyInspirationBanner on page load.
/* eslint-disable no-console */
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

const OG_EXAMPLE_SHARED_CHAT_CUTTLEFISH = "shared_chat_cuttlefish";

function getOgExampleInspirations(exampleId: string): DailyInspiration[] {
  if (exampleId !== OG_EXAMPLE_SHARED_CHAT_CUTTLEFISH) {
    return [];
  }

  return [
    {
      inspiration_id: "og-cut-1",
      phrase: "How cuttlefish camouflage works",
      title: "Cuttlefish Camouflage Mechanism",
      category: "biology",
      content_type: "video",
      video: {
        youtube_id: "3s0LTDhqe5A",
        title: "How Cuttlefish Instantly Change Color",
        thumbnail_url: "https://i.ytimg.com/vi/3s0LTDhqe5A/hqdefault.jpg",
        channel_name: "Nature Explained",
        view_count: 824000,
        duration_seconds: 412,
        published_at: "2024-02-14T00:00:00Z",
      },
      generated_at: 1731000000,
      assistant_response:
        "Cuttlefish use chromatophores, iridophores, and papillae to blend into coral, sand, and rocks in milliseconds.",
      follow_up_suggestions: [
        "Show real-world camouflage examples",
        "Explain chromatophores simply",
        "Compare cuttlefish and octopus camouflage",
      ],
    },
    {
      inspiration_id: "og-cut-2",
      phrase: "Mimicry in marine animals",
      title: "Marine Mimicry in Action",
      category: "nature",
      content_type: "video",
      video: {
        youtube_id: "rK8eM4pS4wA",
        title: "Ocean Masters of Disguise",
        thumbnail_url: "https://i.ytimg.com/vi/rK8eM4pS4wA/hqdefault.jpg",
        channel_name: "Ocean Lab",
        view_count: 512000,
        duration_seconds: 355,
        published_at: "2023-11-03T00:00:00Z",
      },
      generated_at: 1731000300,
      assistant_response:
        "Many marine species imitate textures, movement, and color patterns to avoid predators and surprise prey.",
      follow_up_suggestions: [
        "Top 5 mimicry species",
        "How mimicry evolved",
        "Mimicry vs camouflage",
      ],
    },
    {
      inspiration_id: "og-cut-3",
      phrase: "Animal intelligence in cephalopods",
      title: "Cephalopod Intelligence Facts",
      category: "science",
      content_type: "video",
      video: {
        youtube_id: "Y7Qb2T7k4fY",
        title: "Why Cephalopods Are So Smart",
        thumbnail_url: "https://i.ytimg.com/vi/Y7Qb2T7k4fY/hqdefault.jpg",
        channel_name: "Bio Stories",
        view_count: 691000,
        duration_seconds: 498,
        published_at: "2024-01-09T00:00:00Z",
      },
      generated_at: 1731000600,
      assistant_response:
        "Cuttlefish and octopuses solve puzzles, remember environments, and adapt behavior quickly in changing conditions.",
      follow_up_suggestions: [
        "Examples of puzzle-solving",
        "How memory is tested",
        "Best cephalopod documentaries",
      ],
    },
  ];
}

/**
 * Populate the daily inspiration store on page load.
 *
 * Tries IndexedDB first (persisted personalised inspirations from previous
 * WebSocket delivery), then falls back to the public server defaults endpoint.
 *
 * Only populates the store if it is currently empty — personalized inspirations
 * delivered via WebSocket earlier in the same session take precedence.
 */
export async function loadDefaultInspirations(
  options: { allowIndexedDB?: boolean } = {},
): Promise<void> {
  try {
    const { allowIndexedDB = true } = options;

    const urlParams =
      typeof window !== "undefined"
        ? new URLSearchParams(window.location.search)
        : null;

    // --- Media mode: ?media=1&inspirations=none|fixed ---
    // none  → skip loading entirely (banner stays hidden)
    // fixed → load OG fixture inspirations for deterministic capture
    if (urlParams?.get("media") === "1") {
      const inspirationsParam = urlParams.get("inspirations");
      if (inspirationsParam === "none") {
        console.debug(`${LOG_PREFIX} Media mode: inspirations=none — skipping`);
        return;
      }
      if (inspirationsParam === "fixed") {
        const fixtureInspirations = getOgExampleInspirations("shared_chat_cuttlefish");
        if (fixtureInspirations.length > 0) {
          dailyInspirationStore.setInspirations(fixtureInspirations, {
            personalized: false,
          });
          console.debug(
            `${LOG_PREFIX} Media mode: loaded ${fixtureInspirations.length} fixed inspiration(s)`,
          );
        }
        return;
      }
    }

    const ogExample = urlParams?.get("og_example") ?? null;

    if (ogExample) {
      const fixtureInspirations = getOgExampleInspirations(ogExample);
      if (fixtureInspirations.length > 0) {
        dailyInspirationStore.setInspirations(fixtureInspirations, {
          personalized: false,
        });
        console.debug(
          `${LOG_PREFIX} Loaded ${fixtureInspirations.length} OG fixture inspiration(s) for ${ogExample}`,
        );
        return;
      }
    }

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
    if (allowIndexedDB) {
      try {
        const { loadInspirationsFromIndexedDB } =
          await import("../services/dailyInspirationDB");
        const persisted = await loadInspirationsFromIndexedDB();

        if (persisted.length > 0) {
          // Re-check store — a WS event or Phase 1 sync may have arrived during the async load.
          // If personalized data already landed, skip — it has is_opened / opened_chat_id state
          // that must not be overwritten by anything from this function.
          const currentNow = get(dailyInspirationStore);
          if (currentNow.isPersonalized) {
            console.debug(
              `${LOG_PREFIX} Personalized inspirations already in store — skipping IndexedDB load`,
            );
            return;
          }
          if (currentNow.inspirations.length === 0) {
            // IndexedDB data is from a prior authenticated session — it IS personalized
            // (it was written by processInspirationRecordsFromSync with is_opened state).
            dailyInspirationStore.setInspirations(persisted, {
              personalized: true,
            });
            console.debug(
              `${LOG_PREFIX} Loaded ${persisted.length} personalised inspiration(s) from IndexedDB`,
            );
            // Return — IndexedDB wins over server defaults
            return;
          }
          console.debug(
            `${LOG_PREFIX} WS delivered inspirations while loading from IndexedDB — keeping WS data`,
          );
          return;
        }
      } catch (idbError) {
        // Non-fatal: fall through to server defaults. During logout/cleanup the DB
        // is intentionally blocked — downgrade to debug. For authenticated users,
        // keep it as error since it indicates a real problem (master key race, etc.).
        if (
          idbError instanceof Error &&
          idbError.message?.includes("blocked during logout")
        ) {
          console.debug(
            `${LOG_PREFIX} DB unavailable during cleanup — falling back to server defaults`,
          );
        } else {
          console.error(
            `${LOG_PREFIX} IndexedDB load failed — falling back to server defaults. Error:`,
            idbError,
          );
        }
      }
    } else {
      console.debug(`${LOG_PREFIX} IndexedDB step skipped by caller`);
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
      console.error(
        `${LOG_PREFIX} Server returned ${response.status} fetching default inspirations — no banner will be shown`,
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

    // Only populate the store if it is still empty and does not already hold
    // personalized data — personalized inspirations (with is_opened / opened_chat_id
    // state) delivered via Phase 1 WS sync, WS event, or IndexedDB have priority.
    const currentFinal = get(dailyInspirationStore);
    if (currentFinal.isPersonalized) {
      console.debug(
        `${LOG_PREFIX} Personalized inspirations in store while fetching defaults — skipping server defaults`,
      );
      return;
    }
    if (currentFinal.inspirations.length > 0) {
      console.debug(
        `${LOG_PREFIX} Store populated while fetching defaults — skipping server defaults`,
      );
      return;
    }

    // Public server defaults: not personalized (no is_opened / opened_chat_id).
    // setInspirations guards against overwriting personalized data, so this is safe.
    dailyInspirationStore.setInspirations(inspirations, {
      personalized: false,
    });
    console.debug(
      `${LOG_PREFIX} Loaded ${inspirations.length} server default inspiration(s) into store`,
    );
  } catch (error) {
    // Non-fatal: banner simply remains hidden until personalized ones arrive
    console.error(`${LOG_PREFIX} Failed to load inspirations:`, error);
  }
}
