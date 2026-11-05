/**
 * Thin adapter for the shared Rust web search and PII display alias ports
 * (U16/U18). Exports in packages/openmates-browser-bindings/src/browser_search_pii.rs.
 *
 * Flag-off contract: with VITE_OPENMATES_RUST_CORE unset nothing here is
 * constructed and searchService.ts / embedSuggestionSearch.ts / piiDisplayAliases.ts
 * stay authoritative. The coordinator wires an instance through the shared worker:
 *
 *   const adapter = createSearchPiiAdapter(binding);   // binding = wasm module exports
 *   adapter.findMatchRanges(text, query)                // == searchService.findMatchRanges
 *   adapter.buildSnippet(content, start, length)        // == searchService.buildSnippet
 *   adapter.searchSavedEmbedMemories(state, query, 6)   // == embedSuggestionSearch
 *   adapter.createPIIDisplayAliases(src, mappings, cfg) // == piiDisplayAliases
 *
 * All offsets are UTF-16 code units. A malformed payload rejects with the code
 * `protocol`. The adapter never falls back to the TypeScript implementations.
 */
import type { PIIMapping } from '../../../types/chat';
import type { SavedEmbedSuggestion, SavedMemoriesLike } from '../../embedSuggestionSearch';

/** Worker module exports (snake_case, JSON strings). */
export interface SearchPiiBinding {
  search_find_match_ranges(text: string, query: string): string;
  search_build_snippet(content: string, matchStart: number, matchLength: number): string;
  search_saved_embed_memories(entriesJson: string, query: string, limit: number): string;
  pii_create_display_aliases(sourceJson: string, mappingsJson: string, configuredJson: string): string;
}

export interface SearchPiiAdapter {
  findMatchRanges(text: string, query: string): Array<{ start: number; length: number }>;
  buildSnippet(content: string, matchStart: number, matchLength: number): { snippet: string; snippetMatchStart: number; snippetMatchLength: number };
  searchSavedEmbedMemories(state: SavedMemoriesLike, query: string, limit?: number): SavedEmbedSuggestion[];
  createPIIDisplayAliases(
    sourceContent: string | Record<string, unknown> | null,
    mappings: readonly PIIMapping[],
    configuredReplacements?: readonly string[],
  ): ReadonlyMap<string, string>;
}

type OrderedSource = string | null | OrderedSource[] | { $entries: Array<[string, OrderedSource]> };

/** Objects become ordered pairs so Object.values order crosses the boundary exactly. */
export function toOrderedSource(value: unknown): OrderedSource {
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return value.map(toOrderedSource);
  if (value && typeof value === 'object') {
    return { $entries: Object.entries(value).map(([key, node]) => [key, toOrderedSource(node)] as [string, OrderedSource]) };
  }
  return null;
}

export function toOrderedMemories(entriesByApp: SavedMemoriesLike['entriesByApp']) {
  return Array.from(entriesByApp, ([appId, groups]) => [
    appId,
    Object.entries(groups).map(([group, entries]) => [
      group,
      entries.map(entry => ({
        id: entry.id,
        item_value: entry.item_value && typeof entry.item_value === 'object' ? Object.entries(entry.item_value) : [],
        updated_at: entry.updated_at,
      })),
    ]),
  ]);
}

export function createSearchPiiAdapter(binding: SearchPiiBinding): SearchPiiAdapter {
  return {
    findMatchRanges: (text, query) => JSON.parse(binding.search_find_match_ranges(text, query)),
    buildSnippet: (content, start, length) => JSON.parse(binding.search_build_snippet(content, start, length)),
    searchSavedEmbedMemories: (state, query, limit = 6) =>
      JSON.parse(binding.search_saved_embed_memories(JSON.stringify(toOrderedMemories(state.entriesByApp)), query, limit)),
    createPIIDisplayAliases: (sourceContent, mappings, configuredReplacements = []) =>
      new Map(JSON.parse(binding.pii_create_display_aliases(
        JSON.stringify(toOrderedSource(sourceContent)),
        JSON.stringify(mappings),
        JSON.stringify(configuredReplacements),
      )) as Array<[string, string]>),
  };
}
