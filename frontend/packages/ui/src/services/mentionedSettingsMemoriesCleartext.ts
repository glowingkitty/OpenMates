/**
 * Builds cleartext for settings/memory mentions in message content.
 * When the user includes @memory:... or @memory-entry:... in a message, we resolve
 * the decrypted content and send it so the backend can use it directly — no
 * permission dialog or extra roundtrip needed.
 *
 * Uses the Svelte store as fast path, falls back to IndexedDB + decryption
 * when the store snapshot is stale or missing entries.
 *
 * Key format: "app_id:item_key" (colon-separated, matches backend cache keys).
 * Value: list of entry contents (item_value) for that category.
 */

import { get } from "svelte/store";
import { appSettingsMemoriesStore } from "../stores/appSettingsMemoriesStore";
import { chatDB } from "./db";
import { decryptWithMasterKey } from "./cryptoService";

// Match @memory-entry first (longer pattern) to avoid partial match with @memory
const MEMORY_ENTRY_PATTERN =
  /@memory-entry:([a-zA-Z0-9_-]+):([a-zA-Z0-9_-]+):([a-zA-Z0-9_.-]+)/gi;
const MEMORY_PATTERN =
  /@memory:([a-zA-Z0-9_-]+):([a-zA-Z0-9_-]+):([a-zA-Z0-9_-]+)/gi;

export type MentionedSettingsMemoriesCleartext = Record<string, unknown[]>;

/**
 * Decrypts a single IndexedDB entry's encrypted_item_json and returns the parsed value.
 * Returns null if decryption or parsing fails.
 */
async function decryptEntryFromDB(
  entryId: string,
): Promise<Record<string, unknown> | null> {
  try {
    const dbEntry = await chatDB.getAppSettingsMemoriesEntry(entryId);
    if (!dbEntry?.encrypted_item_json) return null;

    const decryptedJson = await decryptWithMasterKey(
      dbEntry.encrypted_item_json,
    );
    if (!decryptedJson) return null;

    return JSON.parse(decryptedJson) as Record<string, unknown>;
  } catch (err) {
    console.warn(
      `[MentionedCleartext] Failed to decrypt entry ${entryId} from IndexedDB:`,
      err,
    );
    return null;
  }
}

/**
 * Parses message content for @memory and @memory-entry mentions and returns
 * decrypted content per category key (app_id:item_key). Used when sending
 * the message so the backend receives cleartext and does not request those categories.
 *
 * @param content - Outgoing message content (markdown with mention syntax)
 * @returns Map of category key -> list of entry contents (same shape as backend cache)
 */
export async function extractMentionedSettingsMemoriesCleartext(
  content: string,
): Promise<MentionedSettingsMemoriesCleartext> {
  const result: MentionedSettingsMemoriesCleartext = {};
  const state = get(appSettingsMemoriesStore);
  const { entriesByApp, decryptedEntries } = state;

  // Debug: log what we're working with
  const hasEntryMention = content.includes("@memory-entry:");
  const hasMemoryMention = content.includes("@memory:");
  if (hasEntryMention || hasMemoryMention) {
    console.warn(
      `[MentionedCleartext] Extracting from content (${content.length} chars). ` +
        `Has @memory-entry: ${hasEntryMention}, @memory: ${hasMemoryMention}. ` +
        `Store: ${decryptedEntries.size} decrypted entries, ${entriesByApp.size} apps.`,
    );
  }

  // Collect category keys from @memory-entry (app_id, category_id, entry_id)
  const entryMatches = Array.from(content.matchAll(MEMORY_ENTRY_PATTERN));
  const seenEntryIds = new Set<string>();
  for (const match of entryMatches) {
    const appId = match[1];
    const categoryId = match[2];
    const entryId = match[3];
    const key = `${appId}:${categoryId}`;

    if (seenEntryIds.has(entryId)) continue;
    seenEntryIds.add(entryId);

    // Fast path: try the Svelte store snapshot
    let itemValue: Record<string, unknown> | undefined;
    const storeEntry = decryptedEntries.get(entryId);
    if (
      storeEntry &&
      storeEntry.app_id === appId &&
      storeEntry.settings_group === categoryId
    ) {
      itemValue = storeEntry.item_value;
    }

    // Fallback: read from IndexedDB and decrypt on the spot
    if (!itemValue) {
      console.info(
        `[MentionedCleartext] Entry ${entryId} not in store (${decryptedEntries.size} entries), trying IndexedDB...`,
      );
      const decrypted = await decryptEntryFromDB(entryId);
      if (decrypted) {
        itemValue = decrypted;
        console.info(
          `[MentionedCleartext] Successfully decrypted entry ${entryId} from IndexedDB for key ${key}`,
        );
      } else {
        console.warn(
          `[MentionedCleartext] Entry ${entryId} not found in IndexedDB either. Cleartext for ${key} will not be sent.`,
        );
      }
    }

    if (itemValue) {
      if (!result[key]) result[key] = [];
      result[key].push(itemValue);
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

    // Fast path: try the store
    const appGroups = entriesByApp.get(appId);
    const storeEntries = appGroups?.[memoryId];
    if (storeEntries && storeEntries.length > 0) {
      result[key] = storeEntries.map((e) => e.item_value);
      continue;
    }

    // Fallback: read all entries from IndexedDB, filter by app_id + item_type, decrypt
    console.info(
      `[MentionedCleartext] Category ${key} not in store, trying IndexedDB...`,
    );
    try {
      const allDbEntries = await chatDB.getAllAppSettingsMemoriesEntries();
      const categoryDbEntries = allDbEntries.filter(
        (e) => e.app_id === appId && e.item_type === memoryId,
      );
      if (categoryDbEntries.length > 0) {
        const decryptedValues: unknown[] = [];
        for (const dbEntry of categoryDbEntries) {
          try {
            const decryptedJson = await decryptWithMasterKey(
              dbEntry.encrypted_item_json,
            );
            if (decryptedJson) {
              decryptedValues.push(JSON.parse(decryptedJson));
            }
          } catch {
            // Skip entries that fail to decrypt
          }
        }
        if (decryptedValues.length > 0) {
          result[key] = decryptedValues;
          console.info(
            `[MentionedCleartext] Decrypted ${decryptedValues.length} entries from IndexedDB for category ${key}`,
          );
        }
      }
    } catch (err) {
      console.warn(
        `[MentionedCleartext] Failed to read category ${key} from IndexedDB:`,
        err,
      );
    }
  }

  const resultKeys = Object.keys(result);
  if (hasEntryMention || hasMemoryMention) {
    console.warn(
      `[MentionedCleartext] Result: ${resultKeys.length} key(s): ${resultKeys.join(", ") || "(empty)"}. ` +
        `Entry regex matches: ${entryMatches.length}, Memory regex matches: ${memoryMatches.length}.`,
    );
  }

  return result;
}
