/**
 * Store for prefilling the entry edit form when the user clicks an AI-generated
 * deep link to update an existing settings/memories entry.
 *
 * When set, AppSettingsMemoriesEntryDetail (in edit mode) will show a diff view
 * comparing old values with the proposed new values, then clear the store.
 *
 * Architecture context: Replaces the old post-processing Phase 2 suggestion cards.
 * The AI now generates inline deep links with prefill data directly in its response.
 */
import { writable } from "svelte/store";

export interface UpdateEntryPrefill {
  /** The ID of the entry being updated */
  entryId: string;
  /** Map of field names to proposed new values (only changed fields) */
  prefillFields: Record<string, string | number | boolean>;
}

export const updateEntryPrefillStore = writable<UpdateEntryPrefill | null>(null);
