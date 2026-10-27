/** Identity shared by the map, carousel, calendar and local result filters. */
interface ResultViewEntry {
  embedId: string | null;
  category: string;
  highlighted: boolean;
  status: 'loading' | 'ready' | 'unavailable';
  decodedContent?: Record<string, unknown> | null;
}

function eventIdentity(entry: ResultViewEntry): string | null {
  if (entry.category !== 'event') return null;
  const { url, date_start: start } = entry.decodedContent ?? {};
  // Without a source link and occurrence, keep separate results separate.
  if (typeof url !== 'string' || typeof start !== 'string' || !start.trim()) return null;
  const timestamp = Date.parse(start);
  if (!Number.isFinite(timestamp)) return null;
  try {
    const source = new URL(url);
    if (!['http:', 'https:'].includes(source.protocol)) return null;
    const occurrence = /^\d{4}-\d{2}-\d{2}$/.test(start.trim())
      ? `date:${start.trim()}` : `time:${timestamp}`;
    return JSON.stringify([source.href, occurrence]);
  } catch {
    return null;
  }
}

function mergeByIdentity<T extends ResultViewEntry>(entries: T[], identity: (entry: T) => string | null): T[] {
  const indices = new Map<string, number>();
  const unique: T[] = [];
  for (const entry of entries) {
    const key = identity(entry);
    const index = key == null ? undefined : indices.get(key);
    if (index == null) {
      if (key != null) indices.set(key, unique.length);
      unique.push(entry);
    } else {
      const previous = unique[index];
      const representative = previous.status !== 'ready' && entry.status === 'ready' ? entry : previous;
      unique[index] = {
        ...representative,
        highlighted: previous.highlighted || entry.highlighted,
      };
    }
  }
  return unique;
}

/** Preserve source order and highlights across aliases and repeated searches. */
export function deduplicateResultViewEntries<T extends ResultViewEntry>(entries: T[]): T[] {
  const canonical = mergeByIdentity(entries, (entry) => entry.embedId);
  return mergeByIdentity<T>(canonical, eventIdentity);
}
