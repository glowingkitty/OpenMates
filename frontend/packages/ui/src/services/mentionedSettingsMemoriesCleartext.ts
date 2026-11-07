/**
 * Builds cleartext for personal Memory mentions in message content.
 * When the user includes @memory:openmates:memories:... or
 * @memory-entry:openmates:memories:<id-or-title-slug> in a message, we resolve
 * the decrypted Memory and send it so the backend can use it directly - no
 * permission dialog or extra roundtrip needed.
 *
 * Key format: "app_id:item_key" (colon-separated, matches backend cache keys).
 * Value: list of Memory contents (item_value) for that category.
 */

const MEMORY_ENTRY_PATTERN =
  /@memory-entry:([a-zA-Z0-9_-]+):([a-zA-Z0-9_-]+):([a-zA-Z0-9_.-]+)/gi;
const MEMORY_PATTERN =
  /@memory:([a-zA-Z0-9_-]+):([a-zA-Z0-9_-]+):([a-zA-Z0-9_-]+)/gi;
const PERSONAL_MEMORIES_APP_ID = "openmates";
const PERSONAL_MEMORIES_CATEGORY_ID = "memories";

function slugifyMemoryTitle(title: string): string {
  return title.trim().toLowerCase().replace(/[^a-z0-9_.-]+/g, '-').replace(/^-+|-+$/g, '');
}

export type MentionedSettingsMemoriesCleartext = Record<string, unknown[]>;

/**
 * Parses message content for personal Memory mentions and returns the decrypted
 * content per category key (openmates:memories). Used when sending the message so
 * the backend receives cleartext and does not request those Memories again.
 *
 * @param content - Outgoing message content (markdown with mention syntax)
 * @returns Map of category key -> list of Memory contents (same shape as backend cache)
 */
export async function extractMentionedSettingsMemoriesCleartext(
  content: string,
): Promise<MentionedSettingsMemoriesCleartext> {
  const result: MentionedSettingsMemoriesCleartext = {};
  if (!/@memory(?:-entry)?:openmates:memories:/.test(content)) return result;

  const { personalDocumentMemoryEntries } = await import('./ruleDocumentService');
  const personalEntries = await personalDocumentMemoryEntries();
  const key = `${PERSONAL_MEMORIES_APP_ID}:${PERSONAL_MEMORIES_CATEGORY_ID}`;

  const seenEntryIds = new Set<string>();
  for (const match of content.matchAll(MEMORY_ENTRY_PATTERN)) {
    if (match[1] !== PERSONAL_MEMORIES_APP_ID || match[2] !== PERSONAL_MEMORIES_CATEGORY_ID) continue;
    const entryId = match[3];
    if (seenEntryIds.has(entryId)) continue;
    seenEntryIds.add(entryId);
    const wanted = entryId.toLowerCase();
    const found = personalEntries.find(entry => entry.id === entryId)
      ?? personalEntries.find(entry => slugifyMemoryTitle(String(entry.item_value.title ?? '')) === wanted);
    if (found) (result[key] ??= []).push(found.item_value);
  }

  for (const match of content.matchAll(MEMORY_PATTERN)) {
    if (match[1] !== PERSONAL_MEMORIES_APP_ID || match[2] !== PERSONAL_MEMORIES_CATEGORY_ID) continue;
    if (personalEntries.length > 0) result[key] = personalEntries.map(entry => entry.item_value);
  }

  return result;
}
