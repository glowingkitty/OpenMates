// frontend/packages/ui/src/services/embedRefIndex.ts
// Lightweight in-memory embed_ref index shared by parsing and rendering code.
// The map intentionally never persists because embed_ref slugs can reveal
// private content hints for encrypted chats. EmbedStore owns registration, while
// parse_message can read this module without importing IndexedDB-heavy services.
// Components subscribe to embedRefIndexVersion to refresh when refs arrive.

import { writable } from "svelte/store";

export interface EmbedRefIndexEntry {
  embedId: string;
  appId: string | null;
  skillId: string | null;
  type: string | null;
}

const embedRefToIdIndex = new Map<string, EmbedRefIndexEntry>();

export const embedRefIndexVersion = writable(0);

export function registerEmbedRefIndex(
  embedRef: string,
  entry: EmbedRefIndexEntry,
): void {
  if (!embedRef || !entry.embedId) return;
  const normalizedEntry = {
    embedId: entry.embedId,
    appId: entry.appId ?? null,
    skillId: entry.skillId ?? null,
    type: entry.type ?? null,
  };
  // Final message links may use either the human-readable ref or the stable ID.
  embedRefToIdIndex.set(embedRef, normalizedEntry);
  embedRefToIdIndex.set(entry.embedId, normalizedEntry);
  embedRefIndexVersion.update((n) => n + 1);
}

export function resolveEmbedRefIndexEntry(
  embedRef: string,
): EmbedRefIndexEntry | null {
  return embedRefToIdIndex.get(embedRef) ?? null;
}

export function clearEmbedRefIndexEntries(): void {
  embedRefToIdIndex.clear();
}
