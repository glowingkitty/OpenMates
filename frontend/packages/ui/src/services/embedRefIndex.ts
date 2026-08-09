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

export interface ResolvedEmbedRefIndexReference {
  embedRef: string;
  entry: EmbedRefIndexEntry;
}

const embedRefToIdIndex = new Map<string, EmbedRefIndexEntry>();
const EMBED_REF_UNICODE_DASH_RE = /[\u2010\u2011\u2012\u2013\u2014\u2015\u2212]/g;
const EMBED_REF_SUFFIX_ONLY_RE = /^-[A-Za-z0-9]{2,4}$/;

export const embedRefIndexVersion = writable(0);

function normalizeEmbedRefToken(embedRef: string): string {
  return embedRef.trim().replace(EMBED_REF_UNICODE_DASH_RE, "-");
}

function normalizeEmbedRefSuffixLookupKey(embedRef: string): string {
  return normalizeEmbedRefToken(embedRef).toLowerCase();
}

function entriesMatch(
  left: EmbedRefIndexEntry | undefined,
  right: EmbedRefIndexEntry,
): boolean {
  return (
    left?.embedId === right.embedId &&
    left.appId === right.appId &&
    left.skillId === right.skillId &&
    left.type === right.type
  );
}

export function registerEmbedRefIndex(
  embedRef: string,
  entry: EmbedRefIndexEntry,
): void {
  if (!embedRef || !entry.embedId) return;
  const normalizedEmbedRef = normalizeEmbedRefToken(embedRef);
  if (!normalizedEmbedRef) return;
  const normalizedEntry = {
    embedId: entry.embedId,
    appId: entry.appId ?? null,
    skillId: entry.skillId ?? null,
    type: entry.type ?? null,
  };
  // Final message links may use either the human-readable ref or the stable ID.
  const refEntry = embedRefToIdIndex.get(normalizedEmbedRef);
  const idEntry = embedRefToIdIndex.get(entry.embedId);
  embedRefToIdIndex.set(normalizedEmbedRef, normalizedEntry);
  embedRefToIdIndex.set(entry.embedId, normalizedEntry);
  if (!entriesMatch(refEntry, normalizedEntry) || !entriesMatch(idEntry, normalizedEntry)) {
    embedRefIndexVersion.update((n) => n + 1);
  }
}

export function resolveEmbedRefIndexReference(
  embedRef: string,
): ResolvedEmbedRefIndexReference | null {
  const normalizedEmbedRef = normalizeEmbedRefToken(embedRef);
  const exactEntry = embedRefToIdIndex.get(normalizedEmbedRef);
  if (exactEntry) return { embedRef: normalizedEmbedRef, entry: exactEntry };

  if (!EMBED_REF_SUFFIX_ONLY_RE.test(normalizedEmbedRef)) return null;

  let resolved: ResolvedEmbedRefIndexReference | null = null;
  const suffixLookupKey = normalizeEmbedRefSuffixLookupKey(normalizedEmbedRef);
  for (const [candidateRef, entry] of Array.from(embedRefToIdIndex.entries())) {
    if (
      candidateRef === entry.embedId ||
      !normalizeEmbedRefSuffixLookupKey(candidateRef).endsWith(suffixLookupKey)
    ) {
      continue;
    }
    if (resolved && resolved.entry.embedId !== entry.embedId) return null;
    if (!resolved) resolved = { embedRef: candidateRef, entry };
  }
  return resolved;
}

export function resolveEmbedRefIndexEntry(
  embedRef: string,
): EmbedRefIndexEntry | null {
  return resolveEmbedRefIndexReference(embedRef)?.entry ?? null;
}

export function clearEmbedRefIndexEntries(): void {
  embedRefToIdIndex.clear();
}
