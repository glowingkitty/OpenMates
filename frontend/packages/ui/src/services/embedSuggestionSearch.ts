// Composer-only matching over already-decrypted saved memories. No plaintext is persisted.
export interface SavedEmbedSuggestion {
  embedId: string;
  settingsPath?: string;
  title: string;
  subtitle: string;
  appId: string;
  updatedAt: number;
}

interface SavedMemoryEntryLike {
  id?: string;
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
        const settingsPath = entry.id
          ? `apps/${appId}/settings_memories/${groupName}/entry/${entry.id}`
          : undefined;
        const candidate = { embedId, settingsPath, title, subtitle, appId, updatedAt: entry.updated_at ?? 0, searchText };
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

/** Legacy saves retain useful item fields even when the original embed is unavailable. */
export function getSavedEmbedFullscreenFallback(
  state: SavedMemoriesLike,
  embedId: string,
  settingsPath?: string,
): { embedType: string; decodedContent: Record<string, unknown> } | null {
  const kinds: Record<string, { embedType: string; skillId: string }> = {
    'events/saved_events': { embedType: 'events-event', skillId: 'event' },
    'home/saved_listings': { embedType: 'home-listing', skillId: 'listing' },
    'travel/saved_stays': { embedType: 'travel-stay', skillId: 'stay' },
    'travel/saved_connections': { embedType: 'travel-connection', skillId: 'connection' },
    'health/appointments': { embedType: 'health-appointment', skillId: 'appointment' },
  };
  for (const [appId, groups] of state.entriesByApp) {
    for (const [groupName, entries] of Object.entries(groups)) {
      const kind = kinds[`${appId}/${groupName}`];
      if (!kind) continue;
      const entry = entries.find(item => item.item_value.embed_id === embedId && (!settingsPath ||
        settingsPath === `apps/${appId}/settings_memories/${groupName}/entry/${item.id}`));
      if (!entry) continue;
      const value = entry.item_value;
      const decodedContent: Record<string, unknown> = {
        ...value, app_id: appId, skill_id: kind.skillId,
      };
      if (kind.embedType === 'events-event') {
        decodedContent.venue_address = stringValue(value.location);
        decodedContent.description = stringValue(value.notes);
      } else if (kind.embedType === 'health-appointment') {
        decodedContent.name = stringValue(value.where);
        decodedContent.slot_datetime = stringValue(value.appointment_time);
      }
      return { embedType: kind.embedType, decodedContent };
    }
  }
  return null;
}
