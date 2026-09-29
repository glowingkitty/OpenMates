// Composer-only matching over already-decrypted saved memories. No plaintext is persisted.
export interface SavedEmbedSuggestion {
  embedId: string;
  title: string;
  subtitle: string;
  appId: string;
  updatedAt: number;
}

interface SavedMemoryEntryLike {
  item_value: Record<string, unknown>;
  updated_at?: number;
}

export interface SavedMemoriesLike {
  entriesByApp: Map<string, Record<string, SavedMemoryEntryLike[]>>;
}

interface IndexedSavedEmbed extends SavedEmbedSuggestion {
  searchText: string;
}

const indexByEntries = new WeakMap<SavedMemoriesLike['entriesByApp'], IndexedSavedEmbed[]>();

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function buildIndex(entriesByApp: SavedMemoriesLike['entriesByApp']): IndexedSavedEmbed[] {
  const byId = new Map<string, IndexedSavedEmbed>();
  for (const [appId, groups] of Array.from(entriesByApp)) {
    for (const [groupName, entries] of Object.entries(groups)) {
      for (const entry of entries) {
        const value = entry.item_value;
        const embedId = stringValue(value?.embed_id);
        if (!embedId) continue;
        const title = stringValue(value.title) || stringValue(value.name) || groupName.replace(/_/g, ' ');
        const subtitle = [value.location, value.address, value.where, value.origin, value.destination, value.provider, value.date_start]
          .map(stringValue).filter(Boolean).join(' · ').slice(0, 160);
        const metadata = Object.entries(value)
          .filter(([key]) => !['embed_id', 'url', 'booking_url', 'link'].includes(key))
          .map(([, field]) => stringValue(field).slice(0, 120))
          .filter(Boolean).join(' ').slice(0, 500);
        const searchText = [title, metadata].join(' ').toLowerCase();
        const candidate = { embedId, title, subtitle, appId, updatedAt: entry.updated_at ?? 0, searchText };
        if (!byId.has(embedId) || byId.get(embedId)!.updatedAt < candidate.updatedAt) byId.set(embedId, candidate);
      }
    }
  }
  return Array.from(byId.values()).sort((a, b) => b.updatedAt - a.updatedAt);
}

export function searchSavedEmbedMemories(
  state: SavedMemoriesLike,
  query: string,
  limit = 6,
): SavedEmbedSuggestion[] {
  const normalized = query.trim().toLowerCase();
  if (!normalized || limit <= 0) return [];
  let index = indexByEntries.get(state.entriesByApp);
  if (!index) {
    index = buildIndex(state.entriesByApp);
    indexByEntries.set(state.entriesByApp, index);
  }
  const matches: IndexedSavedEmbed[] = [];
  for (const entry of index) {
    if (!entry.searchText.includes(normalized)) continue;
    matches.push(entry);
  }
  matches.sort((a, b) => {
    const aTitle = a.title.toLowerCase().includes(normalized) ? 1 : 0;
    const bTitle = b.title.toLowerCase().includes(normalized) ? 1 : 0;
    return bTitle - aTitle || b.updatedAt - a.updatedAt;
  });
  return matches.slice(0, limit).map(({ searchText: _searchText, ...result }) => result);
}
