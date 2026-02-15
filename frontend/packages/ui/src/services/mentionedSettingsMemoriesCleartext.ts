/**
 * Builds cleartext for settings/memory mentions in message content.
 * When the user includes @memory:... or @memory-entry:... in a message, we resolve
 * the decrypted content from the client store and send it so the backend can use it
 * without requesting that category again.
 *
 * Key format: "app_id:item_key" (colon-separated, matches backend cache keys).
 * Value: list of entry contents (item_value) for that category.
 */

import { get } from "svelte/store";
import { appSettingsMemoriesStore } from "../stores/appSettingsMemoriesStore";

// Match @memory-entry first (longer pattern) to avoid partial match with @memory
const MEMORY_ENTRY_PATTERN =
  /@memory-entry:([a-zA-Z0-9_-]+):([a-zA-Z0-9_-]+):([a-zA-Z0-9_.-]+)/gi;
const MEMORY_PATTERN =
  /@memory:([a-zA-Z0-9_-]+):([a-zA-Z0-9_-]+):([a-zA-Z0-9_-]+)/gi;

export type MentionedSettingsMemoriesCleartext = Record<string, unknown[]>;

/**
 * Parses message content for @memory and @memory-entry mentions and returns
 * decrypted content per category key (app_id:item_key). Used when sending
 * the message so the backend receives cleartext and does not request those categories.
 *
 * @param content - Outgoing message content (markdown with mention syntax)
 * @returns Map of category key -> list of entry contents (same shape as backend cache)
 */
export function extractMentionedSettingsMemoriesCleartext(
  content: string,
): MentionedSettingsMemoriesCleartext {
  const result: MentionedSettingsMemoriesCleartext = {};
  const state = get(appSettingsMemoriesStore);
  const { entriesByApp, decryptedEntries } = state;

  // Collect category keys from @memory-entry (app_id, category_id, entry_id)
  const entryMatches = Array.from(content.matchAll(MEMORY_ENTRY_PATTERN));
  const seenEntryIds = new Set<string>();
  for (const match of entryMatches) {
    const appId = match[1];
    const categoryId = match[2];
    const entryId = match[3];
    const key = `${appId}:${categoryId}`;
    const entry = decryptedEntries.get(entryId);
    if (entry && entry.app_id === appId && entry.settings_group === categoryId) {
      if (!seenEntryIds.has(entryId)) {
        seenEntryIds.add(entryId);
        if (!result[key]) result[key] = [];
        result[key].push(entry.item_value);
      }
    }
  }

  // Collect full category content from @memory (app_id, memory_id, type)
  const memoryMatches = Array.from(content.matchAll(MEMORY_PATTERN));
  const seenCategoryKeys = new Set<string>();
  for (const match of memoryMatches) {
    const appId = match[1];
    const memoryId = match[2];
    const key = `${appId}:${memoryId}`;
    if (seenCategoryKeys.has(key)) continue;
    seenCategoryKeys.add(key);
    const appGroups = entriesByApp.get(appId);
    const entries = appGroups?.[memoryId];
    if (entries && entries.length > 0) {
      // Full category: list of all entry item_values (same shape as backend cache)
      result[key] = entries.map((e) => e.item_value);
    }
  }

  return result;
}
