/*
 * Bounded Task Activity reads and explicit full-history search.
 * Routine context reads stop at a hard entry limit; search scans every page
 * but retains only a bounded number of matches. Decryption remains local.
 * Cursor order is supplied by the existing Task Activity API.
 * Tests: tests/taskActivityHistory.test.ts.
 */
export async function readActivityHistory<T extends { message?: string }>(options: {
  page: (cursor: string | undefined, limit: number) => Promise<{ entries: T[]; next_cursor?: string | null }>;
  maxEntries?: number;
  pageSize?: number;
  query?: string;
  cursor?: string;
}): Promise<{ entries: T[]; next_cursor: string | null; truncated: boolean; matched: number }> {
  const { query } = options;
  const maxEntries = options.maxEntries ?? Infinity;
  if (options.maxEntries !== undefined && (!Number.isSafeInteger(maxEntries) || maxEntries < 1 || maxEntries > 200)) {
    throw new Error("--max-entries must be an integer from 1 to 200");
  }
  if (query !== undefined && !query.trim()) throw new Error("Activity search requires a non-empty --query");
  const pageSize = options.pageSize ?? 100;
  if (!Number.isSafeInteger(pageSize) || pageSize < 1 || pageSize > 200) throw new Error("--limit must be from 1 to 200");
  const entries: T[] = [];
  const seen = new Set<string>();
  let cursor = options.cursor;
  let matched = 0;
  do {
    const page = await options.page(cursor, query === undefined ? Math.min(pageSize, maxEntries - entries.length) : pageSize);
    for (const entry of page.entries) {
      if (query === undefined || (entry.message || "").toLocaleLowerCase().includes(query.toLocaleLowerCase())) {
        matched++;
        if (entries.length < maxEntries) entries.push(entry);
      }
    }
    cursor = page.next_cursor || undefined;
    if (cursor && seen.has(cursor)) throw new Error("Activity pagination repeated a cursor");
    if (cursor) seen.add(cursor);
  } while (cursor && (query !== undefined || entries.length < maxEntries));
  return { entries, next_cursor: cursor || null, truncated: Boolean(cursor) || matched > entries.length, matched };
}
