import { writable } from "svelte/store";
import type { SuggestedSettingsMemoryEntry } from "../types/apps";

/**
 * Store for prefilling the "create settings/memories entry" form when the user
 * clicks a suggestion card to customize before saving.
 *
 * When set, AppSettingsMemoriesCreateEntry (for the matching app_id + item_type)
 * will merge this data into the form and then clear the store.
 */
export const createEntryPrefillStore = writable<SuggestedSettingsMemoryEntry | null>(null);
